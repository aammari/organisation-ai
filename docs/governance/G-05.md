# G-05 — Politique de Sécurité (Security Policy)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit les règles de sécurité applicables à l'infrastructure, au code et aux données de l'Organisation AI.

---

## Périmètre

- API backend FastAPI (`organisation-ai.onrender.com`)
- Bot Telegram (`organisation-ai-telegram.onrender.com`)
- Supabase (PostgreSQL + Auth)
- GitHub repository `aammari/organisation-ai`
- Variables d'environnement Render

---

## Règles de sécurité

**G-05-R01** : Seul le CEO (chat_id `8190041183`) peut envoyer des commandes au bot Telegram. Tout autre émetteur est ignoré silencieusement.

**G-05-R02** : L'endpoint `POST /backlog/add` est protégé par header `X-Role: chief-of-staff`. Toute requête sans ce header reçoit HTTP 403.

**G-05-R03** : Aucune donnée confidentielle n'est loggée (secrets, contenus CEO, clés). Les logs contiennent uniquement les métadonnées.

**G-05-R04** : L'injection de prompt est une déviation D1. Tout input CEO est transmis sans modification aux agents — aucune interpolation shell ou SQL n'est tolérée.

**G-05-R05** : Les requêtes Supabase utilisent exclusivement la `SERVICE_ROLE_KEY` côté backend. Aucune `anon_key` n'est utilisée en production.

**G-05-R06** : Le dépôt GitHub est en accès public (lecture seule). Les secrets de déploiement ne sont jamais dans le repo.

**G-05-R07** : Toute tentative d'accès non autorisé détectée est tracée dans `audit_log` avec `severity: D1` et notifiée au CEO.

---

## Incidents de sécurité

| Sévérité | Délai de réponse | Action |
|---|---|---|
| Critique (secret exposé) | Immédiat | Rotation complète + notification CEO |
| Majeur (accès non autorisé) | 1h | Audit log + rapport CEO |
| Mineur (tentative bloquée) | 24h | Log uniquement |

---

## Références

- Config Management G-04
- Constitution v1.5 — R-GOV-01
- Decision Governance v1.3 — SG-001
