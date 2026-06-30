# G-01 — Protocole de Réunion (Meeting Protocol)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit les règles de toute interaction formelle entre le CEO et les agents de l'organisation. Une « réunion » correspond à tout échange structuré produisant une décision ou un livrable.

---

## Règles

**G-01-R01** : Toute demande CEO doit être formulée comme un Executive Request (ER) explicite. Les messages ambigus sont retournés au CEO avec demande de clarification.

**G-01-R02** : Chaque ER reçoit un identifiant unique (`ER-YYYYMMDD-NNN`) tracé dans `audit_log`.

**G-01-R03** : Le temps de réponse cible est de 60 secondes pour les intents ANALYSE et PRODUCTION, 120 secondes pour ACTION et DECISION.

**G-01-R04** : Toute réponse agent inclut obligatoirement : intent qualifié, décision analyst, et référence ACP.

**G-01-R05** : Les décisions D1 ne peuvent pas être déléguées. Le CEO doit répondre APPROVED / REJECTED / DEFERRED.

**G-01-R06** : Une réunion est considérée close quand le CEO a répondu à l'ACP final ou après 24h sans réponse (→ DEFERRED automatique).

---

## Format de clôture

```
ER-XXXXXXXX : [intent] — [statut final] — [agent responsable]
```

---

## Références

- Constitution v1.5 — R-GOV-04, R-GOV-05
- Protocole ACP v1.3 — ACP-01 à ACP-05
- Workflow Opérationnel v1.1 — OP-03
