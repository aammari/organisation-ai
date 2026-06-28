from core.workflow_engine import WorkflowEngine, PROJECT_TRANSITIONS

def make_engine():
    return WorkflowEngine.__new__(WorkflowEngine)

def test_deviation_detected_on_invalid_transition():
    engine = make_engine()
    result = engine.can_transition("CLOSED", "IMPLEMENTING", PROJECT_TRANSITIONS)
    assert result is False

def test_no_deviation_on_valid_transition():
    engine = make_engine()
    result = engine.can_transition("DECIDING", "ARCHITECTING", PROJECT_TRANSITIONS)
    assert result is True

def test_suspended_always_allowed():
    engine = make_engine()
    for state in ["INITIATED", "QUALIFYING", "STUDYING", "DECIDING", "ARCHITECTING", "IMPLEMENTING"]:
        assert engine.can_transition(state, "SUSPENDED", PROJECT_TRANSITIONS) is True
