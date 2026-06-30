# G-11 — Protocole de Communication CEO (CEO Communication Protocol)
**Version** : 1.1 | **Statut** : APPROVED | **Niveau** : D1

---

## Objet

Définit les règles de communication entre le CEO et l'organisation, notamment via le canal Telegram et les endpoints backend.

---

## Canal principal : Telegram

Le bot Telegram (`@OrganisationAI_bot`) est le canal officiel et exclusif de communication CEO ↔ Organisation.

### Flux entrant (CEO → Organisation)

```
CEO message Telegram
   ↓
Chief of Staff (Haiku) — qualify_intent()
   ↓
┌─────────────────────────────────────────┐
│ route: "cycle"        │ route: "thread" │
│ → POST /cycle         │ → POST /thread  │
│   Chief Architect     │   Débat agents  │
│   réponse directe     │   max 3 tours   │
└─────────────────────────────────────────┘
   ↓
Réponse sur Telegram (même conversation)
```

### Flux sortant (Organisation → CEO)

| Type | Canal | Déclencheur |
|---|---|---|
| Réponse cycle | Telegram reply | Fin de cycle /cycle |
| Tour de débat | Reply au message thread | Chaque tour /thread |
| Notification déploiement | Message direct | Merge main réussi |
| Escalade D1 | Message direct | Signal de Gouvernance D1 |
| Revue hebdo | Message direct | Lundi 08h00 UTC |
| Alerte service down | Message direct | Health check échoué |

---

## Règles

**G-11-R01** : Seul le chat_id `8190041183` est autorisé à interagir avec le bot. Tout autre expéditeur est silencieusement ignoré.

**G-11-R02** : Le CEO reçoit une notification Telegram à chaque merge sur `main` (déploiement). Format : service déployé + commit message.

**G-11-R03** : Les réponses du bot utilisent du texte brut structuré (markdown Telegram). Aucune pièce jointe ou média sans demande explicite.

**G-11-R04** : En cas d'intervention CEO dans un thread (reply au message d'ouverture) :
- Texte libre → injecté dans le contexte du prochain tour
- "stop" / "stoppe" / "arrête" → `CEO_STOPPED` immédiat
- "valide" / "ok" / "approved" → `CEO_VALIDATED` immédiat

**G-11-R05** : Le bot ne contacte jamais le CEO de manière non sollicitée sauf pour : escalades D1, alertes P1, notifications de déploiement, et revue hebdomadaire.

**G-11-R06** : Autonomie maximale — les agents traitent sans demander confirmation au CEO sauf pour les décisions D1 explicites.

**G-11-R07** : La durée maximale d'une requête /cycle est 120 secondes. Au-delà, le CEO est notifié du timeout avec le statut partiel.

---

## Format des notifications

```
# Déploiement
✅ Déployé — {service} | commit: {message}

# Escalade
🚨 ESCALADE D1 — {sujet} | Action CEO requise

# Thread terminé
✅ RESOLVED — consensus tour {n}
⚠️ ESCALATED — décision CEO requise
```

---

## Historique des versions

| Version | Date | Changement |
|---|---|---|
| 1.0 | 2026-06-28 | Version initiale |
| 1.1 | 2026-06-29 | Ajout intervention CEO dans thread (G-11-R04) |

---

## Références

- Meeting Protocol G-01
- Security Policy G-05 — G-05-R01
- Agent Model v1.2 — AGT-01
- Workflow Opérationnel v1.1 — OP-03
