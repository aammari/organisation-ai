# G-02 — Politique de Rétention des Données (Data Retention)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit les durées de conservation, les règles de purge et les responsabilités liées aux données produites par l'organisation.

---

## Catégories de données

| Catégorie | Table Supabase | Rétention | Action à expiration |
|---|---|---|---|
| Audit log | `audit_log` | 90 jours | Archivage JSON → suppression |
| Décisions | `decisions` | Permanent | Aucune |
| Work Packages | `work_packages` | 180 jours après DONE | Archivage |
| Threads agents | `agent_threads` + `agent_messages` | 30 jours | Suppression |
| Contexte org | `org_context` | Courant uniquement | Remplacement à chaque refresh |
| Backlog items | `backlog_items` | 60 jours après DONE | Suppression |

---

## Règles

**G-02-R01** : Aucune donnée CEO (messages, décisions D1) ne peut être supprimée sans approbation explicite CEO.

**G-02-R02** : Les données à caractère personnel (chat_id Telegram) sont pseudonymisées dans `audit_log`.

**G-02-R03** : Un backup hebdomadaire de la table `decisions` est obligatoire (Supabase PITR ou export JSON).

**G-02-R04** : Les clés API et tokens ne sont jamais loggés dans `audit_log`. Toute tentative de logging d'un secret déclenche un Signal de Gouvernance SG-006.

**G-02-R05** : La purge automatique est réalisée par le Backlog Worker tous les lundis à 00h00 UTC.

---

## Références

- Constitution v1.5 — R-GOV-02 (traçabilité totale)
- Decision Governance v1.3 — SG-004
- Agent Model v1.2 — AGT-03
