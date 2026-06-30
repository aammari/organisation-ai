# G-04 — Gestion de la Configuration (Config Management)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D2

---

## Objet

Définit les règles de gestion des variables d'environnement, des secrets, et des paramètres de déploiement de l'infrastructure Organisation AI.

---

## Registre des configurations

| Variable | Service | Sensibilité | Stockage |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | backend, telegram | SECRET | Render env vars |
| `SUPABASE_URL` | backend, worker | STANDARD | Render env vars |
| `SUPABASE_SERVICE_ROLE_KEY` | backend, worker | SECRET | Render env vars |
| `TELEGRAM_BOT_TOKEN` | telegram, backend | SECRET | Render env vars |
| `TELEGRAM_CHAT_ID` | backend, telegram | STANDARD | Render env vars |
| `BACKEND_URL` | telegram, supervisor | STANDARD | Render env vars |
| `GITHUB_TOKEN` | backend | SECRET | Render env vars |

---

## Règles

**G-04-R01** : Aucun secret ne doit apparaître dans le code source, les logs, les commits ou les pull requests. Violation → Signal de Gouvernance immédiat.

**G-04-R02** : Tout changement de valeur d'une variable SECRET est une décision D2 (Chief Architect) avec notification CEO.

**G-04-R03** : La rotation des clés API se fait tous les 90 jours ou immédiatement en cas de suspicion de compromission.

**G-04-R04** : Les variables d'environnement sont synchronisées entre tous les services Render via le dashboard Render uniquement (pas via API publique).

**G-04-R05** : Un fichier `.env.example` sans valeurs réelles est maintenu dans le dépôt pour documentation.

**G-04-R06** : Le fichier `.env` est explicitement dans `.gitignore`. Son commit accidentel déclenche une rotation immédiate de tous les secrets exposés.

---

## Procédure de rotation d'urgence

1. Révoquer l'ancienne clé sur le provider (Anthropic, Supabase, Telegram)
2. Générer nouvelle clé
3. Mettre à jour Render env vars sur tous les services impactés
4. Redéployer les services
5. Vérifier `/health` sur les 4 services
6. Notifier CEO — décision tracée dans `decisions`

---

## Références

- Constitution v1.5 — R-GOV-02 (traçabilité)
- Security Policy G-05
- Agent Model v1.2 — AGT-04
