"""
Test for Mission Phase Transition Race Condition Fix.

Verifies that concurrent phase transitions are properly serialized
and do not leave the system in an inconsistent state.
"""
import pytest
import threading
import time
from state_machine.state_engine import StateMachine, MissionPhase
from core.error_handling import StateTransitionError


class TestMissionPhaseRaceCondition:
    """Test suite for mission phase race condition fix."""

    def test_sequential_transitions(self):
        """Test that sequential transitions work correctly."""
        state_machine = StateMachine()
        
        # Start in NOMINAL_OPS
        assert state_machine.get_current_phase() == MissionPhase.NOMINAL_OPS
        
        # Transition to SAFE_MODE
        result = state_machine.set_phase(MissionPhase.SAFE_MODE)
        assert result['success'] is True
        assert result['new_phase'] == 'SAFE_MODE'
        assert state_machine.get_current_phase() == MissionPhase.SAFE_MODE

    def test_concurrent_transitions_blocked(self):
        """Test that concurrent transitions are properly blocked."""
        state_machine = StateMachine()
        results = []
        errors = []
        
        def slow_transition():
            """Simulate a slow transition."""
            try:
                # This will hold the lock
                state_machine._is_transitioning = True
                time.sleep(0.1)  # Simulate long transition
                state_machine._is_transitioning = False
                results.append("completed")
            except Exception as e:
                errors.append(e)
        
        def concurrent_transition():
            """Try to transition while another is in progress."""
            try:
                time.sleep(0.05)  # Wait a bit to ensure first transition started
                result = state_machine.set_phase(MissionPhase.SAFE_MODE)
                results.append(result)
            except StateTransitionError as e:
                errors.append(e)
        
        # Start first transition
        t1 = threading.Thread(target=slow_transition)
        t2 = threading.Thread(target=concurrent_transition)
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        # Should have one error from blocked transition
        assert len(errors) == 1
        assert "transition already in progress" in str(errors[0]).lower()

    def test_multiple_rapid_transitions(self):
        """Test multiple rapid transitions are serialized correctly."""
        state_machine = StateMachine()
        results = []
        errors = []
        
        def attempt_transition(target_phase):
            """Attempt a phase transition."""
            try:
                result = state_machine.set_phase(target_phase)
                results.append({
                    'success': result['success'],
                    'phase': result['new_phase']
                })
            except StateTransitionError as e:
                errors.append(str(e))
        
        # Create multiple threads trying to transition
        threads = []
        phases = [
            MissionPhase.SAFE_MODE,
            MissionPhase.NOMINAL_OPS,
            MissionPhase.PAYLOAD_OPS,
        ]
        
        for phase in phases:
            t = threading.Thread(target=attempt_transition, args=(phase,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # At least one should succeed, others may be blocked
        successful_results = [r for r in results if r['success']]
        assert len(successful_results) >= 1
        
        # Final phase should be one of the attempted phases
        final_phase = state_machine.get_current_phase()
        assert final_phase in phases or final_phase == MissionPhase.NOMINAL_OPS

    def test_force_safe_mode_interrupts_transition(self):
        """Test that force_safe_mode can interrupt ongoing transitions."""
        state_machine = StateMachine()
        results = []
        
        def slow_transition():
            """Simulate a slow transition."""
            try:
                state_machine._is_transitioning = True
                time.sleep(0.15)
                state_machine._is_transitioning = False
                results.append("normal_completed")
            except Exception:
                results.append("normal_failed")
        
        def force_safe():
            """Force safe mode during transition."""
            time.sleep(0.05)
            result = state_machine.force_safe_mode()
            results.append(result)
        
        t1 = threading.Thread(target=slow_transition)
        t2 = threading.Thread(target=force_safe)
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        # Force safe mode should succeed
        safe_mode_results = [r for r in results if isinstance(r, dict) and r.get('forced')]
        assert len(safe_mode_results) == 1
        assert state_machine.get_current_phase() == MissionPhase.SAFE_MODE

    def test_transition_cleanup_on_error(self):
        """Test that transition flag is always reset even on error."""
        state_machine = StateMachine()
        
        # Try invalid transition
        try:
            state_machine.set_phase("INVALID_PHASE")
        except (StateTransitionError, ValueError):
            pass
        
        # Transition flag should be reset
        assert state_machine._is_transitioning is False
        
        # Should be able to make valid transition now
        result = state_machine.set_phase(MissionPhase.SAFE_MODE)
        assert result['success'] is True

    def test_no_inconsistent_state_during_transition(self):
        """Test that state remains consistent even with rapid queries."""
        state_machine = StateMachine()
        phases_observed = []
        
        def transition_phase():
            """Perform a transition."""
            try:
                state_machine.set_phase(MissionPhase.SAFE_MODE)
                time.sleep(0.05)
                state_machine.set_phase(MissionPhase.NOMINAL_OPS)
            except StateTransitionError:
                pass
        
        def observe_phase():
            """Observe current phase repeatedly."""
            for _ in range(20):
                phase = state_machine.get_current_phase()
                phases_observed.append(phase)
                time.sleep(0.01)
        
        t1 = threading.Thread(target=transition_phase)
        t2 = threading.Thread(target=observe_phase)
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        # All observed phases should be valid MissionPhase enum values
        assert all(isinstance(p, MissionPhase) for p in phases_observed)
        assert len(phases_observed) == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
