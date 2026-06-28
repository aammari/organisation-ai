# Architecture

## Vue d'ensemble

```
CEO Request → FastAPI /cycle → LangGraph workflow
                                    ├── qualify_intent
                                    ├── call_architect (Claude)
                                    ├── validate_output (GPT-4o)
                                    └── produce_response
```

## Composants

| Module | Rôle |
|---|---|
| `core/langgraph_app.py` | Orchestration LangGraph |
| `core/workflow_engine.py` | Workflow State Machine |
| `core/identifiers.py` | Génération EVID/DEC/WP/... |
| `app/database.py` | Client Supabase |
