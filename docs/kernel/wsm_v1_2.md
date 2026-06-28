# Workflow State Machine — v1.2 (résumé kernel)

## États des Projets (PROJECT_TRANSITIONS)

```
INITIATING → DECIDING → IMPLEMENTING → OPERATING → CLOSING
                ↓
            SUSPENDED (depuis tout état sauf CLOSING)
                ↓
            DECIDING (reprise après suspension)
```

| État | Description |
|------|-------------|
| INITIATING | Projet en phase de définition |
| DECIDING | En attente de décision GO/NO-GO du CEO |
| IMPLEMENTING | En cours de construction/déploiement |
| OPERATING | En production, mode opérationnel |
| CLOSING | Clôture formelle en cours |
| SUSPENDED | Bloqué — Signal de Gouvernance ou décision CEO |

### Transitions autorisées

| De | Vers | Condition |
|----|------|-----------|
| INITIATING | DECIDING | ACP initial produit |
| DECIDING | IMPLEMENTING | GO CEO avec Evidence |
| DECIDING | SUSPENDED | NO-GO CEO ou SG déclenché |
| IMPLEMENTING | OPERATING | Déploiement validé |
| OPERATING | CLOSING | Décision CEO |
| * | SUSPENDED | Signal de Gouvernance D1 |

## États des Work Packages (WP_TRANSITIONS)

```
PROPOSED → BACKLOG → READY → EXECUTING → DONE
                                  ↓
                              BLOCKED (résolvable)
                                  ↓
                              READY (après résolution)
```

| État | Description |
|------|-------------|
| PROPOSED | WP identifié, non encore planifié |
| BACKLOG | En attente d'assignation |
| READY | Agent assigné, prêt à démarrer |
| EXECUTING | En cours d'exécution |
| BLOCKED | Bloqué sur dépendance ou déviation |
| DONE | Livrable produit et validé |

### Règles WSM

- **WSM-01** : Transition PROPOSED → BACKLOG requiert un er_id valide.
- **WSM-02** : Transition BACKLOG → READY requiert owner_agent_id assigné.
- **WSM-03** : Transition READY → EXECUTING démarre le timer de délai.
- **WSM-04** : Transition EXECUTING → DONE requiert analyst_decision = VALIDATED.
- **WSM-05** : Un WP BLOCKED ne peut pas passer DONE sans résolution de blocage explicite.
