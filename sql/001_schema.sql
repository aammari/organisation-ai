-- Identifier counters
CREATE TABLE IF NOT EXISTS identifier_counters (
    prefix TEXT PRIMARY KEY,
    current_value INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION generate_identifier(p_prefix TEXT)
RETURNS TEXT AS $$
DECLARE next_value INTEGER;
BEGIN
    INSERT INTO identifier_counters(prefix, current_value)
    VALUES (p_prefix, 0) ON CONFLICT (prefix) DO NOTHING;
    UPDATE identifier_counters
    SET current_value = current_value + 1, updated_at = now()
    WHERE prefix = p_prefix
    RETURNING current_value INTO next_value;
    RETURN p_prefix || '-' || LPAD(next_value::TEXT, 4, '0');
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS executive_requests (
    id TEXT PRIMARY KEY,
    raw_input TEXT NOT NULL,
    qualified_intent TEXT,
    type TEXT,
    priority TEXT DEFAULT 'P2',
    status TEXT DEFAULT 'RECEIVED',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS work_packages (
    id TEXT PRIMARY KEY,
    er_id TEXT REFERENCES executive_requests(id),
    title TEXT NOT NULL,
    status TEXT DEFAULT 'PROPOSED',
    owner_agent_id TEXT,
    context_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS acp_messages (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    sender_agent_id TEXT NOT NULL,
    recipient_agent_id TEXT,
    wp_id TEXT REFERENCES work_packages(id),
    content JSONB NOT NULL,
    status TEXT DEFAULT 'EMITTED',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pending_ceo (
    id TEXT PRIMARY KEY,
    wp_id TEXT REFERENCES work_packages(id),
    subject TEXT NOT NULL,
    options JSONB,
    recommendation TEXT,
    priority TEXT DEFAULT 'P1',
    status TEXT DEFAULT 'PENDING',
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    answered_at TIMESTAMPTZ,
    answer TEXT
);

CREATE TABLE IF NOT EXISTS capabilities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    function_parent TEXT NOT NULL,
    status TEXT DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    llm_provider TEXT NOT NULL,
    llm_model TEXT,
    system_prompt TEXT,
    status TEXT DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS capability_bindings (
    id TEXT PRIMARY KEY,
    capability_id TEXT REFERENCES capabilities(id),
    agent_id TEXT REFERENCES agents(id),
    status TEXT DEFAULT 'ACTIVE',
    decision_id TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS project_states (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    current_state TEXT NOT NULL,
    previous_state TEXT,
    transition_reason TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    source TEXT,
    author TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    checksum TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS evidence_versions (
    evidence_id TEXT NOT NULL REFERENCES evidence(id),
    version INTEGER NOT NULL,
    content JSONB NOT NULL,
    checksum TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (evidence_id, version)
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    decision_level TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT NOT NULL,
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS exception_reports (
    id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT,
    workflow TEXT,
    state TEXT,
    violated_rules JSONB NOT NULL,
    affected_objects JSONB NOT NULL,
    context JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT NOT NULL,
    operation TEXT NOT NULL,
    object_id TEXT NOT NULL,
    previous_value JSONB,
    new_value JSONB,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL,
    actor TEXT NOT NULL,
    severity TEXT NOT NULL,
    related_objects JSONB NOT NULL DEFAULT '[]',
    payload JSONB NOT NULL DEFAULT '{}',
    requires_action BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'PUBLISHED',
    consumed_at TIMESTAMPTZ
);

-- Initial data
INSERT INTO capabilities VALUES
('chief-architect-capability', 'Chief Architect Capability', 'Architecture & Delivery', 'ACTIVE', NOW()),
('chief-analyst-capability', 'Chief Analyst Capability', 'Governance & Analysis', 'ACTIVE', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO agents VALUES
('chief-architect-001', 'Agent Chief Architect', 'chief-architect-capability', 'anthropic', 'claude-sonnet-4-6', NULL, 'ACTIVE', NOW()),
('chief-analyst-001', 'Agent Chief Analyst', 'chief-analyst-capability', 'openai', 'gpt-4o', NULL, 'ACTIVE', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO project_states VALUES
('org-mvp-001', 'Organisation AI MVP', 'IMPLEMENTING', 'DECIDING', 'GO CONDITIONNEL CEO — Juin 2026', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO identifier_counters VALUES
('EVID', 0, NOW(), NOW()), ('DEC', 0, NOW(), NOW()),
('WP', 0, NOW(), NOW()), ('ER', 0, NOW(), NOW()),
('EVT', 0, NOW(), NOW())
ON CONFLICT DO NOTHING;
