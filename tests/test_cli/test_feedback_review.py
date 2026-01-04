"""100% coverage for feedback CLI review flow."""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

from cli import FeedbackCLI
from models.feedback import FeedbackEvent, FeedbackLabel


class TestLoadPending:
    """Test FeedbackCLI.load_pending() functionality."""

    def test_load_pending_file_not_exists(self, tmp_path):
        """Missing file returns empty list."""
        with patch("pathlib.Path.exists", return_value=False):
            events = FeedbackCLI.load_pending()
            assert events == []

    def test_load_pending_single_event(self, tmp_path, monkeypatch):
        """Load valid single pending event."""
        monkeypatch.chdir(tmp_path)
        event_data = {
            "fault_id": "test1",
            "anomaly_type": "power",
            "recovery_action": "cycle_power",
            "mission_phase": "NOMINAL_OPS",
            "label": "correct",
        }
        Path("feedback_pending.json").write_text(json.dumps([event_data]))

        events = FeedbackCLI.load_pending()
        assert len(events) == 1
        assert events[0].fault_id == "test1"
        assert events[0].anomaly_type == "power"

    def test_load_pending_multiple_events(self, tmp_path, monkeypatch):
        """Load multiple pending events."""
        monkeypatch.chdir(tmp_path)
        events_data = [
            {
                "fault_id": f"fault_{i}",
                "anomaly_type": "test",
                "recovery_action": "test_action",
                "mission_phase": "NOMINAL_OPS",
                "label": "correct",
            }
            for i in range(3)
        ]
        Path("feedback_pending.json").write_text(json.dumps(events_data))

        events = FeedbackCLI.load_pending()
        assert len(events) == 3
        assert all(isinstance(e, FeedbackEvent) for e in events)

    def test_load_pending_invalid_json(self, tmp_path, monkeypatch, capsys):
        """Corrupt JSON auto-clears the file."""
        monkeypatch.chdir(tmp_path)
        Path("feedback_pending.json").write_text("invalid json {")

        events = FeedbackCLI.load_pending()
        assert events == []
        assert not Path("feedback_pending.json").exists()
        captured = capsys.readouterr()
        assert "⚠️" in captured.out

    def test_load_pending_not_list(self, tmp_path, monkeypatch):
        """Non-list JSON returns empty list."""
        monkeypatch.chdir(tmp_path)
        Path("feedback_pending.json").write_text(json.dumps({"not": "list"}))

        events = FeedbackCLI.load_pending()
        assert events == []


class TestSaveProcessed:
    """Test FeedbackCLI.save_processed() functionality."""

    def test_save_processed_creates_file(self, tmp_path, monkeypatch):
        """Processed events saved to feedback_processed.json."""
        monkeypatch.chdir(tmp_path)
        event_dict = {
            "fault_id": "test1",
            "anomaly_type": "power",
            "recovery_action": "cycle",
            "mission_phase": "NOMINAL_OPS",
            "label": "correct",
            "timestamp": "2026-01-04T14:00:00",
            "confidence_score": 1.0,
            "operator_notes": "Good",
        }

        FeedbackCLI.save_processed([event_dict])

        processed_file = Path("feedback_processed.json")
        assert processed_file.exists()
        data = json.loads(processed_file.read_text())
        assert len(data) == 1
        assert data[0]["fault_id"] == "test1"

    def test_save_processed_multiple_events(self, tmp_path, monkeypatch):
        """Save multiple processed events."""
        monkeypatch.chdir(tmp_path)
        events = [
            {
                "fault_id": f"fault_{i}",
                "anomaly_type": "test",
                "recovery_action": "test",
                "mission_phase": "NOMINAL_OPS",
                "label": "correct",
                "timestamp": "2026-01-04T14:00:00",
                "confidence_score": 1.0,
                "operator_notes": None,
            }
            for i in range(3)
        ]

        FeedbackCLI.save_processed(events)

        data = json.loads(Path("feedback_processed.json").read_text())
        assert len(data) == 3


class TestReviewInteractive:
    """Test FeedbackCLI.review_interactive() flow."""

    def test_no_pending_events(self, tmp_path, monkeypatch, capsys):
        """No pending events prints success message."""
        monkeypatch.chdir(tmp_path)

        with patch.object(FeedbackCLI, "load_pending", return_value=[]):
            FeedbackCLI.review_interactive()
            captured = capsys.readouterr()
            assert "✅ No pending feedback events" in captured.out

    def test_review_single_event_correct_label(self, tmp_path, monkeypatch, capsys):
        """Review single event with correct label."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="test1",
            anomaly_type="power",
            recovery_action="cycle",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.WRONG,  # Start with wrong
        )

        inputs = ["correct", ""]  # Label, then skip notes
        with patch("builtins.input", side_effect=inputs):
            with patch.object(FeedbackCLI, "load_pending", return_value=[event]):
                FeedbackCLI.review_interactive()

        # Check processed file was created
        processed = json.loads(Path("feedback_processed.json").read_text())
        assert processed[0]["label"] == "correct"
        assert processed[0]["operator_notes"] is None

    def test_review_with_operator_notes(self, tmp_path, monkeypatch):
        """Review event with operator notes."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="test1",
            anomaly_type="power",
            recovery_action="cycle",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.CORRECT,
        )

        inputs = ["correct", "Fixed in 2.3 seconds"]
        with patch("builtins.input", side_effect=inputs):
            with patch.object(FeedbackCLI, "load_pending", return_value=[event]):
                FeedbackCLI.review_interactive()

        processed = json.loads(Path("feedback_processed.json").read_text())
        assert processed[0]["operator_notes"] == "Fixed in 2.3 seconds"

    def test_review_invalid_label_retry(self, tmp_path, monkeypatch, capsys):
        """Invalid label prompts retry."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="test1",
            anomaly_type="test",
            recovery_action="test",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.CORRECT,
        )

        inputs = ["invalid", "correct", ""]
        with patch("builtins.input", side_effect=inputs):
            with patch.object(FeedbackCLI, "load_pending", return_value=[event]):
                FeedbackCLI.review_interactive()

        captured = capsys.readouterr()
        assert "❌ Invalid" in captured.out

    def test_review_quit_early(self, tmp_path, monkeypatch):
        """Quit (q) exits immediately."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="test1",
            anomaly_type="test",
            recovery_action="test",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.CORRECT,
        )

        with patch("builtins.input", return_value="q"):
            with patch.object(FeedbackCLI, "load_pending", return_value=[event]):
                with pytest.raises(SystemExit):
                    FeedbackCLI.review_interactive()

    def test_review_multiple_events_sequence(self, tmp_path, monkeypatch):
        """Review multiple events in sequence."""
        monkeypatch.chdir(tmp_path)
        events = [
            FeedbackEvent(
                fault_id=f"test{i}",
                anomaly_type="test",
                recovery_action="test",
                mission_phase="NOMINAL_OPS",
                label=FeedbackLabel.CORRECT,
            )
            for i in range(2)
        ]

        # Labels for 2 events + notes
        inputs = ["correct", "", "insufficient", ""]
        with patch("builtins.input", side_effect=inputs):
            with patch.object(FeedbackCLI, "load_pending", return_value=events):
                FeedbackCLI.review_interactive()

        processed = json.loads(Path("feedback_processed.json").read_text())
        assert len(processed) == 2
        assert processed[0]["label"] == "correct"
        assert processed[1]["label"] == "insufficient"

    def test_review_clears_pending_file(self, tmp_path, monkeypatch):
        """Pending file deleted after processing."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="test1",
            anomaly_type="test",
            recovery_action="test",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.CORRECT,
        )
        # Use model_dump_json to properly serialize datetime
        Path("feedback_pending.json").write_text(
            json.dumps([json.loads(event.model_dump_json())])
        )

        inputs = ["correct", ""]
        with patch("builtins.input", side_effect=inputs):
            FeedbackCLI.review_interactive()

        assert not Path("feedback_pending.json").exists()
        assert Path("feedback_processed.json").exists()

    def test_review_prints_event_details(self, tmp_path, monkeypatch, capsys):
        """Review displays all event details."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="power_loss_001",
            anomaly_type="power_subsystem",
            recovery_action="emergency_power_cycle",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.CORRECT,
        )

        inputs = ["correct", ""]
        with patch("builtins.input", side_effect=inputs):
            with patch.object(FeedbackCLI, "load_pending", return_value=[event]):
                FeedbackCLI.review_interactive()

        captured = capsys.readouterr()
        assert "power_loss_001" in captured.out
        assert "power_subsystem" in captured.out
        assert "emergency_power_cycle" in captured.out
        assert "NOMINAL_OPS" in captured.out

    def test_review_prints_success_message(self, tmp_path, monkeypatch, capsys):
        """Review prints final success message."""
        monkeypatch.chdir(tmp_path)
        event = FeedbackEvent(
            fault_id="test1",
            anomaly_type="test",
            recovery_action="test",
            mission_phase="NOMINAL_OPS",
            label=FeedbackLabel.CORRECT,
        )

        inputs = ["correct", ""]
        with patch("builtins.input", side_effect=inputs):
            with patch.object(FeedbackCLI, "load_pending", return_value=[event]):
                FeedbackCLI.review_interactive()

        captured = capsys.readouterr()
        assert "🎉" in captured.out
        assert "ready for #53 pinning" in captured.out
