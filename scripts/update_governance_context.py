"""
Lit les documents de gouvernance G-01 à G-11 depuis docs/governance/
et met à jour le champ governance dans org_context Supabase.
"""
import os
import json
from pathlib import Path
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

DOCS_DIR = Path(__file__).parent.parent / "docs" / "governance"

GOVERNANCE_FILES = [
    ("G-01", "MeetingProtocol-G01-v1_0.md"),
    ("G-02", "DataRetention-G02-v1_0.md"),
    ("G-03", "AgentOnboarding-G03-v1_0.md"),
    ("G-04", "ConfigManagement-G04-v1_0.md"),
    ("G-05", "SecurityPolicy-G05-v1_0.md"),
    ("G-06", "CapabilityLifecycle-G06-v1_0.md"),
    ("G-07", "Glossary-G07-v1_0.md"),
    ("G-08", "ExceptionWaiver-G08-v1_0.md"),
    ("G-09", "AIEthics-G09-v1_0.md"),
    ("G-10", "OrgHealthReview-G10-v1_0.md"),
    ("G-11", "CEOCommunicationProtocol-G11-v1_1.md"),
]


def extract_summary(content: str, max_chars: int = 600) -> str:
    lines = content.split("\n")
    title = next((l for l in lines if l.startswith("# ")), "")
    rules = [l for l in lines if l.startswith("**G-") and "**" in l[3:]]
    summary_lines = [title] + rules[:5]
    return "\n".join(summary_lines)[:max_chars]


def main():
    db = create_client(SUPABASE_URL, SUPABASE_KEY)

    governance_index = {}
    for code, filename in GOVERNANCE_FILES:
        path = DOCS_DIR / filename
        if not path.exists():
            print(f"MISSING: {filename}")
            continue
        content = path.read_text()
        governance_index[code] = {
            "file": filename,
            "title": content.split("\n")[0].replace("# ", ""),
            "summary": extract_summary(content),
            "chars": len(content),
        }
        print(f"OK: {code} — {filename} ({len(content)} chars)")

    ctx_row = db.table("org_context").select("*").eq("id", "current").single().execute()
    existing = ctx_row.data or {}

    updated = {**existing, "governance": governance_index, "id": "current"}
    db.table("org_context").upsert(updated).execute()
    print(f"\norg_context updated — {len(governance_index)} governance docs indexed")
    print(json.dumps({k: v["title"] for k, v in governance_index.items()}, indent=2))


if __name__ == "__main__":
    main()
