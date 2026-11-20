import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const args = process.argv.slice(2);
if (args.length !== 2 || args[0] !== '--base') throw new Error('Usage: npm run eval -- --base <git-ref>');
const selection = spawnSync('python3', [path.join(here, 'routing.py'), '--base', args[1]], { encoding: 'utf8' });
if (selection.status !== 0) throw new Error(selection.stderr || 'Selection failed');
const selected = JSON.parse(selection.stdout);
console.log(selection.stdout);
if (selected.selected.length === 0) process.exit(0); // Explicit skip; never emits a model pass.
const directory = path.join(root, '.workspace/promptfoo', randomUUID());
mkdirSync(directory, { recursive: true });
writeFileSync(path.join(directory, 'selection.json'), selection.stdout);
console.log(`Raw output: ${directory}`);
const result = spawnSync(path.join(here, 'node_modules/.bin/promptfoo'), [
  'eval', '--config', path.join(here, 'promptfooconfig.yaml'), '--repeat', '1',
  '--no-cache', '--no-share', '--no-progress-bar', '--no-table',
  '--output', path.join(directory, 'promptfoo.json'),
], { cwd: here, stdio: 'inherit', env: {
  ...process.env, PILOT_RUN_DIR: path.join(directory, 'evidence'),
  PROMPTFOO_CONFIG_DIR: path.join(directory, 'viewer'),
  PROMPTFOO_CACHE_ENABLED: 'false', PROMPTFOO_DISABLE_TELEMETRY: '1',
  PROMPTFOO_DISABLE_UPDATE: '1',
} });
if (result.status !== 0) process.exit(result.status || 1);
// A successful CLI exit is insufficient: check the exported run and evidence again.
const verified = spawnSync('uv', ['run', '--project', path.join(root, 'evals'), '--locked',
  'python', path.join(here, 'report.py'), '--check-run', directory], { stdio: 'inherit' });
process.exit(verified.status ?? 1);
