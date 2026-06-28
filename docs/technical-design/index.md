# Design Technique

## Identifiants

Format : `PREFIX-NNNN` (ex. `EVID-0001`, `DEC-0042`)

Préfixes valides : `EVID`, `DEC`, `WP`, `ER`, `EVT`, `AUD`, `PROMPT`, `CAP`

Générés via RPC Supabase `generate_identifier(prefix)`.

## Schéma SQL

Voir `sql/001_schema.sql` pour le schéma complet.

## LangGraph Flow

Nodes : `qualify_intent` → `call_architect` → `validate_output` → `produce_response`
