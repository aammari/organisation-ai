from app.database import get_supabase


def load_backlog_context() -> str:
    try:
        db = get_supabase()
        rows = (
            db.table("work_packages")
            .select("id,title,status,context_snapshot")
            .like("id", "BT-%")
            .order("id")
            .execute()
        )
        if not rows.data:
            return ""
        lines = ["# BACKLOG ITEMS\n"]
        for row in rows.data:
            snap = row.get("context_snapshot") or {}
            desc = snap.get("description", "")
            priority = snap.get("priority", "P2")
            lines.append(
                f"- [{row['id']}] {row['title']} "
                f"| status={row['status']} | priority={priority}"
            )
            if desc:
                lines.append(f"  {desc}")
        return "\n".join(lines)
    except Exception:
        return ""
