# G-07 — Glossaire (Glossary)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Termes fondamentaux

**ACP** (Assumption/Constraint/Proposal) — Format obligatoire de livrable agent. Toute proposition sans ce format est invalide. Voir Protocole ACP v1.3.

**Agent** — Entité IA autonome avec un rôle défini, un provider LLM et une capability assignée. Ne décide pas, propose.

**Audit Log** — Trace immuable de toutes les opérations dans la table `audit_log`. Chaque action génère une entrée.

**Capability** — Domaine de compétence d'un agent (ex: Architecture & Delivery, Governance & Analysis). Voir G-06.

**Capability Binding** — Lien actif entre un agent et sa capability pour une période donnée.

**CEO** — Décideur humain unique. Seul acteur autorisé pour les décisions D1. Identifié par son chat_id Telegram.

**Chief Analyst** — Agent de validation (CAP-002). Valide ou rejette les livrables du Chief Architect.

**Chief Architect** — Agent de production (CAP-001). Produit les livrables ACP et conçoit l'architecture.

**Chief of Staff** — Rôle de qualification d'intention (Haiku). Route les demandes CEO vers /cycle ou /thread.

**Décision D1/D2/D3** — Niveau de décision. D1 = CEO, D2 = Chief Architect, D3 = Agent opérationnel.

**Déviation** — Violation d'une règle de gouvernance. Sévérité D1 (critique), D2 (majeur), D3 (mineur).

**Evidence** — Document factuel validé qui fonde une décision D1/D2. Toute décision D1 requiert une Evidence validée.

**Exception Report (ER)** — Rapport formel d'une déviation. Déclenche un Signal de Gouvernance si D1.

**Executive Request (ER)** — Demande formalisée du CEO entrant dans le système. Format distinct de Exception Report.

**Intent** — Qualification de la demande CEO : ANALYSE | PRODUCTION | ACTION | DECISION.

**Kernel** — Ensemble des documents fondateurs injectés dans le contexte de chaque agent à chaque cycle.

**Pending CEO** — File d'attente des décisions et escalades requérant l'attention du CEO.

**Signal de Gouvernance (SG)** — Alerte déclenchée par une violation de règle. Suspend l'action en cours.

**Thread** — Débat structuré entre Chief Architect et Chief Analyst (max 3 tours). Déclenché pour discussions/validations complexes.

**Work Package (WP)** — Unité de travail assignée à un agent. Cycle de vie : PROPOSED → BACKLOG → READY → EXECUTING → DONE.

**WSM** (Workflow State Machine) — Machine d'état définissant les transitions autorisées des projets et WP.

---

## Codes de référence

| Code | Document |
|---|---|
| G-XX | Règle de gouvernance (ce document et G-01 à G-11) |
| R-GOV-XX | Règle constitutionnelle (Constitution v1.5) |
| ACP-XX | Règle ACP (Protocole ACP v1.3) |
| SG-XXX | Signal de Gouvernance (Decision Governance v1.3) |
| OP-XX | Règle opérationnelle (Operational Workflow v1.1) |
| WSM-XX | Règle état machine (WSM v1.2) |
| AGT-XX | Règle agent (Agent Model v1.2) |

---

## Références

- Tous les documents kernel (Constitution, ACP, WSM, Agent Model, Decision Governance, Operational Workflow)
