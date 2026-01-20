"""
Test suite for the Context-Aware Interruption Handler.

Run with: python -m pytest tests/test_interruption_handler.py -v
"""

import pytest
import sys
import os

# Add the livekit-agents path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'livekit-agents'))

from livekit.agents.voice.interruption_handler import (
    InterruptionHandler,
    InterruptionDecision,
    EngagementLevel,
    _normalize_text,
    _is_only_acknowledgements,
    DEFAULT_PASSIVE_ACKNOWLEDGEMENTS,
    DEFAULT_INTERRUPT_COMMANDS,
)


class TestNormalization:
    """Test text normalization."""
    
    def test_lowercase(self):
        assert _normalize_text("YEAH") == "yeah"
        assert _normalize_text("Ok") == "ok"
    
    def test_trim_whitespace(self):
        assert _normalize_text("  yeah  ") == "yeah"
        assert _normalize_text("\tyeah\n") == "yeah"
    
    def test_remove_punctuation(self):
        assert _normalize_text("yeah!") == "yeah"
        assert _normalize_text("ok...") == "ok"
        assert _normalize_text("hmm?") == "hmm"
        assert _normalize_text("okay...yeah!!") == "okay yeah"
    
    def test_preserve_hyphens(self):
        assert _normalize_text("uh-huh") == "uh-huh"
        assert _normalize_text("mm-hmm") == "mm-hmm"
    
    def test_collapse_spaces(self):
        assert _normalize_text("yeah   ok") == "yeah ok"
        assert _normalize_text("a   b   c") == "a b c"
    
    def test_complex_normalization(self):
        assert _normalize_text(" Okay... yeah!! ") == "okay yeah"
        assert _normalize_text("  UH-HUH!  ") == "uh-huh"


class TestAcknowledgementDetection:
    """Test detection of acknowledgement-only input."""
    
    def test_single_acknowledgement(self):
        acks = DEFAULT_PASSIVE_ACKNOWLEDGEMENTS
        assert _is_only_acknowledgements("yeah", acks) is True
        assert _is_only_acknowledgements("ok", acks) is True
        assert _is_only_acknowledgements("hmm", acks) is True
    
    def test_multiple_acknowledgements(self):
        acks = DEFAULT_PASSIVE_ACKNOWLEDGEMENTS
        assert _is_only_acknowledgements("yeah ok", acks) is True
        assert _is_only_acknowledgements("hmm yeah ok", acks) is True
    
    def test_non_acknowledgement(self):
        acks = DEFAULT_PASSIVE_ACKNOWLEDGEMENTS
        assert _is_only_acknowledgements("hello", acks) is False
        assert _is_only_acknowledgements("stop", acks) is False
    
    def test_mixed_content(self):
        acks = DEFAULT_PASSIVE_ACKNOWLEDGEMENTS
        assert _is_only_acknowledgements("yeah but wait", acks) is False
        assert _is_only_acknowledgements("ok stop", acks) is False
    
    def test_empty_input(self):
        acks = DEFAULT_PASSIVE_ACKNOWLEDGEMENTS
        assert _is_only_acknowledgements("", acks) is False


class TestInterruptionHandler:
    """Test the main InterruptionHandler class."""
    
    @pytest.fixture
    def handler(self):
        return InterruptionHandler()
    
    # === Agent is SPEAKING ===
    
    def test_ignore_passive_while_speaking(self, handler):
        """Passive acknowledgements should be IGNORED while agent is speaking."""
        result = handler.classify("yeah", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
        
        result = handler.classify("ok", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
        
        result = handler.classify("hmm", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
        
        result = handler.classify("uh-huh", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
    
    def test_ignore_multiple_passive_while_speaking(self, handler):
        """Multiple passive acknowledgements should still be IGNORED."""
        result = handler.classify("yeah ok hmm", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
        
        result = handler.classify("uh-huh yeah ok", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
    
    def test_interrupt_command_while_speaking(self, handler):
        """Interrupt commands should ALWAYS interrupt."""
        result = handler.classify("stop", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
        
        result = handler.classify("wait", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
        
        result = handler.classify("no", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
    
    def test_mixed_input_while_speaking(self, handler):
        """Mixed input containing command should INTERRUPT."""
        result = handler.classify("yeah okay but wait", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
        
        result = handler.classify("ok stop", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
        
        result = handler.classify("yeah no", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
    
    def test_unknown_content_while_speaking(self, handler):
        """Unknown content should default to INTERRUPT (safe behavior)."""
        result = handler.classify("hello there", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
        
        result = handler.classify("I have a question", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
    
    # === Agent is SILENT ===
    
    def test_process_passive_while_silent(self, handler):
        """Passive acknowledgements should be PROCESSED when agent is silent."""
        result = handler.classify("yeah", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
        
        result = handler.classify("ok", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
    
    def test_process_command_while_silent(self, handler):
        """Commands should be PROCESSED when agent is silent."""
        result = handler.classify("stop", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
        
        result = handler.classify("wait", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
    
    def test_process_any_while_silent(self, handler):
        """Any input should be PROCESSED when agent is silent."""
        result = handler.classify("hello", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
        
        result = handler.classify("tell me more", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
    
    # === Edge cases ===
    
    def test_empty_input(self, handler):
        """Empty input should be IGNORED."""
        result = handler.classify("", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
        
        result = handler.classify("   ", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
    
    def test_punctuation_only(self, handler):
        """Punctuation-only input should be IGNORED."""
        result = handler.classify("...", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
    
    def test_convenience_methods(self, handler):
        """Test should_interrupt and should_ignore convenience methods."""
        assert handler.should_ignore("yeah", agent_is_speaking=True) is True
        assert handler.should_interrupt("yeah", agent_is_speaking=True) is False
        
        assert handler.should_interrupt("stop", agent_is_speaking=True) is True
        assert handler.should_ignore("stop", agent_is_speaking=True) is False


class TestEngagementTracking:
    """Test engagement level tracking (observational feature)."""
    
    @pytest.fixture
    def handler(self):
        return InterruptionHandler()
    
    def test_initial_engagement_low(self, handler):
        """Initial engagement should be LOW."""
        assert handler.get_engagement_level() == EngagementLevel.LOW
    
    def test_engagement_increases_with_acks(self, handler):
        """Engagement should increase as acknowledgements are detected."""
        # Process acknowledgements while speaking to trigger tracking
        handler.classify("yeah", agent_is_speaking=True)
        level = handler.get_engagement_level()
        assert level in [EngagementLevel.MEDIUM, EngagementLevel.HIGH]
    
    def test_engagement_tracks_multiple_acks(self, handler):
        """Multiple acknowledgements should increase engagement level."""
        for _ in range(3):
            handler.classify("yeah", agent_is_speaking=True)
        
        assert handler.get_engagement_level() == EngagementLevel.HIGH


class TestSatisfactionTracking:
    """Test satisfaction score tracking (observational feature)."""
    
    @pytest.fixture
    def handler(self):
        return InterruptionHandler()
    
    def test_initial_satisfaction_neutral(self, handler):
        """Initial satisfaction should be neutral (0.0)."""
        assert handler.get_satisfaction_score() == 0.0
    
    def test_positive_satisfaction(self, handler):
        """Positive indicators should increase satisfaction."""
        # Satisfaction updates when agent is silent
        handler.classify("great", agent_is_speaking=False)
        assert handler.get_satisfaction_score() > 0
    
    def test_negative_satisfaction(self, handler):
        """Negative indicators should decrease satisfaction."""
        # Satisfaction updates when agent is silent
        handler.classify("wrong", agent_is_speaking=False)
        assert handler.get_satisfaction_score() < 0
    
    def test_satisfaction_clamped(self, handler):
        """Satisfaction should be clamped between -1.0 and 1.0."""
        # Push satisfaction to extremes
        for _ in range(20):
            handler.classify("great perfect awesome", agent_is_speaking=False)
        assert handler.get_satisfaction_score() <= 1.0
        
        for _ in range(40):
            handler.classify("wrong bad problem", agent_is_speaking=False)
        assert handler.get_satisfaction_score() >= -1.0


class TestScenarios:
    """Test the example scenarios from the requirements."""
    
    @pytest.fixture
    def handler(self):
        return InterruptionHandler()
    
    def test_scenario1_long_explanation(self, handler):
        """
        Scenario 1: Agent is reading a long paragraph about history.
        User says "Okay... yeah... uh-huh" while Agent is talking.
        Expected: Agent audio does not break. Ignores user input completely.
        """
        result = handler.classify("Okay... yeah... uh-huh", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.IGNORE
    
    def test_scenario2_passive_affirmation(self, handler):
        """
        Scenario 2: Agent asks "Are you ready?" and goes silent.
        User says "Yeah."
        Expected: Agent processes "Yeah" as an answer.
        """
        result = handler.classify("Yeah", agent_is_speaking=False)
        assert result.decision == InterruptionDecision.PROCESS
    
    def test_scenario3_correction(self, handler):
        """
        Scenario 3: Agent is counting "One, two, three..."
        User says "No stop."
        Expected: Agent cuts off immediately.
        """
        result = handler.classify("No stop", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT
    
    def test_scenario4_mixed_input(self, handler):
        """
        Scenario 4: Agent is speaking.
        User says "Yeah okay but wait."
        Expected: Agent stops (because "wait" is an interrupt command).
        """
        result = handler.classify("Yeah okay but wait", agent_is_speaking=True)
        assert result.decision == InterruptionDecision.INTERRUPT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
