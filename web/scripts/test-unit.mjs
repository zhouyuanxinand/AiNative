// Resolve the test set independently of the caller's working directory/shell globbing.
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const web = fileURLToPath(new URL('../', import.meta.url));
const directory = fileURLToPath(new URL('../tests/unit/', import.meta.url));
const tests = readdirSync(directory).filter(name => name.endsWith('.test.mjs')).sort();
if (!tests.length) throw new Error('No frontend unit tests found');
const result = spawnSync(process.execPath, ['--experimental-strip-types', '--test', ...tests.map(name => `tests/unit/${name}`)], {
  cwd: web,
  stdio: 'inherit',
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
