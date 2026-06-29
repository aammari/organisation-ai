from pathlib import Path


def load_governance_context() -> str:
    context = []
    docs_path = Path("docs")

    for folder in ["governance", "architecture", "technical-design"]:
        folder_path = docs_path / folder
        if folder_path.exists():
            for f in sorted(folder_path.glob("*.md")):
                content = f.read_text()[:2000]
                context.append(f"# {f.stem}\n{content}")

    return "\n\n---\n\n".join(context)
