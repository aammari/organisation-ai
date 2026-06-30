"""WP-M07 — Chief of Staff Conversation Engine.

Natural language intent classification → internal service dispatch → factual CEO response.
Zero LLM for data aggregation. Haiku only for ambiguous classification (fallback).
Budget Protection: deterministic first, Haiku only when intent is genuinely UNKNOWN.
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from anthropic import Anthropic

from app.database import get_supabase
from core.adoption_service import adoption_svc
from core.compliance_engine import compliance_engine
from core.document_improvement_engine import die
from core.goal_planner import goal_planner

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_CONFIDENCE_THRESHOLD = 0.6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_doc_ids(message: str) -> list[str]:
    """Extract document IDs like G-07, A-02, P-01 from a message."""
    matches = re.findall(r'\b([a-zA-Z])-(\d+)\b', message)
    return [f"{g.upper()}-{n.zfill(2)}" for g, n in matches]


# ── Deterministic pattern sets ─────────────────────────────────────────────────

_FOOTBALLIQ_KW = {"footballiq", "football iq"}

_STATUS_KW = [
    "où en est l'org", "état global", "comment va l'org", "comment ça va",
    "bilan org", "vue d'ensemble", "tableau de bord", "état de l'org",
    "où en sommes", "comment se porte", "org health",
]

_BLOCKERS_KW = [
    "blocage", "bloque", "bloquant", "frein", "n'avance pas", "avance pas",
    "qu'est-ce qui manque", "qu'est-ce qui empêche", "obstacle",
    "pourquoi on n'avance", "ce qui manque", "ce qui reste",
    "reste avant", "manque pour", "principaux problème",
    "qu'est-ce qu'il reste",
]

_AUDIT_KW = [
    "relis les doc", "relis les documents", "compare l'existant",
    "compare avec l'existant", "compare avec ce qui est",
    "audit org", "revue org", "analyse les documents",
    "compare les documents",
]

_DOC_STATUS_KW = [
    "pourquoi", "pas adopté", "non adopté", "toujours pas adopté",
    "pas encore adopté", "où en est", "statut de", "état de",
    "qu'est-ce qui se passe avec", "que se passe-t-il avec",
]

_COMPLIANCE_KW = [
    "conformit", "conforme", "respecté", "est-ce que", "compliance",
]

_VALIDATION_KW = ["valide", "valider", "validation", "revalide"]
_ADOPTION_KW = ["adopt", "passe en adopted", "activer"]
_IMPROVEMENT_KW = ["améliore", "ameliore", "corrige", "amélioration"]


def _classify_deterministic(message: str) -> tuple[str, list[str]]:
    """Returns (intent, doc_ids). UNKNOWN → Haiku needed."""
    msg = message.lower()
    doc_ids = _extract_doc_ids(message)

    # FOOTBALLIQ overrides all
    if any(k in msg for k in _FOOTBALLIQ_KW):
        return "FOOTBALLIQ_READINESS", []

    # Intent with specific doc_id
    if doc_ids:
        if any(k in msg for k in _DOC_STATUS_KW):
            return "DOCUMENT_STATUS", doc_ids
        if any(k in msg for k in _AUDIT_KW):
            return "DOCUMENT_AUDIT", doc_ids
        if re.search(r'\bvalid', msg):
            return "VALIDATION_REQUEST", doc_ids
        if re.search(r'\badopt', msg):
            return "ADOPTION_REQUEST", doc_ids
        if any(k in msg for k in _COMPLIANCE_KW):
            return "COMPLIANCE_CHECK", doc_ids
        if any(k in msg for k in _IMPROVEMENT_KW):
            return "IMPROVEMENT_REQUEST", doc_ids
        # Generic doc reference → DOCUMENT_STATUS
        return "DOCUMENT_STATUS", doc_ids

    # Intent without doc_id
    if any(k in msg for k in _BLOCKERS_KW):
        return "ORGANIZATION_BLOCKERS", []

    if any(k in msg for k in _AUDIT_KW):
        return "DOCUMENT_AUDIT", []

    # "status" alone or org-status phrases
    if msg.strip() in ("status", "statut", "état", "bilan", "health") or any(k in msg for k in _STATUS_KW):
        return "ORGANIZATION_STATUS", []

    if re.search(r'\bvalid', msg):
        return "VALIDATION_REQUEST", []
    if re.search(r'\badopt', msg):
        return "ADOPTION_REQUEST", []
    if any(k in msg for k in _COMPLIANCE_KW) and len(msg) < 50:
        return "COMPLIANCE_CHECK", []
    if any(k in msg for k in _IMPROVEMENT_KW):
        return "IMPROVEMENT_REQUEST", []

    return "UNKNOWN", doc_ids


# ── Rendering helpers (formatting only — no workflow logic) ───────────────────


def _health_label(comp_score: int, n_escalated: int, n_d3: int) -> str:
    if comp_score < 70 or n_escalated >= 3 or n_d3 >= 3:
        return "Critique"
    if comp_score < 95 or n_escalated or n_d3:
        return "Attention"
    return "Stable"


def _alerts_block(comp_score: int, escalated: list[str], waiting_ceo: list[dict]) -> str:
    parts = []
    if comp_score < 95:
        parts.append(f"⚠ Conformité {comp_score}% — seuil 95% non atteint")
    for w in waiting_ceo[:2]:
        parts.append(f"⚠ Décision D3 attendue : {w.get('id', '?')}")
    for doc in escalated[:2]:
        parts.append(f"⚠ Validation ESCALATED : {doc}")
    return "\n".join(parts) if parts else "✓ Aucun risque majeur."


def _doc_list(docs: list[str], max_n: int = 6) -> str:
    shown = docs[:max_n]
    rest = len(docs) - len(shown)
    lines = [f"• {d}" for d in shown]
    if rest:
        lines.append(f"• +{rest} autre(s)")
    return "\n".join(lines) if lines else "• Aucun"


def _top_actions(items: list[dict], limit: int = 5) -> list[dict]:
    """Deduplicate by key and cap at limit."""
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.get("key", item.get("text", ""))
        if key not in seen:
            seen.add(key)
            result.append(item)
        if len(result) >= limit:
            break
    return result


# ── Workflow handlers (all return formatted strings) ───────────────────────────

async def _wf_org_status() -> str:
    db = get_supabase()
    try:
        adopted = adoption_svc.list_adopted()
        comp = compliance_engine.compute_compliance_score()
    except Exception as e:
        return f"Erreur lecture organisation : {e}"

    try:
        wp_rows = (db.table("work_packages").select("id,status,priority,title")
                   .in_("status", ["PENDING", "RUNNING", "CLAIMED", "WAITING_CEO"])
                   .execute())
        wps = wp_rows.data or []
    except Exception:
        wps = []

    try:
        esc_rows = (db.table("doc_validations").select("document_id")
                    .eq("status", "ESCALATED")
                    .order("validated_at", desc=True).limit(5).execute())
        escalated = list(dict.fromkeys(r["document_id"] for r in (esc_rows.data or [])))
    except Exception:
        escalated = []

    runs_impl = die.list_runs_by_status("IMPLEMENTATION")
    runs_prop = die.list_runs_by_status("ADOPTION_PROPOSAL")
    runs_esc = die.list_runs_by_status("ESCALATED")

    waiting_ceo = [w for w in wps if w.get("status") == "WAITING_CEO"]
    wp_pending = len([w for w in wps if w.get("status") in ("PENDING", "CLAIMED")])
    wp_running = len([w for w in wps if w.get("status") == "RUNNING"])
    comp_score = comp["overall_score"]

    health = _health_label(comp_score, len(escalated), len(waiting_ceo))
    alerts = _alerts_block(comp_score, escalated, waiting_ceo)

    adopted_ids = [d["doc_id"] for d in adopted]
    impl_docs = list(dict.fromkeys(r["doc_id"] for r in runs_impl))
    prop_docs = list(dict.fromkeys(r["doc_id"] for r in runs_prop))
    esc_die_docs = list(dict.fromkeys(r["doc_id"] for r in runs_esc))

    # Build prioritized, deduplicated action list (max 5)
    raw_actions: list[dict] = []
    for w in waiting_ceo:
        raw_actions.append({
            "key": w["id"],
            "text": f"Approuver {w['id']}",
            "why": f"{w.get('title', '')[:55]}\nDécision D3 requise — bloque l'exécution.",
            "cmd": f"A {w['id']}",
        })
    for doc in prop_docs:
        raw_actions.append({
            "key": doc,
            "text": f"Adopter {doc}",
            "why": "Document validé et conforme. Améliore la readiness FootballIQ.",
            "cmd": f"adopte {doc}",
        })
    if comp["gaps"]:
        gap_codes = ", ".join(g["code"] for g in comp["gaps"][:3])
        raw_actions.append({
            "key": "conformite",
            "text": "Résoudre les gaps de conformité",
            "why": f"Gaps : {gap_codes}\nObjectif : passer de {comp_score}% à 95%.",
        })
    actions = _top_actions(raw_actions)

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {_today()}",
        f"\nOrganisation : {health}",
        f"\n{alerts}",
        SEP,
        "\nDocuments",
        f"\nAdoptés ({len(adopted_ids)}) : {', '.join(adopted_ids[:8]) or 'Aucun'}",
    ]
    if impl_docs:
        lines += ["\nÀ corriger :", _doc_list(impl_docs)]
    if prop_docs:
        lines += ["\nPrêts à adopter :", _doc_list(prop_docs)]
    if esc_die_docs:
        lines += ["\nEscaladés :", _doc_list(esc_die_docs)]

    lines += [
        SEP,
        f"\nConformité : {comp_score}% — {len(comp['gaps'])} gap(s) ouvert(s)",
        SEP,
        "\nWork Packages",
        f"En attente : {wp_pending}  |  En cours : {wp_running}  |  Décision CEO : {len(waiting_ceo)}",
    ]

    if actions:
        lines.append(SEP)
        lines.append("\nLa priorité aujourd'hui :")
        for i, a in enumerate(actions, 1):
            lines.append(f"\n{i}. {a['text']}")
            if a.get("why"):
                lines.append(f"   Pourquoi : {a['why']}")
            if a.get("cmd"):
                lines.append(f"   Commande : {a['cmd']}")

    return "\n".join(lines)


async def _wf_org_blockers() -> str:
    db = get_supabase()
    try:
        comp = compliance_engine.compute_compliance_score()
    except Exception as e:
        return f"Erreur lecture conformité : {e}"

    try:
        waiting_rows = (db.table("work_packages").select("id,title,priority")
                        .eq("status", "WAITING_CEO").limit(5).execute())
        waiting = waiting_rows.data or []
    except Exception:
        waiting = []

    try:
        esc_rows = (db.table("doc_validations").select("document_id")
                    .eq("status", "ESCALATED")
                    .order("validated_at", desc=True).limit(5).execute())
        escalated = list(dict.fromkeys(r["document_id"] for r in (esc_rows.data or [])))
    except Exception:
        escalated = []

    impl_runs = die.list_runs_by_status("IMPLEMENTATION")
    adopted = adoption_svc.list_adopted()

    comp_score = comp["overall_score"]
    health = _health_label(comp_score, len(escalated), len(waiting))
    alerts = _alerts_block(comp_score, escalated, waiting)
    impl_docs = list(dict.fromkeys(r["doc_id"] for r in impl_runs))

    adopted_g = [d for d in adopted if d["doc_id"].startswith("G-")]
    non_adopted_count = max(0, 11 - len(adopted_g))

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {_today()}",
        f"\nOrganisation : {health}",
        f"\n{alerts}",
    ]

    if not comp["gaps"] and not waiting and not escalated and not impl_runs and non_adopted_count == 0:
        lines += [SEP, "\n✓ Aucun blocage organisationnel identifié.",
                  f"Documents adoptés : {len(adopted)} — Conformité : {comp_score}%"]
        return "\n".join(lines)

    lines.append(SEP)
    rank = 1

    if comp["gaps"]:
        gap_codes = ", ".join(g["code"] for g in comp["gaps"][:4])
        lines.append(f"\n{rank}. Conformité insuffisante ({comp_score}%)")
        lines.append(f"   Gaps : {gap_codes}")
        lines.append("   → Objectif : atteindre 95%")
        rank += 1

    if waiting:
        for w in waiting[:2]:
            lines.append(f"\n{rank}. Décision CEO attendue : {w['id']}")
            lines.append(f"   {w.get('title','')[:60]}")
            lines.append(f"   Commande : A {w['id']}")
            rank += 1

    if escalated:
        lines.append(f"\n{rank}. Validation(s) ESCALATED :")
        lines.append(_doc_list(escalated))
        lines.append("   → Intervention requise : 'améliore <doc>'")
        rank += 1

    if impl_docs:
        lines.append(f"\n{rank}. Documents en correction :")
        lines.append(_doc_list(impl_docs))
        rank += 1

    if non_adopted_count:
        lines.append(f"\n{rank}. {non_adopted_count} document(s) gouvernance non adoptés")
        non_adopted_ids = [f"G-{str(i).zfill(2)}" for i in range(1, 12)
                           if f"G-{str(i).zfill(2)}" not in [d["doc_id"] for d in adopted_g]]
        lines.append(_doc_list(non_adopted_ids[:5]))

    # Next step recommendation
    lines.append(SEP)
    if waiting:
        lines.append(f"\nLa prochaine étape est d'approuver {waiting[0]['id']} (D3 bloquant).")
    elif prop_docs := list(dict.fromkeys(r["doc_id"] for r in die.list_runs_by_status("ADOPTION_PROPOSAL"))):
        lines.append(f"\nJe recommande d'adopter {prop_docs[0]} en premier — document prêt.")
    elif comp["gaps"]:
        lines.append(f"\nLe principal blocage est la conformité ({comp_score}%).")
    elif escalated:
        lines.append(f"\nLa priorité est de débloquer la validation de {escalated[0]}.")

    return "\n".join(lines)


async def _wf_footballiq() -> str:
    try:
        plan = await goal_planner.produce_plan("lancer FootballIQ")
    except Exception as e:
        return f"Erreur analyse readiness : {e}"

    readiness = plan["readiness"]
    missing = plan["missing_documents"]
    adopted_docs = plan["adopted_documents"]

    if readiness >= 80:
        verdict = "PRÊT — lancement possible"
        health = "Stable"
    elif readiness >= 50:
        verdict = "PARTIEL — blocages à lever"
        health = "Attention"
    else:
        verdict = "NOT READY — travail significatif requis"
        health = "Critique"

    # Impact projection: each doc adoption ≈ readiness gain
    if missing:
        doc_weight = round(60 / len(plan["required_documents"]))
        projected = min(100, readiness + len(missing) * doc_weight)
        impact_line = f"Readiness FootballIQ : {readiness}% → ~{projected}% (si tous docs adoptés)"
    else:
        impact_line = f"Readiness FootballIQ : {readiness}% — tous documents adoptés"

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {_today()}",
        f"\nOrganisation : {health}",
        f"\n{'⚠ ' if readiness < 80 else '✓ '}FootballIQ : {verdict}",
        SEP,
        f"\nReadiness : {readiness}%",
        f"Documents requis : {len(plan['required_documents'])}",
        f"  Adoptés ({len(adopted_docs)}) : {', '.join(adopted_docs[:6]) or 'Aucun'}",
    ]

    if missing:
        lines += ["\nManquants :", _doc_list(missing)]

    if plan["blockers"]:
        lines.append("\nBlockeurs :")
        for b in plan["blockers"][:4]:
            lines.append(f"• {b}")

    lines += [SEP, "\nImpact attendu :", f"{impact_line}"]

    if plan["requires_ceo_approval"]:
        lines.append("\n⚠ Décision D3 CEO requise avant tout lancement.")

    # Prioritized actions (max 5, deduped)
    raw_actions: list[dict] = []
    for doc in missing[:5]:
        raw_actions.append({
            "key": doc,
            "text": f"Adopter {doc}",
            "why": "Document requis pour FootballIQ — bloque la readiness.",
            "cmd": f"adopte {doc}",
        })
    for wp in plan.get("proposed_work_packages", [])[:3]:
        raw_actions.append({
            "key": wp["title"],
            "text": wp["title"],
            "why": "",
        })
    actions = _top_actions(raw_actions)

    if actions:
        lines.append(SEP)
        lines.append("\nJe recommande :")
        for i, a in enumerate(actions, 1):
            lines.append(f"\n{i}. {a['text']}")
            if a.get("why"):
                lines.append(f"   Pourquoi : {a['why']}")
            if a.get("cmd"):
                lines.append(f"   Commande : {a['cmd']}")

    return "\n".join(lines)


async def _wf_doc_status(doc_ids: list[str]) -> str:
    if not doc_ids:
        return "Précisez le document. Ex : 'statut G-07'"
    doc_id = doc_ids[0]
    db = get_supabase()

    try:
        val_rows = (db.table("doc_validations")
                    .select("status,doc_sha,validated_at,remarks")
                    .eq("document_id", doc_id)
                    .order("validated_at", desc=True).limit(1).execute())
        val = val_rows.data[0] if val_rows.data else None
    except Exception:
        val = None

    try:
        adoption = adoption_svc.get_adoption(doc_id)
    except Exception:
        adoption = None

    run = die.get_latest_run(doc_id)
    comp = compliance_engine.check_document_compliance(doc_id)
    score = 100 if comp.get("status") == "UNKNOWN" else comp.get("score", 0)

    val_status = val["status"] if val else "AUCUNE"
    adop_status = adoption.get("status") if adoption else "NON DEMANDÉE"

    # Determine doc health
    if adop_status == "ADOPTED":
        health = "Stable"
        alert = "✓ Document adopté et actif."
    elif val_status == "ESCALATED":
        health = "Critique"
        alert = "⚠ Validation ESCALATED — intervention requise."
    elif adop_status == "WAITING_CEO":
        health = "Attention"
        alert = "⚠ Décision D3 CEO attendue."
    elif val_status == "RESOLVED" or (run and run.get("status") == "ADOPTION_PROPOSAL"):
        health = "Attention"
        alert = "⚠ Prêt à adopter — action CEO requise."
    else:
        health = "Attention"
        alert = "⚠ Document non encore adopté."

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {doc_id}",
        f"\nDocument : {health}",
        f"\n{alert}",
        SEP,
        f"\nValidation : {val_status}",
    ]
    if val and val.get("validated_at"):
        lines.append(f"  Dernière : {val['validated_at'][:10]}")

    lines.append(f"\nAdoption : {adop_status}")
    if adoption and adoption.get("adopted_at"):
        lines.append(f"  Date : {adoption['adopted_at'][:10]}")

    lines.append(f"\nConformité : {score}%")
    if comp.get("gaps"):
        for g in comp["gaps"][:3]:
            lines.append(f"  [{g.get('severity','?')}] {g.get('description','')[:50]}")

    if run:
        lines.append(f"\nDIE : {run.get('status', '?')} (cycle {run.get('iteration', 0)}/3)")
        if run.get("escalation_reason"):
            lines.append(f"  Cause : {run['escalation_reason'][:80]}")

    lines.append(SEP)

    # Recommendation with reason
    if adop_status == "ADOPTED":
        lines.append("\nAucune action requise.")
    elif adop_status == "WAITING_CEO":
        lines.append("\nJe recommande d'approuver ce document.")
        lines.append("Pourquoi : décision D3 bloquante — l'organisation attend votre validation.")
    elif run and run.get("status") == "ADOPTION_PROPOSAL":
        lines.append(f"\nJe recommande d'adopter {doc_id}.")
        lines.append("Pourquoi : document validé et conforme — prêt à entrer en vigueur.")
        lines.append(f"Commande : adopte {doc_id}")
    elif val_status == "RESOLVED":
        lines.append(f"\nJe recommande d'adopter {doc_id}.")
        lines.append("Pourquoi : validation RESOLVED — aucun blocage restant.")
        lines.append(f"Commande : adopte {doc_id}")
    elif val_status == "ESCALATED":
        lines.append(f"\nLa prochaine étape est de relancer l'amélioration de {doc_id}.")
        lines.append("Pourquoi : validation escaladée — correction requise avant adoption.")
        lines.append(f"Commande : améliore {doc_id}")
    else:
        lines.append(f"\nLa prochaine étape est de valider {doc_id}.")
        lines.append("Pourquoi : aucune validation existante — étape préalable obligatoire.")
        lines.append(f"Commande : valide {doc_id}")

    return "\n".join(lines)


async def _notify_wp_approval_required(
    wp_id: str,
    title: str,
    priority: str,
    level: str,
    purpose: str,
    tg_notify,
    db,
    action_id: str = "",
) -> None:
    """Notify CEO via Telegram when a WP requires approval. Logs NOTIFICATION_FAILED on error."""
    msg = (
        f"WP créé — approbation requise\n\n"
        f"ID :\n{wp_id}\n\n"
        f"Titre :\n{title}\n\n"
        f"Priorité :\n{priority}\n\n"
        f"Niveau :\n{level}\n\n"
        f"Objectif :\n{purpose}\n\n"
        f"Action CEO :\nRépondez :\nA {wp_id}"
    )
    if not tg_notify:
        return
    try:
        await tg_notify(msg)
    except Exception as e:
        logger.error(f"notify_wp {wp_id}: {e}")
        try:
            db.table("action_ledger").insert({
                "id": f"ACT-{uuid.uuid4().hex[:8]}",
                "source": "system",
                "raw_message": f"NOTIFICATION_FAILED: WP {wp_id} — {str(e)[:200]}",
                "state": "NOTIFICATION_FAILED",
                "type": "wp_notification_failed",
                "created_at": _now(),
                "updated_at": _now(),
            }).execute()
        except Exception as e2:
            logger.error(f"notify_wp action_ledger: {e2}")


async def _wf_doc_audit(doc_ids: list[str], action_id: str, tg_notify=None) -> str:
    db = get_supabase()
    wp_id = f"WP-AUDIT-{uuid.uuid4().hex[:6].upper()}"
    scope = " ".join(doc_ids) if doc_ids else "tous documents adoptés"
    title = f"[AUDIT] {scope} — comparaison existant vs implémentation"
    try:
        db.table("work_packages").insert({
            "id": wp_id,
            "title": title,
            "status": "PENDING",
            "approved": False,
            "required_decision_level": "D2",
            "priority": "P1",
            "context_snapshot": {
                "action_id": action_id,
                "doc_ids": doc_ids,
                "type": "ORG_AUDIT",
            },
            "created_at": _now(),
            "updated_at": _now(),
        }).execute()
    except Exception as e:
        logger.error(f"_wf_doc_audit WP insert: {e}")
        return f"Erreur création WP audit : {e}"

    await _notify_wp_approval_required(
        wp_id=wp_id,
        title=title,
        priority="P1",
        level="D2",
        purpose="Comparer l'organisation réelle avec les documents officiels.",
        tg_notify=tg_notify,
        db=db,
        action_id=action_id,
    )

    return (
        f"Audit organisationnel lancé.\n\n"
        f"Scope : {scope}\n"
        f"WP créé : {wp_id}\n\n"
        f"Cette analyse nécessite un traitement approfondi.\n"
        f"Approuvez avec : 'A {wp_id}'\n"
        f"Notification Telegram envoyée."
    )


async def _wf_validation(doc_ids: list[str]) -> str:
    if not doc_ids:
        return "Précisez le document à valider. Ex : 'valide G-07'"
    doc_id = doc_ids[0]
    return (
        f"Pour valider {doc_id}, répondez :\n"
        f"valide {doc_id}\n\n"
        f"Le Chief Architect et Chief Analyst examineront le document GitHub."
    )


async def _wf_adoption(doc_ids: list[str]) -> str:
    if not doc_ids:
        return "Précisez le document à adopter. Ex : 'adopte G-07'"
    doc_id = doc_ids[0]
    try:
        result = await adoption_svc.request_adoption(doc_id)
        status = result.get("status", "?")
        if status == "ADOPTED":
            return (
                f"{doc_id} — ADOPTED\n"
                f"Version : {result.get('version', '?')}\n"
                f"Niveau : {result.get('decision_level', '?')}"
            )
        if status == "WAITING_CEO":
            return f"{doc_id} — WAITING_CEO (D3)\nApprobation CEO requise avant adoption."
        if status == "REFUSED":
            return f"{doc_id} — REFUSÉ\nRaison : {result.get('reason', '?')}\n{result.get('detail', '')}"
        return f"{doc_id} — {status}\n{result.get('detail', '')}"
    except Exception as e:
        return f"Erreur adoption {doc_id} : {e}"


async def _wf_compliance(doc_ids: list[str]) -> str:
    if doc_ids:
        doc_id = doc_ids[0]
        try:
            comp = compliance_engine.check_document_compliance(doc_id)
        except Exception as e:
            return f"Erreur conformité {doc_id} : {e}"
        score = 100 if comp.get("status") == "UNKNOWN" else comp.get("score", 0)
        gaps = comp.get("gaps", [])
        lines = [f"Conformité {doc_id} : {score}% ({comp.get('status', '?')})"]
        if gaps:
            lines.append(f"\nGaps ({len(gaps)}) :")
            for g in gaps[:3]:
                lines.append(f"  [{g['severity']}] {g['description']}")
        elif comp.get("status") == "UNKNOWN":
            lines.append("\nAucune règle de conformité définie pour ce document.")
        else:
            lines.append("\nAucun gap — document conforme.")
        return "\n".join(lines)
    else:
        try:
            comp = compliance_engine.compute_compliance_score()
        except Exception as e:
            return f"Erreur conformité globale : {e}"
        return (
            f"Conformité globale : {comp['overall_score']}%\n"
            f"Documents vérifiés : {comp['documents_checked']}\n"
            f"Conformes : {comp['compliant']}\n"
            f"Partiels : {comp['partial']}\n"
            f"Non-conformes : {comp['non_compliant']}\n"
            f"Gaps ouverts : {len(comp['gaps'])}"
        )


async def _wf_improvement(doc_ids: list[str], background_tasks, tg_notify) -> str:
    if not doc_ids:
        return "Précisez le document à améliorer. Ex : 'améliore G-07'"
    doc_id = doc_ids[0]
    try:
        existing = die.get_latest_run(doc_id)
        if existing and existing.get("status") == "IMPLEMENTATION":
            run = existing
            reused = True
        else:
            run = die.create_run(doc_id)
            reused = False
        if background_tasks:
            background_tasks.add_task(die.run_cycle, run["id"], tg_notify)
        return (
            f"DIE — {doc_id}\n"
            f"Run : {run['id']}\n"
            f"{'Cycle supplémentaire sur run existant.' if reused else 'Nouveau cycle lancé.'}\n"
            f"CEO notifié à chaque étape."
        )
    except Exception as e:
        return f"Erreur amélioration {doc_id} : {e}"


def _clarify_response() -> str:
    return (
        "Intention non reconnue.\n\n"
        "Exemples :\n"
        "• 'Est-ce qu'on peut lancer FootballIQ ?'\n"
        "• 'Quels sont les blocages ?'\n"
        "• 'Pourquoi G-07 n'est pas adopté ?'\n"
        "• 'Où en est l'organisation ?'\n"
        "• 'Relis les documents et compare avec l'existant'\n\n"
        "Commandes directes : 'valide G-07', 'adopte G-07', 'organisation health'"
    )


# ── Haiku fallback ─────────────────────────────────────────────────────────────

_HAIKU_SYSTEM = """Classifie ce message CEO parmi ces 10 intentions exactes :

ORGANIZATION_STATUS — état global de l'organisation
ORGANIZATION_BLOCKERS — blocages, freins, obstacles
FOOTBALLIQ_READINESS — readiness pour lancer FootballIQ
DOCUMENT_AUDIT — relire, comparer, auditer des documents
DOCUMENT_STATUS — statut d'un document spécifique
VALIDATION_REQUEST — valider un document
ADOPTION_REQUEST — adopter un document
COMPLIANCE_CHECK — conformité d'un document
IMPROVEMENT_REQUEST — améliorer ou corriger un document
UNKNOWN — aucune intention claire

Retourne UNIQUEMENT un JSON valide sans markdown :
{"intent": "ORGANIZATION_STATUS", "confidence": 0.85, "doc_ids": [], "reason": "..."}

confidence entre 0.0 et 1.0. doc_ids : liste des identifiants de documents (ex: ["G-07"]) ou []."""


async def _haiku_classify(message: str) -> dict:
    try:
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=128,
            system=_HAIKU_SYSTEM,
            messages=[{"role": "user", "content": message}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
        # Merge Haiku doc_ids with regex extraction (deduplicated)
        regex_ids = _extract_doc_ids(message)
        haiku_ids = result.get("doc_ids") or []
        merged = list(dict.fromkeys(haiku_ids + regex_ids))
        result["doc_ids"] = merged
        return result
    except Exception as e:
        logger.warning(f"haiku_classify: {e}")
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "doc_ids": _extract_doc_ids(message),
            "reason": str(e),
        }


# ── Main engine ────────────────────────────────────────────────────────────────

class ConversationEngine:
    async def classify(self, message: str) -> dict:
        """Returns {intent, doc_ids, confidence, source}."""
        intent, doc_ids = _classify_deterministic(message)
        if intent != "UNKNOWN":
            return {
                "intent": intent,
                "doc_ids": doc_ids,
                "confidence": 1.0,
                "source": "deterministic",
            }
        # Haiku fallback — Budget Protection: only when truly ambiguous
        haiku = await _haiku_classify(message)
        return {
            "intent": haiku.get("intent", "UNKNOWN"),
            "doc_ids": haiku.get("doc_ids") or doc_ids,
            "confidence": float(haiku.get("confidence", 0.0)),
            "source": "haiku",
            "reason": haiku.get("reason", ""),
        }

    async def handle(
        self,
        message: str,
        action_id: str = "",
        background_tasks=None,
        tg_notify=None,
    ) -> dict:
        classification = await self.classify(message)
        intent = classification["intent"]
        doc_ids = classification["doc_ids"]
        confidence = classification["confidence"]
        source = classification["source"]

        logger.info(
            f"CE intent={intent} confidence={confidence:.2f} "
            f"source={source} docs={doc_ids}"
        )

        # Low confidence → ask for clarification (never forward raw LLM)
        if intent == "UNKNOWN" or (source == "haiku" and confidence < HAIKU_CONFIDENCE_THRESHOLD):
            return {
                "intent": "UNKNOWN",
                "confidence": confidence,
                "response": _clarify_response(),
                "source": source,
            }

        # Dispatch
        try:
            if intent == "ORGANIZATION_STATUS":
                response = await _wf_org_status()
            elif intent == "ORGANIZATION_BLOCKERS":
                response = await _wf_org_blockers()
            elif intent == "FOOTBALLIQ_READINESS":
                response = await _wf_footballiq()
            elif intent == "DOCUMENT_STATUS":
                response = await _wf_doc_status(doc_ids)
            elif intent == "DOCUMENT_AUDIT":
                response = await _wf_doc_audit(doc_ids, action_id, tg_notify)
            elif intent == "VALIDATION_REQUEST":
                response = await _wf_validation(doc_ids)
            elif intent == "ADOPTION_REQUEST":
                response = await _wf_adoption(doc_ids)
            elif intent == "COMPLIANCE_CHECK":
                response = await _wf_compliance(doc_ids)
            elif intent == "IMPROVEMENT_REQUEST":
                response = await _wf_improvement(doc_ids, background_tasks, tg_notify)
            else:
                response = _clarify_response()
        except Exception as e:
            logger.error(f"CE dispatch {intent}: {e}")
            response = f"Erreur traitement ({intent}): {e}"

        return {
            "intent": intent,
            "confidence": confidence,
            "response": response,
            "source": source,
            "doc_ids": doc_ids,
        }


conversation_engine = ConversationEngine()
