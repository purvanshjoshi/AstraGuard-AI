"""Integration test for @log_feedback with policy engine recovery functions."""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from security_engine.decorators import log_feedback, ThreadSafeFeedbackStore
from models.feedback import FeedbackEvent


class TestFeedbackLoggingIntegration:
    """Integration tests simulating real recovery action logging."""

    def test_simulated_recovery_action_logging(self):
        """Simulates wrapping a real recovery function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ThreadSafeFeedbackStore(Path(tmpdir) / "feedback_pending.json")
            with patch("security_engine.decorators._pending_store", store):

                # Simulate a recovery function that might exist in policy_engine
                @log_feedback(
                    fault_id="power_loss_001",
                    anomaly_type="power_subsystem",
                )
                def emergency_power_cycle(system_state):
                    """Simulated recovery action."""
                    return True

                # Simulate system state object
                mock_system = MagicMock()
                mock_system.mission_phase = "NOMINAL_OPS"

                result = emergency_power_cycle(mock_system)
                assert result is True

                # Verify feedback was logged
                pending = json.loads(
                    (Path(tmpdir) / "feedback_pending.json").read_text()
                )
                assert len(pending) == 1
                assert pending[0]["fault_id"] == "power_loss_001"
                assert pending[0]["anomaly_type"] == "power_subsystem"
                assert pending[0]["recovery_action"] == "emergency_power_cycle"

    def test_multiple_recovery_actions_sequence(self):
        """Tests a sequence of recovery actions being logged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ThreadSafeFeedbackStore(Path(tmpdir) / "feedback_pending.json")
            with patch("security_engine.decorators._pending_store", store):

                @log_feedback("thermal_001", "thermal_subsystem")
                def thermal_control_init(state):
                    return True

                @log_feedback("thermal_002", "thermal_subsystem")
                def activate_passive_cooling(state):
                    return True

                @log_feedback("thermal_003", "thermal_subsystem")
                def thermal_emergency_shutdown(state):
                    return True

                mock_state = MagicMock()
                mock_state.mission_phase = "PAYLOAD_OPS"

                # Execute recovery sequence
                thermal_control_init(mock_state)
                activate_passive_cooling(mock_state)
                thermal_emergency_shutdown(mock_state)

                pending = json.loads(
                    (Path(tmpdir) / "feedback_pending.json").read_text()
                )
                assert len(pending) == 3
                assert pending[0]["fault_id"] == "thermal_001"
                assert pending[1]["fault_id"] == "thermal_002"
                assert pending[2]["fault_id"] == "thermal_003"

    def test_mission_phase_propagation(self):
        """Tests that mission_phase is extracted from system state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ThreadSafeFeedbackStore(Path(tmpdir) / "feedback_pending.json")
            with patch("security_engine.decorators._pending_store", store):

                @log_feedback("f1", "test")
                def recovery_action(system_state):
                    return True

                # Test with different mission phases
                for phase in ["LAUNCH", "DEPLOYMENT", "NOMINAL_OPS", "PAYLOAD_OPS", "SAFE_MODE"]:
                    mock_state = MagicMock()
                    mock_state.mission_phase = phase
                    recovery_action(mock_state)

                pending = json.loads(
                    (Path(tmpdir) / "feedback_pending.json").read_text()
                )
                assert len(pending) == 5
                phases = [e["mission_phase"] for e in pending]
                assert phases == ["LAUNCH", "DEPLOYMENT", "NOMINAL_OPS", "PAYLOAD_OPS", "SAFE_MODE"]

    def test_recovery_failure_logged_with_reduced_confidence(self):
        """Failed recovery action logged with reduced confidence score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ThreadSafeFeedbackStore(Path(tmpdir) / "feedback_pending.json")
            with patch("security_engine.decorators._pending_store", store):

                @log_feedback("f1", "test")
                def failed_recovery(state):
                    return False  # Indicates failure

                mock_state = MagicMock()
                recovery_result = failed_recovery(mock_state)
                assert recovery_result is False

                pending = json.loads(
                    (Path(tmpdir) / "feedback_pending.json").read_text()
                )
                assert pending[0]["confidence_score"] == 0.5

    def test_pending_store_can_be_consumed_by_cli(self):
        """Verify pending store format is JSON-readable for CLI consumption."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ThreadSafeFeedbackStore(Path(tmpdir) / "feedback_pending.json")
            with patch("security_engine.decorators._pending_store", store):

                @log_feedback("f1", "test")
                def recovery(state):
                    return True

                mock_state = MagicMock()
                recovery(mock_state)

                # Simulate CLI reading and parsing
                with open(Path(tmpdir) / "feedback_pending.json") as f:
                    events = json.load(f)

                # Verify structure is valid FeedbackEvent
                assert isinstance(events, list)
                event = events[0]
                assert "fault_id" in event
                assert "anomaly_type" in event
                assert "recovery_action" in event
                assert "mission_phase" in event
                assert "confidence_score" in event
                assert "timestamp" in event
