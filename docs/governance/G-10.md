# G-10 — Revue de Santé Organisationnelle (Org Health Review)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit la cadence et le contenu des revues périodiques de l'état de santé de l'organisation, permettant au CEO de piloter l'évolution du système.

---

## Cadence

| Type | Fréquence | Déclencheur |
|---|---|---|
| Revue hebdomadaire | Tous les lundis | Automatique (Backlog Worker) |
| Revue de sprint | Fin de chaque sprint (2 semaines) | Manuel — CEO |
| Revue d'urgence | À la demande | Signal de Gouvernance D1 non résolu |

---

## Contenu d'une revue

```
1. Backlog actif
   - WPs PENDING / IN_PROGRESS / BLOCKED
   - Items en attente CEO (pending_ceo)

2. Métriques agents
   - Taux de validation (Chief Analyst)
   - Temps de réponse moyen
   - Erreurs et escalades (7 derniers jours)

3. Décisions en attente
   - Décisions D1 non tranchées
   - Waivers arrivant à expiration

4. Coûts API
   - Tokens consommés (Anthropic Sonnet + Haiku)
   - Projection mensuelle
   - Alertes si dépassement seuil

5. Infrastructure
   - Statut des 4 services Render
   - Derniers déploiements
   - Incidents (cold starts, timeouts)

6. Recommandations
   - Chief Architect : top 3 actions prioritaires
   - Chief Analyst : déviations identifiées
```

---

## Règles

**G-10-R01** : La revue hebdomadaire est produite automatiquement par le Backlog Worker et transmise au CEO sur Telegram.

**G-10-R02** : Toute métrique en-dessous du seuil d'alerte défini en G-06 déclenche un item `priority: P1` en backlog.

**G-10-R03** : Le CEO peut demander une revue à tout moment via le bot Telegram (intent: ANALYSE).

**G-10-R04** : Les résultats de revue sont tracés dans `decisions` avec level D2 (Chief Architect).

**G-10-R05** : Si 3 revues consécutives signalent le même problème non résolu, escalade automatique en décision D1.

---

## Format de rapport

```
# OrgHealthReview — Semaine WW/YYYY
Date : YYYY-MM-DD | Généré par : Backlog Worker

## Backlog
- PENDING : N | IN_PROGRESS : N | BLOCKED : N

## Agents
- Taux validation : X% | Temps moyen : Xs

## Infrastructure
- Tous services : ✅ / ⚠️ / ❌

## Actions requises CEO
1. [item le plus urgent]
```

---

## Références

- Capability Lifecycle G-06 (métriques agents)
- Data Retention G-02 (données de revue)
- Operational Workflow v1.1 — OP-02
