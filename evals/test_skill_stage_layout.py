"""Keep progressive disclosure explicit and complete for local and remote skills."""
import json
from pathlib import Path
import re

from skill_contract import read_contract

ROOT = Path(__file__).resolve().parents[1]


def test_every_stage_reference_is_routed_and_stage_vocabulary_is_reachable():
    definitions = json.loads((ROOT / 'skills/references/workflows.json').read_text())['skills']
    for skill, definition in definitions.items():
        entry = ROOT / 'skills' / skill / 'SKILL.md'
        text = entry.read_text()
        routes = re.findall(r'\]\((references/stages/[a-z-]+\.md)\)', text)
        assert routes
        assert {entry.parent / route for route in routes} == set((entry.parent / 'references/stages').glob('*.md'))
        assert 'loading each linked reference before its affected work' in text
        assert 'skill-workflow-observability.md' in text
        assert len(text) < len(read_contract(entry)) / 2
        for stage in definition['stages']:
            assert f'`{stage["id"]}`' in text
            for predecessor in stage.get('after', []):
                assert predecessor in {s['id'] for s in definition['stages']}


def test_stage_cleanup_preserves_canonical_and_plugin_contracts():
    for skill in ('otel-audit', 'otel-instrument', 'otel-verify'):
        assert read_contract(ROOT / 'skills' / skill / 'SKILL.md') == read_contract(ROOT / 'plugins/obstudio/skills' / skill / 'SKILL.md')
