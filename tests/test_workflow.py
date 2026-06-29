from core.workflow_engine import WorkflowEngine, PROJECT_TRANSITIONS, WP_TRANSITIONS

def make_engine():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    return engine

def test_valid_project_transition():
    engine = make_engine()
    assert engine.can_transition("IMPLEMENTING", "VALIDATING", PROJECT_TRANSITIONS) is True

def test_invalid_project_transition():
    engine = make_engine()
    assert engine.can_transition("IMPLEMENTING", "CLOSED", PROJECT_TRANSITIONS) is False

def test_any_transitions():
    engine = make_engine()
    assert engine.can_transition("IMPLEMENTING", "SUSPENDED", PROJECT_TRANSITIONS) is True
    assert engine.can_transition("IMPLEMENTING", "PENDING_CEO", PROJECT_TRANSITIONS) is True

def test_wp_transition_done():
    engine = make_engine()
    assert engine.can_transition("REVIEW", "DONE", WP_TRANSITIONS) is True

def test_wp_invalid_transition():
    engine = make_engine()
    assert engine.can_transition("PROPOSED", "DONE", WP_TRANSITIONS) is False
