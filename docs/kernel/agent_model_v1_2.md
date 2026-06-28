# Modèle des Agents — v1.2 (résumé kernel)

## Agents actifs

### Chief Architect (chief-architect-001)
- **Provider** : Anthropic — claude-sonnet-4-6
- **Capability** : Architecture & Delivery
- **Rôle** : Produit les livrables ACP, conçoit l'architecture, alloue les Work Packages
- **Ne peut pas** : valider ses propres livrables, prendre des décisions D1

### Chief Analyst (chief-analyst-001)
- **Provider** : Groq — llama-3.3-70b-versatile
- **Capability** : Governance & Analysis
- **Rôle** : Valide les livrables du Chief Architect, déclenche les Signaux de Gouvernance
- **Ne peut pas** : produire des livrables, prendre des décisions D1

## Règles du modèle agent

- **AGT-01** : Un agent ne peut pas valider son propre livrable (séparation des rôles).
- **AGT-02** : Un agent inactif (status: INACTIVE) ne peut pas recevoir de WP.
- **AGT-03** : Chaque agent est lié à une et une seule capability active.
- **AGT-04** : Le changement de provider LLM d'un agent est une décision D2 (Chief Architect).
- **AGT-05** : La création d'un nouvel agent est une décision D1 (CEO).

## Cycle de vie d'un agent

`ACTIVE` → `SUSPENDED` → `ACTIVE` (réactivation CEO)
`ACTIVE` → `RETIRED` (décision D1 finale)

## Capability Bindings

Un `capability_binding` associe un agent à une capability pour une période donnée. Un binding `ACTIVE` est requis pour qu'un agent puisse exécuter des WP.

## Limites opérationnelles actuelles (MVP)

- Maximum 2 agents actifs simultanément (Chief Architect + Chief Analyst)
- Pas de parallélisme de WP (séquentiel)
- Pas de mémoire persistante entre les cycles (stateless)
