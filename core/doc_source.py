"""
Canonical document source — GitHub is the single source of truth.
All document content must be fetched from the repository; no local cache,
no Supabase copy, no in-memory fallback is authorised.
"""

import base64
import hashlib
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "aammari/organisation-ai")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# ── Canonical path mapping ─────────────────────────────────────────────────
# Each doc_id maps to its unique location in the repository.
# Add new families here as documents are created.
DOC_PATHS: dict[str, str] = {
    # Governance
    "G-01": "docs/governance/G-01.md",
    "G-02": "docs/governance/G-02.md",
    "G-03": "docs/governance/G-03.md",
    "G-04": "docs/governance/G-04.md",
    "G-05": "docs/governance/G-05.md",
    "G-06": "docs/governance/G-06.md",
    "G-07": "docs/governance/G-07.md",
    "G-08": "docs/governance/G-08.md",
    "G-09": "docs/governance/G-09.md",
    "G-10": "docs/governance/G-10.md",
    "G-11": "docs/governance/G-11.md",
    # Architecture — to be created before validation
    "A-01": "docs/architecture/A-01.md",
    "A-02": "docs/architecture/A-02.md",
    "A-03": "docs/architecture/A-03.md",
    "A-04": "docs/architecture/A-04.md",
    "A-05": "docs/architecture/A-05.md",
    # Product — to be created before validation
    "P-01": "docs/product/P-01.md",
    "P-02": "docs/product/P-02.md",
    "P-03": "docs/product/P-03.md",
    # Future — to be created before validation
    "F-01": "docs/future/F-01.md",
    "F-02": "docs/future/F-02.md",
}

FAMILIES = {
    "G": [k for k in DOC_PATHS if k.startswith("G-")],
    "A": [k for k in DOC_PATHS if k.startswith("A-")],
    "P": [k for k in DOC_PATHS if k.startswith("P-")],
    "F": [k for k in DOC_PATHS if k.startswith("F-")],
}


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _extract_version(content: str) -> str:
    m = re.search(r"\*\*Version\*\*\s*[:：]\s*([\d.]+)", content)
    if m:
        return m.group(1)
    m = re.search(r"v([\d.]+)", content[:200])
    return m.group(1) if m else "1.0"


def _github_headers() -> dict:
    if GITHUB_TOKEN:
        return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    return {"Accept": "application/vnd.github.v3+json"}


async def fetch_doc(doc_id: str) -> dict:
    """
    Fetch a document from GitHub.  Returns a result dict with keys:
      status  — OK | UNKNOWN_DOC | MISSING_DOCUMENTS | UPLOAD_FAILED
      doc_id, path, content, doc_sha, commit_sha, version  (when OK)
    """
    path = DOC_PATHS.get(doc_id)
    if not path:
        return {"status": "UNKNOWN_DOC", "doc_id": doc_id}

    url = (
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
        f"?ref={GITHUB_BRANCH}"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=_github_headers())
    except Exception as e:
        logger.error(f"fetch_doc {doc_id}: network error {e}")
        return {"status": "UPLOAD_FAILED", "doc_id": doc_id, "error": str(e)}

    if r.status_code == 404:
        return {
            "status": "MISSING_DOCUMENTS",
            "doc_id": doc_id,
            "path": path,
        }
    if r.status_code != 200:
        return {
            "status": "UPLOAD_FAILED",
            "doc_id": doc_id,
            "path": path,
            "error": f"HTTP {r.status_code}",
        }

    data = r.json()
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
    except Exception as e:
        return {"status": "UPLOAD_FAILED", "doc_id": doc_id, "error": f"decode error: {e}"}

    if not content.strip():
        return {"status": "UPLOAD_FAILED", "doc_id": doc_id, "error": "empty content"}

    return {
        "status": "OK",
        "doc_id": doc_id,
        "path": path,
        "content": content,
        "doc_sha": _sha256(content),
        "commit_sha": data.get("sha", ""),
        "version": _extract_version(content),
    }


async def check_exists(doc_id: str) -> dict:
    """Lightweight existence check — does not download content body."""
    path = DOC_PATHS.get(doc_id)
    if not path:
        return {"doc_id": doc_id, "status": "UNKNOWN_DOC", "path": None}

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.head(url, headers=_github_headers())
        # GitHub returns 302 for HEAD on contents; use GET with minimal fields instead
        if r.status_code in (302, 405):
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url, headers={**_github_headers(), "Range": "bytes=0-0"})
    except Exception as e:
        return {"doc_id": doc_id, "status": "UPLOAD_FAILED", "path": path, "error": str(e)}

    ok = r.status_code in (200, 206)
    return {
        "doc_id": doc_id,
        "status": "OK" if ok else "MISSING_DOCUMENTS",
        "path": path,
    }


async def batch_preflight(doc_ids: list[str]) -> dict:
    """
    Check all doc_ids for GitHub presence.
    Returns {"status": "READY"|"MISSING_DOCUMENTS", "ready": [...], "missing": [...]}
    """
    import asyncio
    results = await asyncio.gather(*[check_exists(d) for d in doc_ids])
    ready = [r for r in results if r["status"] == "OK"]
    missing = [r for r in results if r["status"] != "OK"]
    return {
        "status": "READY" if not missing else "MISSING_DOCUMENTS",
        "ready": ready,
        "missing": missing,
        "total": len(results),
    }
