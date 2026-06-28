# Gouvernance des Décisions — v1.3 (résumé kernel)

## Signal de Gouvernance

Le **Signal de Gouvernance** est déclenché automatiquement quand une règle de gouvernance est violée. Il suspend l'action en cours et requiert une résolution explicite.

### Déclencheurs obligatoires

| Code | Condition | Action |
|------|-----------|--------|
| SG-001 | Décision D1 sans Evidence validée | Suspendre, escalader CEO |
| SG-002 | Work Package EXECUTING sans owner | Bloquer, notifier Chief Architect |
| SG-003 | ACP sans section PROPOSAL | Rejeter, retourner à l'émetteur |
| SG-004 | Exception Report D1 non traitée sous 24h | Escalader CEO en urgence |
| SG-005 | Décision D2 prise sans ACP associé | Invalider la décision |

### Procédure Signal de Gouvernance

1. **Identifier** la règle violée (R-GOV-XX)
2. **Suspendre** l'objet concerné (WP, décision, ACP)
3. **Créer** une `exception_report` avec `severity: D1` ou `D2`
4. **Notifier** le CEO via `pending_ceo` si sévérité D1
5. **Attendre** résolution explicite avant de reprendre

## Evidence

Une **Evidence** est un document factuel validé qui fonde une décision.

- Toute décision D1 doit référencer au moins une Evidence de statut `VALIDATED`
- Une Evidence non versionnée est invalide
- La checksum garantit l'intégrité de l'Evidence

### États d'une Evidence

`DRAFT` → `UNDER_REVIEW` → `VALIDATED` | `REJECTED`

## Niveaux de sévérité des déviations

| Sévérité | Description | Délai résolution |
|----------|-------------|-----------------|
| D1 | Critique — bloque le projet | Immédiat (CEO) |
| D2 | Majeur — bloque le WP | 4h (Chief Architect) |
| D3 | Mineur — note pour amélioration | 48h (Agent opérationnel) |
