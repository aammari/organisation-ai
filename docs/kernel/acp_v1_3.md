# Protocole ACP — v1.3 (résumé kernel)

## Définition

ACP = **Assumption / Constraint / Proposal**

Format obligatoire pour tout livrable produit par un agent. Garantit que le CEO comprend le contexte de chaque proposition avant de décider.

## Structure d'un message ACP

```
## ASSUMPTIONS
- [Liste des hypothèses posées par l'agent pour produire ce livrable]

## CONSTRAINTS  
- [Contraintes identifiées : techniques, temporelles, réglementaires, budgétaires]

## PROPOSAL
- [La proposition concrète de l'agent, actionnable et précise]

## RISKS
- [Risques identifiés si la proposition est adoptée ou rejetée]
```

## Règles ACP

- **ACP-01** : Tout livrable de Chief Architect vers CEO doit être au format ACP.
- **ACP-02** : Un ACP sans section PROPOSAL est invalide — Chief Analyst doit le rejeter (REJECTED).
- **ACP-03** : Les ASSUMPTIONS doivent être explicites. Une assumption implicite est une déviation.
- **ACP-04** : Le CEO répond à un ACP par : APPROVED / REJECTED / DEFERRED.
- **ACP-05** : Un ACP DEFERRED reste en `pending_ceo` jusqu'à résolution explicite.

## États d'un message ACP

`EMITTED` → `VALIDATED` → `APPROVED` | `REJECTED` | `DEFERRED`

## Exemple minimal valide

```
## ASSUMPTIONS
- Le budget alloué est de 0€ (MVP bootstrappé)
- L'infrastructure Render Free Tier est suffisante pour la phase pilote

## CONSTRAINTS
- Render Free Tier : 750h/mois, spin-down après 15min d'inactivité
- Pas de base de données relationnelle dédiée hors Supabase

## PROPOSAL
Déployer l'API FastAPI + bot Telegram sur Render Free Tier
avec Supabase comme couche de persistance unique.

## RISKS
- Latence première requête (cold start ~30s) peut dégrader l'expérience CEO
```
