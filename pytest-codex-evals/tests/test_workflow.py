import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_codex_evals.backends import _parse_claude_trace
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
    trace.actions[0].status = 'failed'
    assert not run_check(check, tmp_path, '', trace).passed
    trace.actions[0].status = 'completed'
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


def test_shell_control_operators_cannot_mask_recorder_failure(tmp_path):
    path, run, check, trace = journal_fixture(tmp_path)
    command = trace.actions[0].input['command']
    for suffix in ['|true', ' | true', '||true', ' || true', ';true', '&&true', '>capture']:
        for candidate in [command + suffix, shlex.join(['/bin/zsh', '-lc', command + suffix])]:
            trace.actions[0].input['command'] = candidate
            assert not run_check(check, tmp_path, '', trace).passed, candidate
    for argument in ['|', 'literal|value', '&&', 'semi;colon']:
        trace.actions[0].input['command'] = command + ' ' + shlex.quote(argument)
        assert run_check(check, tmp_path, '', trace).passed
    trace.actions[0].input['command'] = command.replace(' -- go', ' --stage report -- go')
    assert not run_check(check, tmp_path, '', trace).passed


def test_invalid_durations_fail_without_aborting_later_checks(tmp_path):
    path, run, check, trace = journal_fixture(tmp_path)
    run['events'][1]['exitCode'] = False
    path.write_text(json.dumps(run))
    assert not run_check(check, tmp_path, '', trace).passed
    run['events'][1]['exitCode'] = 0
    for duration in [10**400, True, -1, float('inf'), float('nan')]:
        run['events'][1]['durationMs'] = duration
        path.write_text(json.dumps(run))
        assert not run_check(check, tmp_path, '', trace).passed
        legacy = SanityCheck(id='later', description='Later check', kind='file_exists', path='result.json')
        assert run_check(legacy, tmp_path, '').passed


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX shell pipeline regression')
def test_actual_failed_command_hidden_by_successful_pipeline_is_rejected(tmp_path):
    path, run, check, trace = journal_fixture(tmp_path)
    script = tmp_path / 'skill_workflow.py'
    script.write_text('import sys\nsys.exit(7)\n')
    recorder = shlex.join([sys.executable, str(script), 'execute', '--run', str(path), '--stage', 'build', '--', 'false'])
    assert subprocess.run(shlex.split(recorder), check=False).returncode == 7
    pipeline = recorder + '|true'
    outcome = subprocess.run(pipeline, shell=True, check=False)
    assert outcome.returncode == 0
    trace.actions[0].input['command'] = pipeline
    trace.actions[0].exit_code = outcome.returncode
    assert not run_check(check, tmp_path, '', trace).passed


def test_claude_command_witness_success_failure_and_unknown(tmp_path):
    path, run, check, codex_trace = journal_fixture(tmp_path)
    command = codex_trace.actions[0].input['command']
    for label, result_fields, detail, expected, code in [
        ('success', {'is_error': False}, {}, True, 0),
        ('explicit success', {}, {'exit_code': 0}, True, 0),
        ('failed', {'is_error': True}, {'exit_code': 7}, False, 7),
        ('missing outcome', {}, {}, False, None),
        ('background', {'is_error': False}, {'backgroundTaskId': 'task-1'}, False, None),
        ('interrupted', {'is_error': False}, {'interrupted': True}, False, None),
        ('inconsistent outcome', {'is_error': True}, {'exit_code': 0}, False, None),
        ('invalid exit code', {'is_error': False}, {'exit_code': 'invalid'}, False, None),
    ]:
        events = [
            {'type': 'tool_use', 'id': 'command-1', 'name': 'Bash', 'input': {'command': command}},
            {'type': 'tool_result', 'tool_use_id': 'command-1', 'content': 'tool result', 'tool_use_result': detail, **result_fields},
        ]
        trace_path = tmp_path / 'claude.jsonl'
        trace_path.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
        trace = _parse_claude_trace(trace_path)
        assert trace.actions[0].exit_code == code, label
        assert run_check(check, tmp_path, '', trace).passed is expected, label
    assert run_check(check, tmp_path, '', codex_trace).passed
