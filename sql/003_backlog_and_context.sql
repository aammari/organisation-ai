-- Migration 003 — backlog_items + org_context

CREATE TABLE IF NOT EXISTS backlog_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT DEFAULT 'P2',
    status TEXT DEFAULT 'PENDING',
    decision_level TEXT DEFAULT 'D1',
    assigned_agent TEXT,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS org_context (
    id TEXT PRIMARY KEY,
    version TEXT,
    project JSONB,
    backlog JSONB,
    decisions JSONB,
    agents JSONB,
    last_updated TEXT
);

INSERT INTO backlog_items VALUES
('BT-20','A-12 Organizational Sync Service',
'Créer core/context_sync.py. Classe OrgContextSync lit Supabase et GitHub puis formate le contexte. Injecter dans call_architect() via get_formatted(). Endpoints /context et /context/refresh dans main.py. Refresh auto dans supervisor toutes les 5 min.',
'P0','PENDING','D1','chief-architect-001',NULL,NOW(),NOW()),
('BT-21','Backlog Worker autonome',
'Créer core/backlog_worker.py. Lit backlog_items Supabase toutes les 5 min. Prend item PENDING P0. Lance /cycle. Marque DONE. Notifie CEO Telegram uniquement si D3 ou blocage. Déployer comme Background Worker sur Render.',
'P0','PENDING','D1','chief-architect-001',NULL,NOW(),NOW()),
('BT-23','Enregistrer décision Groq Chief Analyst',
'INSERT INTO decisions VALUES (generate_identifier(''DEC''), ''Groq remplace ChatGPT comme Chief Analyst'', ''D3'', ''APPROVED'', ''CEO'', ''Effectif 29 juin 2026'', NOW(), NOW())',
'P0','PENDING','D1','chief-architect-001',NULL,NOW(),NOW())
ON CONFLICT DO NOTHING;
