from pathlib import Path
import re


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = SKILL_DIR.parent
SKILL = SKILL_DIR / "SKILL.md"
OFFLINE = SKILL_DIR / "references" / "offline-plan.md"
LIVE = SKILL_DIR / "references" / "live-publish.md"
NORMALIZATION = SKILLS_DIR / "references" / "terraform-normalization.md"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_entrypoint_is_a_bounded_safety_router() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert len(text.encode()) <= 10_000
    assert "## Always-Loaded Safety Contract" in text
    assert "## Reference Router" in text
    assert "Offline mode must not load" in text
    assert "references/offline-plan.md" in text
    assert "references/live-publish.md" in text
    normalized = " ".join(text.split())
    assert "Resolve paths in this entrypoint from the skill directory" in normalized
    assert "Inside a loaded reference" in normalized
    assert "from that reference's directory" in normalized


def test_offline_loaded_path_is_smaller_than_the_old_entrypoint() -> None:
    loaded_bytes = sum(
        len(path.read_bytes()) for path in (SKILL, OFFLINE, NORMALIZATION)
    )

    # The old monolithic entrypoint alone was 20,081 bytes. Keep the complete
    # ordinary offline route below it even after loading normalization details.
    assert loaded_bytes <= 19_000


def test_always_loaded_contract_keeps_mutation_safety_visible() -> None:
    text = _normalized(SKILL)

    for required in (
        "every remote mutation set",
        "explicit current yes/no confirmation",
        "fetches and reclassifies current state",
        "Create only rows currently classified `GAP`",
        "never create `UNCERTAIN`",
        "never updates or deletes detectors",
        "SPLUNK_ACCESS_TOKEN",
        "Never echo, log, print, persist",
        "never reads environment credentials",
        "skips only HTTP 500 pages",
        "409/duplicate",
        "non-empty `Reason`",
        '"tags": ["obstudio"]',
    ):
        assert required in text


def test_offline_reference_is_uncertain_non_mutating_and_self_contained() -> None:
    text = _normalized(OFFLINE)

    for required in (
        "never reads environment credentials",
        "never `COVERED` or `GAP`",
        "all local verdicts remain UNCERTAIN",
        "no network call or remote create/update/delete occurred",
        "cannot authorize later mutation",
        "later online run must re-fetch, reclassify",
        "Exact normalized programText",
        "POST /v2/detector",
        'literal `"tags": ["obstudio"]`',
        "AutoDetect detectors",
        "resolved notification value",
        "stop before confirmation",
    ):
        assert required in text

    assert "SPLUNK_ACCESS_TOKEN" not in text
    for forbidden_reference in (
        "references/live-publish.md",
        "references/coverage-model.md",
        "references/splunk-api.md",
        "references/coverage-decision-tree.md",
        "references/ledger-template.md",
    ):
        assert forbidden_reference not in text


def test_live_reference_preserves_fresh_idempotent_response_contract() -> None:
    text = _normalized(LIVE)

    for required in (
        "skip-on-500 pagination",
        "Only a successful empty list",
        "makes every affected local verdict UNCERTAIN",
        "explicit current yes/no",
        "confirmation authorizes one exact mutation set only",
        "A changed diff must be shown and confirmed again",
        "POST 200/201",
        "409/duplicate",
        "401/403 stops",
        "Create Confirmed GAPs Sequentially",
        "Never update/delete a detector",
        ".observe/detector-sync.md",
        "Never store the token",
        "unresolved notification expressions",
        'rule["notifications"]',
    ):
        assert required in text


def test_routed_references_resolve_inside_the_skill_catalog() -> None:
    for relative in (
        "references/offline-plan.md",
        "references/live-publish.md",
        "references/coverage-model.md",
        "../references/terraform-normalization.md",
        "../references/splunk-api.md",
        "../references/coverage-decision-tree.md",
        "../references/ledger-template.md",
    ):
        target = (SKILL_DIR / relative).resolve()
        assert target.is_file()
        assert target.is_relative_to(SKILLS_DIR.resolve())

    for owner in (OFFLINE, LIVE, SKILL_DIR / "references" / "coverage-model.md"):
        for relative in re.findall(r"`([^`]+\.md)`", owner.read_text()):
            if relative.startswith(".observe/"):
                continue
            target = (owner.parent / relative).resolve()
            assert target.is_file(), f"{owner} routes to missing {relative}"
            assert target.is_relative_to(SKILLS_DIR.resolve())
