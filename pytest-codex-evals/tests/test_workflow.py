import hashlib
import json
import shlex
import sys
from pathlib import Path

from pytest_codex_evals.definitions import SanityCheck
from pytest_codex_evals.graders.sanity import run_check
from pytest_codex_evals.schema_resources import schema_validator
from pytest_codex_evals.trace import TraceSummary


def journal_fixture(root):
    artifact = root / 'result.json'
    artifact.write_text('{"real":"artifact"}')
    path = root / '.observe/skill-runs/example.json'
    path.parent.mkdir(parents=True)
    run = {'schemaVersion': 1, 'skill': 'sample', 'status': 'passed', 'finishedAt': '2026-10-15T00:01:00Z',
           'events': [{'stage': 'inputs', 'status': 'passed', 'branch': 'canonical', 'source': 'checkpoint'},
                      {'stage': 'build', 'status': 'passed', 'branch': 'go', 'source': 'executed', 'exitCode': 0,
                       'durationMs': 1.0, 'evidence': [{'path': 'result.json', 'sha256': 'sha256:' + hashlib.sha256(artifact.read_bytes()).hexdigest()}]}]}
    path.write_text(json.dumps(run))
    command = shlex.join([sys.executable, '/bundle/scripts/skill_workflow.py', 'execute', '--run', str(path), '--stage', 'build', '--', 'go', 'test', './...'])
    trace = TraceSummary([{'type': 'item.completed', 'item': {'type': 'command_execution', 'command': command, 'exit_code': 0, 'status': 'completed'}}], '')
    check = SanityCheck(id='path', description='Validate workflow path', kind='skill_workflow', workflow_skill='sample',
                        required_stages=['inputs', 'build'], before=[['inputs', 'build']], forbidden_branches=['build=python'],
                        executed_stages=['build'], evidence_paths=['result.json'])
    return path, run, check, trace


def test_path_uses_independent_artifact_and_command_evidence(tmp_path):
    path, run, check, trace = journal_fixture(tmp_path)
    assert run_check(check, tmp_path, '', trace).passed
    command = trace.actions[0].input['command']
    trace.actions[0].input['command'] = shlex.join(['/bin/zsh', '-lc', command])
    assert run_check(check, tmp_path, '', trace).passed
    assert not run_check(check, tmp_path, '', TraceSummary([], '')).passed
    trace.actions[0].input['command'] = 'echo ' + trace.actions[0].input['command']
    assert not run_check(check, tmp_path, '', trace).passed
    (tmp_path / 'result.json').write_text('changed')
    assert not run_check(check, tmp_path, '', trace).passed
    # One failed check leaves the old checker and later checks usable.
    legacy = SanityCheck(id='existing', description='Existing path', kind='file_exists', path='result.json')
    assert run_check(legacy, tmp_path, '').passed


def test_missing_partial_forbidden_order_and_ambiguous_paths_fail(tmp_path):
    path, run, check, trace = journal_fixture(tmp_path)
    original = json.loads(json.dumps(run))
    for mutate in [lambda r: r.update(status='partial'), lambda r: r.update(finishedAt=None),
                   lambda r: r['events'].reverse(), lambda r: r['events'][1].update(branch='python'),
                   lambda r: r['events'].pop()]:
        run = json.loads(json.dumps(original)); mutate(run); path.write_text(json.dumps(run))
        assert not run_check(check, tmp_path, '', trace).passed
    path.write_text(json.dumps(original))
    path.with_name('another.json').write_text(json.dumps(original))
    assert not run_check(check, tmp_path, '', trace).passed


def test_paths_and_invalid_input_are_confined_to_fixture(tmp_path):
    path, run, check, trace = journal_fixture(tmp_path)
    for pattern in ['../outside/*.json', '/tmp/*.json', 'missing/*.json']:
        assert not run_check(check.model_copy(update={'path': pattern}), tmp_path, '', trace).passed
    path.write_text('[]')
    assert not run_check(check, tmp_path, '', trace).passed
    path.unlink();path.symlink_to(tmp_path / 'outside')
    assert not run_check(check, tmp_path, '', trace).passed


def test_new_and_existing_sanity_schemas_validate():
    for check in [dict(id='legacy', description='Existing', kind='file_exists', path='result.json'),
                  dict(id='stages', description='Path', kind='skill_workflow', workflow_skill='sample', required_stages=['inputs'],
                       before=[['inputs', 'report']], forbidden_branches=['inputs=stale'], evidence_paths=['result.json'])]:
        schema_validator('sanity.schema.json').validate({'skill': 'sample', 'prompts': [{'id': 'run', 'task': 'Run'}], 'checks': [check]})
        assert SanityCheck(**check).kind == check['kind']
