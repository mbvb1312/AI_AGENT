"""
Context-Aware Interruption Handler for LiveKit Agents

This module implements intelligent interruption handling that distinguishes between
passive acknowledgements (e.g., "yeah", "ok", "hmm") and active interruptions
(e.g., "stop", "wait", "no") based on whether the agent is currently speaking.

PRIMARY FEATURE (Behavior-affecting):
- When agent is speaking + user says passive acknowledgement → IGNORE (no pause/stop)
- When agent is speaking + user says interrupt command → INTERRUPT immediately
- When agent is silent + user says anything → PROCESS normally

ADDITIONAL FEATURES (Observational only - do not affect behavior):
- User Engagement Level tracking
- User Satisfaction Score tracking

Author: Vignesh Balamurugan
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Set, Tuple

logger = logging.getLogger("livekit.agents.interruption_handler")


# =============================================================================
# CONFIGURABLE WORD GROUPS
# =============================================================================

def _get_env_words(env_var: str, default: Set[str]) -> Set[str]:
    """Load word set from environment variable or use default."""
    env_value = os.getenv(env_var)
    if env_value:
        return set(w.strip().lower() for w in env_value.split(",") if w.strip())
    return default


# Passive acknowledgements - IGNORE ONLY while agent is speaking
DEFAULT_PASSIVE_ACKNOWLEDGEMENTS: Set[str] = {
    # affirmatives
    "yeah", "yep", "yup", "yes",
    # ok variations
    "ok", "okay", "k",
    # thinking sounds
    "hmm", "hmmm", "mmm", "mmmm", "uh", "uhh", "um", "umm",
    # agreement sounds
    "uh-huh", "uh huh", "mm-hmm", "mm hmm", "mhm", "mmhmm",
    # understanding
    "right", "alright", "i see", "got it", "gotcha",
    # casual agreement
    "sure", "fine", "cool", "nice", "good", "great",
    # continuers
    "go on", "continue", "and",
}

# Active interruption commands - ALWAYS interrupt when detected
DEFAULT_INTERRUPT_COMMANDS: Set[str] = {
    # stop commands
    "stop", "wait", "pause", "hold",
    # negatives that indicate correction
    "no", "nope", "cancel", "never mind", "nevermind",
    # attention demands
    "hold on", "listen", "hey", "excuse me",
    # turn-taking
    "let me speak", "let me talk", "my turn", "actually",
    # corrections
    "wrong", "incorrect", "that's wrong", "not right",
}

# Positive satisfaction indicators
DEFAULT_POSITIVE_INDICATORS: Set[str] = {
    "yes", "yeah", "great", "good", "nice", "perfect", "works",
    "fine", "awesome", "excellent", "wonderful", "thanks", "thank you",
    "helpful", "correct", "exactly", "right", "understood",
}

# Negative satisfaction indicators
DEFAULT_NEGATIVE_INDICATORS: Set[str] = {
    "no", "stop", "wait", "wrong", "bad", "problem", "issue",
    "confusing", "unclear", "annoyed", "frustrated", "don't understand",
    "what", "huh", "repeat", "again", "slower",
}


class EngagementLevel(Enum):
    """User engagement level based on passive acknowledgement frequency."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InterruptionDecision(Enum):
    """Decision on how to handle user speech."""
    IGNORE = "IGNORE"          # Continue speaking, ignore input completely
    INTERRUPT = "INTERRUPT"    # Stop speaking immediately
    PROCESS = "PROCESS"        # Process input normally (agent is silent)


@dataclass
class InterruptionResult:
    """Result of interruption classification."""
    decision: InterruptionDecision
    reason: str
    normalized_text: str
    detected_commands: List[str] = field(default_factory=list)
    detected_acknowledgements: List[str] = field(default_factory=list)


@dataclass
class EngagementState:
    """Tracks user engagement through passive acknowledgements."""
    acknowledgement_timestamps: List[float] = field(default_factory=list)
    window_seconds: float = 8.0
    
    def add_acknowledgement(self) -> None:
        """Record a passive acknowledgement."""
        self.acknowledgement_timestamps.append(time.time())
        self._cleanup_old()
    
    def _cleanup_old(self) -> None:
        """Remove acknowledgements outside the time window."""
        cutoff = time.time() - self.window_seconds
        self.acknowledgement_timestamps = [
            t for t in self.acknowledgement_timestamps if t > cutoff
        ]
    
    def get_level(self) -> EngagementLevel:
        """Calculate current engagement level."""
        self._cleanup_old()
        count = len(self.acknowledgement_timestamps)
        if count >= 3:
            return EngagementLevel.HIGH
        elif count >= 1:
            return EngagementLevel.MEDIUM
        return EngagementLevel.LOW
    
    def get_count(self) -> int:
        """Get current acknowledgement count in window."""
        self._cleanup_old()
        return len(self.acknowledgement_timestamps)


@dataclass
class SatisfactionState:
    """Tracks user satisfaction score based on lexical signals."""
    score: float = 0.0
    last_signal: str = ""
    last_text: str = ""
    
    # Score adjustment amounts
    POSITIVE_DELTA: float = 0.15
    NEGATIVE_DELTA: float = 0.20
    DECAY_RATE: float = 0.05  # Slight decay toward neutral over time
    
    def update(self, text: str, positive_indicators: Set[str], negative_indicators: Set[str]) -> None:
        """Update satisfaction based on detected indicators."""
        normalized = _normalize_text(text)
        words = set(normalized.split())
        
        positive_found = words & positive_indicators
        negative_found = words & negative_indicators
        
        if positive_found and not negative_found:
            self.score = min(1.0, self.score + self.POSITIVE_DELTA)
            self.last_signal = "positive"
            self.last_text = text
            logger.info(
                f"[SATISFACTION] score={self.score:+.2f} signal=positive "
                f"(\"{text[:50]}\")"
            )
        elif negative_found:
            self.score = max(-1.0, self.score - self.NEGATIVE_DELTA)
            self.last_signal = "negative"
            self.last_text = text
            logger.info(
                f"[SATISFACTION] score={self.score:+.2f} signal=negative "
                f"(\"{text[:50]}\")"
            )
    
    def decay(self) -> None:
        """Apply slight decay toward neutral."""
        if abs(self.score) > 0.01:
            if self.score > 0:
                self.score = max(0, self.score - self.DECAY_RATE)
            else:
                self.score = min(0, self.score + self.DECAY_RATE)


def _normalize_text(text: str) -> str:
    """
    Normalize user input for classification.
    - lowercase
    - trim whitespace  
    - remove punctuation (except hyphens in words like uh-huh)
    - collapse repeated spaces
    """
    if not text:
        return ""
    
    # Lowercase and trim
    text = text.lower().strip()
    
    # Remove punctuation but keep hyphens between word characters
    # Replace punctuation with space
    text = re.sub(r"[^\w\s-]", " ", text)
    
    # Clean up standalone hyphens
    text = re.sub(r"(?<!\w)-|-(?!\w)", " ", text)
    
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    
    return text.strip()


def _tokenize(text: str) -> List[str]:
    """Split normalized text into tokens."""
    return text.split() if text else []


def _contains_any_phrase(text: str, phrases: Set[str]) -> Tuple[bool, List[str]]:
    """
    Check if text contains any phrase from the set.
    Handles both single words and multi-word phrases.
    Returns (found, list_of_matches).
    """
    found = []
    
    # Check multi-word phrases first
    for phrase in phrases:
        if " " in phrase and phrase in text:
            found.append(phrase)
    
    # Check single words
    words = set(_tokenize(text))
    for phrase in phrases:
        if " " not in phrase and phrase in words:
            found.append(phrase)
    
    return len(found) > 0, found


def _is_only_acknowledgements(text: str, acknowledgements: Set[str]) -> bool:
    """
    Check if text contains ONLY passive acknowledgement words/phrases.
    Returns True only if every token is an acknowledgement.
    """
    if not text:
        return False
    
    # First remove any multi-word acknowledgement phrases from text
    remaining = text
    for phrase in acknowledgements:
        if " " in phrase:
            remaining = remaining.replace(phrase, " ")
    
    # Check remaining single words
    words = _tokenize(remaining)
    if not words:
        return True  # All content was multi-word phrases
    
    single_word_acks = {p for p in acknowledgements if " " not in p}
    return all(w in single_word_acks for w in words)


class InterruptionHandler:
    """
    Main handler for context-aware interruption decisions.
    
    This class implements the core logic for distinguishing between
    passive acknowledgements and active interruptions based on agent state.
    """
    
    def __init__(self):
        # Load configurable word sets
        self.passive_acknowledgements = _get_env_words(
            "AGENT_PASSIVE_WORDS",
            DEFAULT_PASSIVE_ACKNOWLEDGEMENTS
        )
        self.interrupt_commands = _get_env_words(
            "AGENT_INTERRUPT_WORDS",
            DEFAULT_INTERRUPT_COMMANDS
        )
        self.positive_indicators = _get_env_words(
            "AGENT_POSITIVE_WORDS",
            DEFAULT_POSITIVE_INDICATORS
        )
        self.negative_indicators = _get_env_words(
            "AGENT_NEGATIVE_WORDS",
            DEFAULT_NEGATIVE_INDICATORS
        )
        
        # Observational state (does not affect behavior)
        self.engagement_state = EngagementState()
        self.satisfaction_state = SatisfactionState()
        
        logger.info(
            f"InterruptionHandler initialized with "
            f"{len(self.passive_acknowledgements)} passive words, "
            f"{len(self.interrupt_commands)} interrupt commands"
        )
    
    def classify(
        self,
        text: str,
        agent_is_speaking: bool,
    ) -> InterruptionResult:
        """
        Classify user input and determine how to handle it.
        
        Args:
            text: The user's transcribed speech
            agent_is_speaking: Whether the agent is currently speaking/playing audio
            
        Returns:
            InterruptionResult with the decision and reasoning
        """
        normalized = _normalize_text(text)
        
        if not normalized:
            return InterruptionResult(
                decision=InterruptionDecision.IGNORE,
                reason="empty input",
                normalized_text=normalized,
            )
        
        # Check for interrupt commands
        has_interrupt, interrupt_matches = _contains_any_phrase(
            normalized, self.interrupt_commands
        )
        
        # Check for acknowledgements
        has_ack, ack_matches = _contains_any_phrase(
            normalized, self.passive_acknowledgements
        )
        is_only_ack = _is_only_acknowledgements(normalized, self.passive_acknowledgements)
        
        # === CORE DECISION LOGIC ===
        
        if not agent_is_speaking:
            # Agent is silent - process all input normally
            # Also update satisfaction score (observational only)
            self.satisfaction_state.update(
                text, self.positive_indicators, self.negative_indicators
            )
            return InterruptionResult(
                decision=InterruptionDecision.PROCESS,
                reason="agent is silent, processing normally",
                normalized_text=normalized,
                detected_commands=interrupt_matches,
                detected_acknowledgements=ack_matches,
            )
        
        # Agent IS speaking - apply filtering logic
        
        if has_interrupt:
            # Contains interrupt command - ALWAYS interrupt
            logger.debug(
                f"[INTERRUPT] Detected interrupt command while agent speaking: "
                f"{interrupt_matches} in \"{text[:50]}\""
            )
            return InterruptionResult(
                decision=InterruptionDecision.INTERRUPT,
                reason=f"interrupt command detected: {interrupt_matches}",
                normalized_text=normalized,
                detected_commands=interrupt_matches,
                detected_acknowledgements=ack_matches,
            )
        
        if is_only_ack:
            # Contains ONLY passive acknowledgements - IGNORE
            # Update engagement tracking (observational only)
            self.engagement_state.add_acknowledgement()
            level = self.engagement_state.get_level()
            count = self.engagement_state.get_count()
            
            logger.info(
                f"[ENGAGEMENT] passive_ack={count} "
                f"window={self.engagement_state.window_seconds}s "
                f"level={level.value}"
            )
            logger.debug(
                f"[IGNORE] Passive acknowledgement while agent speaking: "
                f"{ack_matches} in \"{text[:50]}\""
            )
            
            return InterruptionResult(
                decision=InterruptionDecision.IGNORE,
                reason=f"passive acknowledgement only: {ack_matches}",
                normalized_text=normalized,
                detected_commands=[],
                detected_acknowledgements=ack_matches,
            )
        
        # Contains other content - default to interrupt for safety
        logger.debug(
            f"[INTERRUPT] Non-acknowledgement content while agent speaking: "
            f"\"{text[:50]}\""
        )
        return InterruptionResult(
            decision=InterruptionDecision.INTERRUPT,
            reason="contains non-acknowledgement content",
            normalized_text=normalized,
            detected_commands=interrupt_matches,
            detected_acknowledgements=ack_matches,
        )
    
    def should_interrupt(self, text: str, agent_is_speaking: bool) -> bool:
        """
        Convenience method returning True if agent should be interrupted.
        
        Args:
            text: The user's transcribed speech
            agent_is_speaking: Whether the agent is currently speaking
            
        Returns:
            True if agent should be interrupted, False otherwise
        """
        result = self.classify(text, agent_is_speaking)
        return result.decision == InterruptionDecision.INTERRUPT
    
    def should_ignore(self, text: str, agent_is_speaking: bool) -> bool:
        """
        Convenience method returning True if input should be ignored.
        
        Args:
            text: The user's transcribed speech
            agent_is_speaking: Whether the agent is currently speaking
            
        Returns:
            True if input should be ignored, False otherwise
        """
        result = self.classify(text, agent_is_speaking)
        return result.decision == InterruptionDecision.IGNORE
    
    def get_engagement_level(self) -> EngagementLevel:
        """Get current user engagement level (observational only)."""
        return self.engagement_state.get_level()
    
    def get_satisfaction_score(self) -> float:
        """Get current user satisfaction score (observational only)."""
        return self.satisfaction_state.score
    
    def log_state(self) -> None:
        """Log current observational state."""
        engagement = self.engagement_state.get_level()
        satisfaction = self.satisfaction_state.score
        ack_count = self.engagement_state.get_count()
        
        logger.info(
            f"[STATE] engagement={engagement.value} "
            f"(ack_count={ack_count}) "
            f"satisfaction={satisfaction:+.2f}"
        )


# Global singleton instance for easy access
_handler_instance: InterruptionHandler | None = None


def get_interruption_handler() -> InterruptionHandler:
    """Get the global InterruptionHandler instance."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = InterruptionHandler()
    return _handler_instance


def reset_interruption_handler() -> None:
    """Reset the global handler (useful for testing)."""
    global _handler_instance
    _handler_instance = None
