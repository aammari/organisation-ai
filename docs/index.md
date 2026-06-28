# Organisation AI

Bienvenue dans la documentation officielle de l'Organisation AI.

## Architecture Rapide

| Couche | Composants |
|---|---|
| Kernel | WSM, Decision Governance, Constitution |
| Runtime | LangGraph, Supabase, Redis |
| Execution | FastAPI, LangGraph nodes |
| Interface | Custom GPT, CEO Dashboard |

## Démarrage Rapide

1. Cloner le dépôt
2. Copier `.env.example` → `.env`
3. Remplir les variables d'environnement
4. `pip install -r requirements.txt`
5. `uvicorn main:app --reload`

## Lien Architecture

Voir [Organizational Reference Architecture](architecture/index.md)
