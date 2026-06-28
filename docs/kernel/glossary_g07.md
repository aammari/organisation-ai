# Glossaire Organisation AI — G07 (résumé kernel)

## Termes fondamentaux

**ACP** (Assumption/Constraint/Proposal) — Format obligatoire de livrable agent. Toute proposition sans ce format est invalide.

**Agent** — Entité IA autonome avec un rôle défini, un provider LLM et une capability assignée. Ne décide pas, propose.

**Audit Log** — Trace immuable de toutes les opérations. Chaque action génère une entrée.

**Capability** — Domaine de compétence d'un agent (ex: Architecture & Delivery, Governance & Analysis).

**Capability Binding** — Lien actif entre un agent et sa capability pour une période donnée.

**CEO** — Décideur humain unique. Seul acteur autorisé pour les décisions D1.

**Chief Analyst** — Agent de validation. Valide ou rejette les livrables du Chief Architect.

**Chief Architect** — Agent de production. Produit les livrables ACP et conçoit l'architecture.

**Décision D1/D2/D3** — Niveau de décision. D1 = CEO, D2 = Chief Architect, D3 = Agent opérationnel.

**Déviation** — Violation d'une règle de gouvernance. Sévérité D1 (critique), D2 (majeur), D3 (mineur).

**Evidence** — Document factuel validé qui fonde une décision. Toute décision D1 requiert une Evidence.

**Exception Report** — Rapport formel d'une déviation. Déclenche un Signal de Gouvernance si D1.

**Executive Request (ER)** — Demande formalisée du CEO entrant dans le système.

**Intent** — Qualification de la demande CEO : ANALYSE | PRODUCTION | ACTION | DECISION.

**Pending CEO** — File d'attente des décisions et escalades requérant l'attention du CEO.

**Signal de Gouvernance (SG)** — Alerte déclenchée par une violation de règle. Suspend l'action en cours.

**Work Package (WP)** — Unité de travail assignée à un agent. Cycle de vie : PROPOSED → DONE.

**WSM** (Workflow State Machine) — Machine d'état définissant les transitions autorisées des projets et WP.

## Codes de référence

| Code | Document |
|------|----------|
| R-GOV-XX | Règle de gouvernance (Constitution v1.5) |
| ACP-XX | Règle ACP (Protocole ACP v1.3) |
| SG-XXX | Signal de Gouvernance (Decision Governance v1.3) |
| OP-XX | Règle opérationnelle (Operational Workflow v1.1) |
| WSM-XX | Règle état machine (WSM v1.2) |
| AGT-XX | Règle agent (Agent Model v1.2) |
