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

_ADVICE_INTENT_KW = [
    "que me recommande", "recommande-tu", "priorité aujourd'hui",
    "dois-je faire maintenant", "dois-je faire en premier",
    "si tu étais à ma place", "meilleure prochaine action",
    "que faire maintenant", "par où commencer",
    "première action", "quelle est la priorité",
]

_QUESTION_MODE_KW = [
    "explique", "pourquoi", "comment", "qu'est-ce", "qu'est ce",
    "c'est quoi", "signifie", "dis-moi pourquoi", "que veut dire",
    "qu'est-il", "quel est l'objectif", "quelle est la raison",
]

_WP_ID_RE = re.compile(r'\b(WP-[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)\b', re.IGNORECASE)


def _extract_wp_ids(message: str) -> list[str]:
    return [m.upper() for m in _WP_ID_RE.findall(message)]


def _classify_deterministic(message: str) -> tuple[str, list[str]]:
    """Returns (intent, doc_ids). UNKNOWN → Haiku needed."""
    msg = message.lower()
    doc_ids = _extract_doc_ids(message)

    # FOOTBALLIQ overrides all
    if any(k in msg for k in _FOOTBALLIQ_KW):
        return "FOOTBALLIQ_READINESS", []

    # EXECUTIVE_ADVICE — explicit advice/priority request
    if any(k in msg for k in _ADVICE_INTENT_KW):
        return "EXECUTIVE_ADVICE", []

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


def _health_reasons(comp_score: int, escalated: list[str], waiting_ceo: list[dict]) -> list[str]:
    reasons = []
    if comp_score < 80:
        reasons.append(f"conformité critique : {comp_score}%")
    elif comp_score < 95:
        reasons.append(f"conformité {comp_score}% (seuil 95% non atteint)")
    if waiting_ceo:
        reasons.append(f"{len(waiting_ceo)} décision(s) D3 CEO en attente")
    if escalated:
        reasons.append(f"{len(escalated)} document(s) ESCALATED")
    return reasons


async def _canonical_doc_state(doc_id: str, db) -> dict:
    """Returns the single authoritative state for a document, with inconsistency detection."""
    try:
        val_rows = (db.table("doc_validations").select("status,validated_at")
                    .eq("document_id", doc_id).order("validated_at", desc=True).limit(1).execute())
        val = val_rows.data[0] if val_rows.data else None
    except Exception:
        val = None

    try:
        adoption = adoption_svc.get_adoption(doc_id)
    except Exception:
        adoption = None

    run = die.get_latest_run(doc_id)

    adop_status = adoption.get("status") if adoption else None
    val_status = val["status"] if val else None
    run_status = run.get("status") if run else None

    # Priority: ADOPTED > WAITING_CEO > ADOPTION_PROPOSAL > ESCALATED > CHANGES_REQUIRED > VALIDATED > UNKNOWN
    inconsistencies = []
    if adop_status == "ADOPTED" and run_status in ("IMPLEMENTATION", "ESCALATED"):
        inconsistencies.append(f"adopté mais DIE encore {run_status}")

    if adop_status == "ADOPTED":
        canonical = "ADOPTED"
    elif adop_status == "WAITING_CEO":
        canonical = "WAITING_CEO"
    elif run_status == "ADOPTION_PROPOSAL" or val_status == "RESOLVED":
        canonical = "ADOPTION_PROPOSAL"
    elif val_status == "ESCALATED" or run_status == "ESCALATED":
        canonical = "ESCALATED"
    elif val_status in ("CHANGES_REQUIRED", "ISSUES_FOUND"):
        canonical = "CHANGES_REQUIRED"
    elif val_status == "RESOLVED":
        canonical = "VALIDATED"
    else:
        canonical = "UNKNOWN"

    return {
        "canonical": canonical,
        "val_status": val_status,
        "adop_status": adop_status,
        "run_status": run_status,
        "inconsistencies": inconsistencies,
        "val_date": val["validated_at"][:10] if val and val.get("validated_at") else None,
    }


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
    reasons = _health_reasons(comp_score, escalated, waiting_ceo)

    adopted_ids = [d["doc_id"] for d in adopted]
    impl_docs = list(dict.fromkeys(r["doc_id"] for r in runs_impl))
    prop_docs = list(dict.fromkeys(r["doc_id"] for r in runs_prop))
    esc_die_docs = list(dict.fromkeys(r["doc_id"] for r in runs_esc))

    # WP decomposition by type (PARTIE L)
    wp_by_type: dict[str, list[str]] = {}
    for w in wps:
        ctx = w.get("context_snapshot") or {}
        wp_type = ctx.get("type", w.get("title", "")[:12] or "Autre")
        if w.get("status") == "WAITING_CEO":
            wp_type = "Décision CEO"
        wp_by_type.setdefault(wp_type, []).append(w.get("id", "?"))

    # Build prioritized, deduplicated action list (max 5)
    raw_actions: list[dict] = []
    for w in waiting_ceo:
        raw_actions.append({
            "key": w["id"],
            "text": f"Approuver {w['id']}",
            "why": f"{w.get('title', '')[:55]}\nDécision D3 requise — bloque l'exécution.",
            "impact": "Débloque le WP et relance le workflow.",
            "cmd": f"A {w['id']}",
        })
    for doc in prop_docs:
        raw_actions.append({
            "key": doc,
            "text": f"Adopter {doc}",
            "why": "Document validé et conforme — prêt à entrer en vigueur.",
            "impact": "Améliore la readiness FootballIQ et la conformité.",
            "cmd": f"adopte {doc}",
        })
    if comp["gaps"]:
        gap_codes = ", ".join(g["code"] for g in comp["gaps"][:3])
        raw_actions.append({
            "key": "conformite",
            "text": "Résoudre les gaps de conformité",
            "why": f"Gaps : {gap_codes}",
            "impact": f"Conformité {comp_score}% → objectif 95%.",
        })
    actions = _top_actions(raw_actions)

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {_today()}",
        f"\nOrganisation : {health}",
    ]
    if reasons:
        lines.append("Pourquoi :")
        for r in reasons:
            lines.append(f"• {r}")
    lines += [f"\n{alerts}", SEP, "\nDocuments",
              f"\nAdoptés ({len(adopted_ids)}) : {', '.join(adopted_ids[:8]) or 'Aucun'}"]
    if impl_docs:
        lines += ["\nÀ corriger :", _doc_list(impl_docs)]
    if prop_docs:
        lines += ["\nPrêts à adopter :", _doc_list(prop_docs)]
    if esc_die_docs:
        lines += ["\nEscaladés :", _doc_list(esc_die_docs)]

    lines += [SEP, f"\nConformité : {comp_score}% — {len(comp['gaps'])} gap(s) ouvert(s)", SEP,
              "\nWork Packages"]
    if wp_by_type:
        for wtype, wids in list(wp_by_type.items())[:4]:
            lines.append(f"• {wtype} : {len(wids)}")
    else:
        lines.append(f"En attente : {wp_pending}  |  En cours : {wp_running}  |  Décision CEO : {len(waiting_ceo)}")

    if actions:
        lines.append(SEP)
        lines.append("\nLa priorité aujourd'hui :")
        for i, a in enumerate(actions, 1):
            lines.append(f"\n{i}. {a['text']}")
            if a.get("why"):
                lines.append(f"   Pourquoi : {a['why']}")
            if a.get("impact"):
                lines.append(f"   Impact : {a['impact']}")
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
    reasons = _health_reasons(comp_score, escalated, waiting)
    impl_docs = list(dict.fromkeys(r["doc_id"] for r in impl_runs))
    adopted_g = [d for d in adopted if d["doc_id"].startswith("G-")]
    non_adopted_count = max(0, 11 - len(adopted_g))

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {_today()}",
        f"\nOrganisation : {health}",
    ]
    if reasons:
        lines.append("Pourquoi :")
        for r in reasons:
            lines.append(f"• {r}")
    lines.append(f"\n{alerts}")

    if not comp["gaps"] and not waiting and not escalated and not impl_runs and non_adopted_count == 0:
        lines += [SEP, "\n✓ Aucun blocage organisationnel identifié.",
                  f"Documents adoptés : {len(adopted)} — Conformité : {comp_score}%"]
        return "\n".join(lines)

    # ── Catégorie 1 : Décisions CEO requises ──
    if waiting:
        lines += [SEP, "\nDécisions CEO requises :"]
        for w in waiting[:3]:
            level = w.get("required_decision_level", "D3")
            lines.append(f"\n• {w['id']} ({level})")
            lines.append(f"  Titre : {w.get('title','')[:60]}")
            lines.append("  Impact si approuvé : exécution déléguée au Chief of Staff.")
            lines.append("  Impact si refusé : WP archivé.")
            lines.append(f"  Commande : A {w['id']}")

    # ── Catégorie 2 : Blocages techniques ──
    tech_blocks = []
    if comp["gaps"]:
        gap_codes = ", ".join(g["code"] for g in comp["gaps"][:4])
        tech_blocks.append(f"Conformité {comp_score}% — gaps : {gap_codes}")
    if escalated:
        tech_blocks.append(f"Validations ESCALATED : {', '.join(escalated[:3])}")
    if impl_docs:
        tech_blocks.append(f"Documents en correction ({len(impl_docs)}) : {', '.join(impl_docs[:4])}")

    if tech_blocks:
        lines += [SEP, "\nBlocages techniques :"]
        for i, b in enumerate(tech_blocks, 1):
            lines.append(f"\n{i}. {b}")

    # ── Catégorie 3 : Gouvernance ──
    if non_adopted_count:
        non_adopted_ids = [f"G-{str(i).zfill(2)}" for i in range(1, 12)
                           if f"G-{str(i).zfill(2)}" not in [d["doc_id"] for d in adopted_g]]
        lines += [SEP, f"\nGouvernance — {non_adopted_count} document(s) non adoptés :"]
        lines.append(_doc_list(non_adopted_ids[:6]))

    # Next step recommendation
    lines.append(SEP)
    if waiting:
        w = waiting[0]
        lines.append(f"\nLa prochaine étape est d'approuver {w['id']} — décision D3 bloquante.")
    elif prop_docs := list(dict.fromkeys(r["doc_id"] for r in die.list_runs_by_status("ADOPTION_PROPOSAL"))):
        lines.append(f"\nJe recommande d'adopter {prop_docs[0]} — document prêt, aucun blocage restant.")
    elif comp["gaps"]:
        lines.append(f"\nLe principal blocage est la conformité ({comp_score}% — objectif 95%).")
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

    state = await _canonical_doc_state(doc_id, db)
    canonical = state["canonical"]
    val_status = state["val_status"] or "AUCUNE"
    adop_status = state["adop_status"] or "NON DEMANDÉE"

    comp = compliance_engine.check_document_compliance(doc_id)
    score = 100 if comp.get("status") == "UNKNOWN" else comp.get("score", 0)
    run = die.get_latest_run(doc_id)

    # Single health from canonical state
    _health_map = {
        "ADOPTED": ("Stable", "✓ Document adopté et actif."),
        "WAITING_CEO": ("Attention", "⚠ Décision D3 CEO attendue."),
        "ADOPTION_PROPOSAL": ("Attention", "⚠ Prêt à adopter — action CEO requise."),
        "ESCALATED": ("Critique", "⚠ Validation ESCALATED — intervention requise."),
        "CHANGES_REQUIRED": ("Attention", "⚠ Corrections requises avant adoption."),
        "VALIDATED": ("Attention", "⚠ Validé mais non encore adopté."),
        "UNKNOWN": ("Attention", "⚠ Document non encore validé."),
    }
    health, alert = _health_map.get(canonical, ("Attention", "⚠ Statut inconnu."))

    SEP = "\n───────────────────"
    lines = [
        f"Résumé exécutif — {doc_id}",
        f"\nDocument : {health}",
        f"\n{alert}",
    ]

    # Flag inconsistencies (ECT-09)
    if state["inconsistencies"]:
        for inc in state["inconsistencies"]:
            lines.append(f"⚠ Incohérence interne détectée : {inc}")
        lines.append("  → Répondez 'améliore " + doc_id + "' pour un cycle de nettoyage.")

    lines += [
        SEP,
        f"\nÉtat canonique : {canonical}",
        f"Validation : {val_status}",
    ]
    if state.get("val_date"):
        lines.append(f"  Dernière : {state['val_date']}")

    lines.append(f"\nAdoption : {adop_status}")

    comp_label = "Aucune règle définie" if comp.get("status") == "UNKNOWN" else f"{score}%"
    lines.append(f"\nConformité : {comp_label}")
    if comp.get("gaps"):
        for g in comp["gaps"][:2]:
            lines.append(f"  [{g.get('severity','?')}] {g.get('description','')[:50]}")

    if run:
        lines.append(f"\nDIE : {run.get('status', '?')} (cycle {run.get('iteration', 0)}/3)")
        if run.get("escalation_reason"):
            lines.append(f"  Cause : {run['escalation_reason'][:80]}")

    lines.append(SEP)

    # Recommendation (one, actionable, with why/impact/command/risk)
    if canonical == "ADOPTED":
        lines.append("\nAucune action requise.")
    elif canonical == "WAITING_CEO":
        lines.append("\nJe recommande d'approuver ce document.")
        lines.append("Pourquoi : décision D3 bloquante — l'organisation attend votre validation.")
        lines.append("Impact : débloque l'adoption et les flux dépendants.")
        lines.append("Risque : faible — adoption réversible.")
        lines.append("Commande : A <WP-ID associé>")
    elif canonical == "ADOPTION_PROPOSAL":
        lines.append(f"\nJe recommande d'adopter {doc_id}.")
        lines.append("Pourquoi : document validé et conforme — prêt à entrer en vigueur.")
        lines.append("Impact : améliore la readiness FootballIQ et la conformité organisationnelle.")
        lines.append("Risque : faible — adoption réversible.")
        lines.append(f"Commande : adopte {doc_id}")
    elif canonical == "ESCALATED":
        lines.append(f"\nLa prochaine étape est de relancer l'amélioration de {doc_id}.")
        lines.append("Pourquoi : validation escaladée — correction requise avant adoption.")
        lines.append("Impact : débloque la chaîne d'adoption.")
        lines.append("Risque : faible — déclenche un cycle DIE automatique.")
        lines.append(f"Commande : améliore {doc_id}")
    elif canonical in ("VALIDATED", "CHANGES_REQUIRED"):
        lines.append(f"\nJe recommande d'adopter {doc_id}.")
        lines.append("Pourquoi : validation RESOLVED — aucun blocage restant.")
        lines.append("Impact : un document de plus actif dans l'organisation.")
        lines.append(f"Commande : adopte {doc_id}")
    else:
        lines.append(f"\nLa prochaine étape est de valider {doc_id}.")
        lines.append("Pourquoi : aucune validation existante — étape préalable obligatoire.")
        lines.append("Impact : ouvre la voie à l'adoption.")
        lines.append(f"Commande : valide {doc_id}")

    return "\n".join(lines)


async def _wf_explain_wp(wp_id: str) -> str:
    """Explain a WP without creating new WPs (QUESTION mode — D0 read-only)."""
    db = get_supabase()
    try:
        row = db.table("work_packages").select("*").eq("id", wp_id.upper()).execute()
    except Exception as e:
        return f"Erreur lecture WP {wp_id} : {e}"

    if not row.data:
        # WP not found — list pending CEO WPs
        try:
            pending = (db.table("work_packages").select("id,title,priority,required_decision_level")
                       .eq("approved", False).eq("status", "PENDING")
                       .order("priority").limit(5).execute())
            pending_list = pending.data or []
        except Exception:
            pending_list = []

        lines = [f"Le Work Package {wp_id} est introuvable."]
        if pending_list:
            lines += ["\nWPs actuellement en attente d'approbation CEO :"]
            for w in pending_list:
                lines.append(f"• {w['id']} ({w.get('priority','?')}, {w.get('required_decision_level','?')}) — {w.get('title','')[:55]}")
        else:
            lines.append("\nAucun WP en attente d'approbation CEO.")
        return "\n".join(lines)

    wp = row.data[0]
    level = wp.get("required_decision_level", "D1")
    title = wp.get("title", "sans titre")
    status = wp.get("status", "?")
    priority = wp.get("priority", "?")
    ctx = wp.get("context_snapshot") or {}

    _D_WHY = {
        "D3": "Décision CEO obligatoire — impact majeur ou irréversible sur l'organisation.",
        "D2": "Décision déléguée — impact modéré, réversible, peut être exécuté sans CEO.",
        "D1": "Décision automatique — aucun impact CEO, exécuté par les agents.",
    }

    SEP = "\n───────────────────"
    lines = [
        f"Work Package {wp_id}",
        f"\nTitre : {title}",
        f"Statut : {status}  |  Priorité : {priority}  |  Niveau : {level}",
        SEP,
        f"\nPourquoi {level} ?",
        f"{_D_WHY.get(level, f'Niveau {level}.')}",
    ]

    if ctx.get("type"):
        lines.append(f"\nType : {ctx['type']}")

    if level in ("D3", "D2"):
        lines += [
            SEP,
            "\nConséquences :",
            "• Si approuvé (A) : le WP sera exécuté par le Chief of Staff.",
            "• Si refusé (B)  : le WP sera archivé (statut REJECTED).",
            "\nRisque : exécution irréversible selon le type d'action.",
            SEP,
            "\nCommande :",
            f"  Approuver : A {wp_id}",
            f"  Refuser   : B {wp_id}",
        ]

    return "\n".join(lines)


async def _wf_executive_advice() -> str:
    """Return a single actionable top recommendation for the CEO (EXECUTIVE_ADVICE)."""
    db = get_supabase()
    try:
        adopted = adoption_svc.list_adopted()
        comp = compliance_engine.compute_compliance_score()
    except Exception as e:
        return f"Erreur lecture organisation : {e}"

    try:
        waiting_rows = (db.table("work_packages").select("id,title,priority,required_decision_level")
                        .eq("status", "WAITING_CEO").order("priority").limit(3).execute())
        waiting_ceo = waiting_rows.data or []
    except Exception:
        waiting_ceo = []

    try:
        esc_rows = (db.table("doc_validations").select("document_id")
                    .eq("status", "ESCALATED").order("validated_at", desc=True).limit(3).execute())
        escalated = list(dict.fromkeys(r["document_id"] for r in (esc_rows.data or [])))
    except Exception:
        escalated = []

    runs_prop = die.list_runs_by_status("ADOPTION_PROPOSAL")
    prop_docs = list(dict.fromkeys(r["doc_id"] for r in runs_prop))

    comp_score = comp["overall_score"]

    # Determine single best action
    SEP = "\n───────────────────"
    if waiting_ceo:
        w = waiting_ceo[0]
        primary = {
            "text": f"Approuver {w['id']}",
            "why": f"Décision D3 bloquante — {w.get('title','')[:60]}\nL'exécution est en attente de votre approbation.",
            "impact": "Débloque immédiatement le work package et relance le workflow.",
            "cmd": f"A {w['id']}",
            "risk": "Action irréversible — le WP sera exécuté.",
        }
    elif prop_docs:
        primary = {
            "text": f"Adopter {prop_docs[0]}",
            "why": "Document validé et conforme — prêt à entrer en vigueur.",
            "impact": "Réduit le nombre de documents non adoptés et améliore la readiness FootballIQ.",
            "cmd": f"adopte {prop_docs[0]}",
            "risk": "Faible — adoption réversible par une nouvelle décision CEO.",
        }
    elif escalated:
        primary = {
            "text": f"Relancer l'amélioration de {escalated[0]}",
            "why": "Validation ESCALATED — le document est bloqué et ne peut pas être adopté.",
            "impact": "Débloque la chaîne d'adoption et améliore la conformité.",
            "cmd": f"améliore {escalated[0]}",
            "risk": "Faible — déclenche un nouveau cycle d'amélioration automatique.",
        }
    elif comp_score < 95:
        primary = {
            "text": "Résoudre les gaps de conformité",
            "why": f"Conformité {comp_score}% — seuil 95% non atteint.",
            "impact": f"Passage de {comp_score}% à 95% débloque les flux de gouvernance.",
            "cmd": "Quels sont les blocages ?",
            "risk": "Aucun — analyse uniquement.",
        }
    else:
        adopted_ids = [d["doc_id"] for d in adopted]
        primary = {
            "text": "Organisation en bonne santé",
            "why": f"Conformité {comp_score}% — aucun blocage critique identifié.",
            "impact": f"{len(adopted_ids)} documents adoptés.",
            "cmd": None,
            "risk": None,
        }

    lines = [
        f"Résumé exécutif — {_today()}",
        SEP,
        "\nPriorité principale :",
        f"\n{primary['text']}",
        f"\nPourquoi : {primary['why']}",
        f"Impact : {primary['impact']}",
    ]
    if primary.get("cmd"):
        lines.append(f"Commande : {primary['cmd']}")
    if primary.get("risk"):
        lines.append(f"Risque : {primary['risk']}")

    # Up to 3 secondary actions
    secondary = []
    seen = {primary["text"]}
    candidates = []
    for doc in prop_docs[1:3]:
        candidates.append({"text": f"Adopter {doc}", "cmd": f"adopte {doc}"})
    for w in waiting_ceo[1:]:
        candidates.append({"text": f"Approuver {w['id']}", "cmd": f"A {w['id']}"})
    if escalated:
        for doc in escalated[:2]:
            candidates.append({"text": f"Améliorer {doc}", "cmd": f"améliore {doc}"})
    for c in candidates:
        if c["text"] not in seen and len(secondary) < 3:
            seen.add(c["text"])
            secondary.append(c)

    if secondary:
        lines += [SEP, "\nActions secondaires :"]
        for i, s in enumerate(secondary, 1):
            lines.append(f"{i}. {s['text']} → {s['cmd']}")

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
    """D0 read-only audit — immediate Supabase-based analysis, no CEO approval required."""
    db = get_supabase()
    adopted = adoption_svc.list_adopted()
    adopted_map = {d["doc_id"]: d for d in adopted}

    try:
        comp = compliance_engine.compute_compliance_score()
        comp_score = comp["overall_score"]
        gap_codes = ", ".join(g["code"] for g in comp["gaps"][:4]) if comp["gaps"] else "Aucun"
    except Exception:
        comp_score = None
        gap_codes = "?"

    # Scope: explicit docs or all governance docs G-01..G-11
    target_docs = doc_ids if doc_ids else [f"G-{str(i).zfill(2)}" for i in range(1, 12)]

    adopted_in_scope = [d for d in target_docs if adopted_map.get(d, {}).get("status") == "ADOPTED"]
    to_process = []

    for doc_id in target_docs:
        if adopted_map.get(doc_id, {}).get("status") == "ADOPTED":
            continue
        try:
            val_rows = (db.table("doc_validations").select("status")
                        .eq("document_id", doc_id).order("validated_at", desc=True).limit(1).execute())
            val_st = val_rows.data[0]["status"] if val_rows.data else None
        except Exception:
            val_st = None
        run = die.get_latest_run(doc_id)
        run_st = run.get("status") if run else None

        if val_st == "RESOLVED" or run_st == "ADOPTION_PROPOSAL":
            state, cmd = "PRÊT à adopter", f"adopte {doc_id}"
        elif val_st == "ESCALATED" or run_st == "ESCALATED":
            state, cmd = "ESCALATED", f"améliore {doc_id}"
        elif val_st:
            state, cmd = f"Validation {val_st}", None
        else:
            state, cmd = "Non validé", f"valide {doc_id}"
        to_process.append((doc_id, state, cmd))

    SEP = "\n───────────────────"
    lines = [
        f"Audit organisationnel — {_today()}",
        f"\nScope : {len(target_docs)} document(s) — D0 read-only",
        SEP,
        f"\nAdoptés ({len(adopted_in_scope)}/{len(target_docs)}) :",
        _doc_list(adopted_in_scope) if adopted_in_scope else "• Aucun",
    ]

    if to_process:
        lines += [f"\nÀ traiter ({len(to_process)}) :"]
        for doc_id, state, cmd in to_process[:8]:
            lines.append(f"• {doc_id} — {state}")
            if cmd:
                lines.append(f"  → {cmd}")

    if comp_score is not None:
        lines += [SEP, f"\nConformité : {comp_score}%", f"Gaps : {gap_codes}"]

    lines.append("\n✓ Analyse read-only — aucune modification effectuée.")
    return "\n".join(lines)


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

_HAIKU_SYSTEM = """Classifie ce message CEO parmi ces 11 intentions exactes :

ORGANIZATION_STATUS — état global de l'organisation
ORGANIZATION_BLOCKERS — blocages, freins, obstacles
FOOTBALLIQ_READINESS — readiness pour lancer FootballIQ
EXECUTIVE_ADVICE — recommandation, priorité, que faire maintenant
DOCUMENT_AUDIT — relire, comparer, auditer des documents
DOCUMENT_STATUS — statut d'un document spécifique
VALIDATION_REQUEST — valider un document
ADOPTION_REQUEST — adopter un document
COMPLIANCE_CHECK — conformité d'un document
IMPROVEMENT_REQUEST — améliorer ou corriger un document
UNKNOWN — aucune intention claire

Retourne UNIQUEMENT un JSON valide sans markdown :
{"intent": "ORGANIZATION_STATUS", "confidence": 0.85, "doc_ids": [], "reason": "..."}

confidence entre 0.0 et 1.0. doc_ids : liste des identifiants de documents (ex: ["G-07"]) ou [].
IMPORTANT : une question explicative ("explique", "pourquoi", "comment") sur un WP ou doc → DOCUMENT_STATUS (jamais DOCUMENT_AUDIT)."""


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
        msg_lower = message.lower()

        # ── Pre-classification A: WP explanation (ECT-01) ──────────────────────
        # "Explique-moi pourquoi WP-xxx nécessite..." → explain, never create WP
        wp_ids_in_msg = _extract_wp_ids(message)
        if wp_ids_in_msg and any(k in msg_lower for k in _QUESTION_MODE_KW):
            response = await _wf_explain_wp(wp_ids_in_msg[0])
            logger.info(f"CE pre-class=EXPLAIN_WP wp={wp_ids_in_msg[0]}")
            return {"intent": "EXPLAIN_WP", "confidence": 1.0, "response": response,
                    "source": "deterministic", "doc_ids": []}

        # ── Pre-classification B: executive advice (ECT-03, ECT-07) ───────────
        if any(k in msg_lower for k in _ADVICE_INTENT_KW):
            response = await _wf_executive_advice()
            logger.info("CE pre-class=EXECUTIVE_ADVICE")
            return {"intent": "EXECUTIVE_ADVICE", "confidence": 1.0, "response": response,
                    "source": "deterministic", "doc_ids": []}

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

        # ── Dispatch ────────────────────────────────────────────────────────────
        try:
            if intent == "ORGANIZATION_STATUS":
                response = await _wf_org_status()
            elif intent == "ORGANIZATION_BLOCKERS":
                response = await _wf_org_blockers()
            elif intent == "FOOTBALLIQ_READINESS":
                response = await _wf_footballiq()
            elif intent == "EXECUTIVE_ADVICE":
                response = await _wf_executive_advice()
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
