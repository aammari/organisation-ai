# G-08 — Dérogation et Exceptions (Exception Waiver)
**Version** : 1.0 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit la procédure permettant au CEO d'autoriser temporairement une dérogation à une règle de gouvernance, avec traçabilité complète.

---

## Principe

Une dérogation (waiver) permet de suspendre temporairement une règle de gouvernance pour un cas précis. Elle ne modifie pas le document de gouvernance source — elle l'overrides ponctuellement avec approbation D1.

---

## Procédure de waiver

```
1. Identification du besoin
   → Agent identifie la règle à déroger (code R-GOV-XX ou G-XX-RXX)
   → Produit un ACP avec justification

2. Demande de waiver
   → INSERT INTO waivers (rule_id, justification, duration, status='PENDING')
   → Notifier CEO sur Telegram

3. Décision CEO (D1)
   → APPROVED → UPDATE waivers SET status='ACTIVE', approved_at=NOW()
   → REJECTED → UPDATE waivers SET status='REJECTED'

4. Application
   → Le waiver est référencé dans chaque action concernée dans audit_log
   → Durée maximale : 7 jours (renouvellement D1 requis)

5. Expiration
   → Waiver passe automatiquement en status='EXPIRED'
   → La règle d'origine reprend effet
   → CEO notifié à J-1 avant expiration
```

---

## Règles

**G-08-R01** : Un waiver ne peut pas déroger aux principes fondateurs de la Constitution (Art. 1-5). Ces règles sont non dérogatoires.

**G-08-R02** : Chaque waiver actif est visible dans le contexte organisationnel injecté aux agents.

**G-08-R03** : Maximum 3 waivers simultanés actifs. Au-delà → révision de la règle source requise.

**G-08-R04** : Un waiver ne peut pas couvrir une violation déjà commise (effet non rétroactif).

**G-08-R05** : Tout waiver est traçé dans `decisions` avec level D1.

---

## Règles non dérogatoires (Constitution v1.5 Art. 1-5)

- Autorité CEO sur les décisions D1
- Traçabilité totale (audit_log)
- Evidence avant décision D1/D2
- Séparation des rôles (Chief Architect ≠ Chief Analyst)
- Escalade obligatoire des déviations D1

---

## Références

- Constitution v1.5 — R-GOV-01 à R-GOV-05
- Decision Governance v1.3 — SG-001 à SG-005
- Config Management G-04
