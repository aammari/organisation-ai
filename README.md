# Organisation AI MVP

Système multi-agents autonome pour la gestion organisationnelle.

## Stack

- **Backend** : FastAPI + Python
- **Orchestration** : LangGraph minimal
- **State Store** : Supabase PostgreSQL
- **Cache** : Upstash Redis
- **LLM Chief Architect** : Claude (Anthropic)
- **LLM Chief Analyst** : GPT-4o (OpenAI)
- **Interface CEO** : Custom GPT
- **Documentation** : MkDocs Material

## Installation

```bash
git clone https://github.com/aammari/organisation-ai
cd organisation-ai
pip install -r requirements.txt
cp .env.example .env
# Remplir .env avec tes clés
uvicorn main:app --reload
```

## Premier cycle autonome

```bash
curl -X POST http://localhost:8000/cycle \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyse nos trois documents fondateurs les plus importants"}'
```

## Documentation

```bash
pip install mkdocs-material
mkdocs serve
```

## Gouvernance

Ce projet suit les principes de l'Organisation AI :
- Workflow State Machine v1.3
- Evidence Model (EVID-XXXX)
- Decision Governance v1.3
- Constitution v1.5
