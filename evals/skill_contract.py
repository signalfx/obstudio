"""Read the mandatory stage references declared by a skill's entry point."""
from pathlib import Path
import re


def read_contract(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name != "SKILL.md":
        return text
    links = re.findall(r"\]\((references/stages/[a-z-]+\.md)\)", text)
    if len(links) != len(set(links)):
        raise AssertionError("Duplicate stage route")
    return text + "\n" + "\n".join(
        (path.parent / target).read_text(encoding="utf-8") for target in links
    )
