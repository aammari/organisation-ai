# Workflow Opérationnel — v1.1 (résumé kernel)

## Cycle de vie d'une demande CEO

```
CEO input
   ↓
[ER] Executive Request créée (status: RECEIVED)
   ↓
qualify_intent() → intent: ANALYSE | PRODUCTION | ACTION | DECISION
   ↓
[WP] Work Package créé (status: PROPOSED)
   ↓
Chief Architect assigné (status: BACKLOG → READY)
   ↓
call_architect() → ACP produit (status: EXECUTING)
   ↓
validate_output() → Chief Analyst valide/rejette
   ↓
Si VALIDATED → produce_response() → réponse CEO
Si REJECTED  → retour Chief Architect (max 2 itérations)
```

## Intents qualifiés

| Intent | Mots-clés | Description |
|--------|-----------|-------------|
| ANALYSE | analyse, évalue, examine, étudie | Demande d'analyse ou rapport |
| PRODUCTION | produis, génère, crée, rédige | Demande de livrable |
| ACTION | lance, exécute, déploie, active | Demande d'action concrète |
| DECISION | décide, valide, approuve, GO | Demande de décision D1 |

## Priorités

| Priorité | Délai cible | Usage |
|----------|-------------|-------|
| P1 | Immédiat | Urgence, blocage, Signal de Gouvernance |
| P2 | 4h | Standard opérationnel |
| P3 | 48h | Amélioration, optimisation |

## Règles opérationnelles

- **OP-01** : Un WP ne peut avoir qu'un seul owner_agent_id actif à la fois.
- **OP-02** : Maximum 2 itérations REJECTED avant escalade CEO.
- **OP-03** : Toute réponse au CEO doit inclure l'intent qualifié et la décision analyst.
- **OP-04** : Le format de réponse par défaut est ACP.
