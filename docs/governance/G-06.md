# G-06 — Cycle de Vie des Capabilities (Capability Lifecycle)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D2

---

## Objet

Définit le cycle de vie des capabilities d'agents — de leur création à leur retrait — et les règles de binding entre agents et capabilities.

---

## Capabilities actives (MVP)

| ID | Nom | Agent assigné | Modèle |
|---|---|---|---|
| CAP-001 | Architecture & Delivery | chief-architect-001 | claude-sonnet-4-6 |
| CAP-002 | Governance & Analysis | chief-analyst-001 | claude-haiku-4-5-20251001 |

---

## Cycle de vie d'une capability

```
PROPOSED (Chief Architect ACP)
   ↓ CEO APPROVED
ACTIVE (binding créé)
   ↓ Décision D2 ou révision technique
SUSPENDED (agent suspendu temporairement)
   ↓ CEO APPROVED
RETIRED (capability non utilisable)
```

---

## Règles

**G-06-R01** : Une capability ne peut être assignée qu'à un seul agent actif à la fois.

**G-06-R02** : Le changement de modèle LLM d'une capability est une décision D2 (Chief Architect ACP requis).

**G-06-R03** : La création d'une nouvelle capability est une décision D1 (CEO). Elle implique nécessairement la création ou modification d'un agent (G-03).

**G-06-R04** : Une capability SUSPENDED bloque tous les Work Packages de l'agent concerné. Ils passent en `status: BLOCKED`.

**G-06-R05** : Le performance review d'une capability (qualité des livrables, taux de validation) est effectué à chaque OrgHealthReview G-10.

**G-06-R06** : Le changement de provider LLM (ex: Groq → Anthropic) est tracé dans `decisions` avec justification et Evidence.

---

## Métriques de capability

| Métrique | Cible MVP | Seuil d'alerte |
|---|---|---|
| Taux validation analyst | ≥ 70% | < 50% → révision capability |
| Temps de réponse moyen | < 30s | > 60s → investigation |
| Disponibilité | ≥ 95% | < 90% → incident D2 |

---

## Références

- Agent Model v1.2 — AGT-01 à AGT-05
- OrgHealthReview G-10
- Constitution v1.5 — R-GOV-01
