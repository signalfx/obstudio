import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));
export default class HarnessProvider {
  id() { return 'obstudio:existing-codex-cli'; }
  async callApi(prompt) {
    if (!process.env.PILOT_RUN_DIR) throw new Error('Use npm run eval to allocate a fresh run');
    const { stdout } = await promisify(execFile)('uv', [
      'run', '--project', path.join(directory, '..'), '--locked', 'python',
      path.join(directory, 'adapter.py'), '--prompt', prompt,
      '--output', process.env.PILOT_RUN_DIR,
    ], { timeout: 2_300_000, maxBuffer: 4 * 1024 * 1024 });
    const result = JSON.parse(stdout);
    return { output: JSON.stringify(result), metadata: { artifactDirectory: process.env.PILOT_RUN_DIR } };
  }
}
