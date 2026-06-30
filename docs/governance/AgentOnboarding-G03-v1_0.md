# G-03 — Onboarding des Agents (Agent Onboarding)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit la procédure d'activation d'un nouvel agent dans l'organisation, depuis la décision de création jusqu'à la première exécution de Work Package.

---

## Étapes d'onboarding

```
1. Décision D1 CEO (création agent)
   → INSERT INTO agents (id, role, provider, model, status='INACTIVE')

2. Capability Binding
   → INSERT INTO capability_bindings (agent_id, capability, status='PENDING')
   → Validation Chief Architect (décision D2)

3. Activation
   → UPDATE agents SET status='ACTIVE'
   → UPDATE capability_bindings SET status='ACTIVE'
   → Notifier CEO sur Telegram

4. Premier WP test (P3)
   → Exécution supervisée — Chief Analyst valide obligatoirement
   → Si VALIDATED → agent opérationnel
   → Si REJECTED  → suspension + rapport CEO
```

---

## Règles

**G-03-R01** : La création d'un agent est une décision D1 irréversible sans re-approbation CEO. Règle AGT-05.

**G-03-R02** : Tout agent doit recevoir le Glossaire G-07 et la Constitution v1.5 dans son system prompt avant activation.

**G-03-R03** : Un agent ne peut pas être activé si un autre agent du même rôle est déjà ACTIVE. (MVP : max 2 agents simultanés).

**G-03-R04** : Les credentials LLM d'un agent (API key, model ID) sont stockés uniquement en variable d'environnement sécurisée, jamais en base de données.

**G-03-R05** : Chaque agent reçoit un identifiant unique non réutilisable (`{role}-{NNN}`).

---

## Checklist onboarding

- [ ] Décision D1 CEO documentée avec Evidence
- [ ] Provider et model validés par Chief Architect (ACP)
- [ ] System prompt contient Constitution + Glossaire
- [ ] Capability binding actif
- [ ] Premier WP test exécuté et VALIDATED
- [ ] CEO notifié sur Telegram

---

## Références

- Agent Model v1.2 — AGT-01 à AGT-05
- Constitution v1.5 — R-GOV-01, R-GOV-03
- Protocole ACP v1.3 — ACP-01
