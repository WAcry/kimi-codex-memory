// Kimi's own Node runtime runs this file for both standalone and npm installations.
import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const mode = process.argv[2] || 'hook';
const allowed = new Set(['hook', 'status', 'doctor', 'render', 'worker', 'note', 'update']);
if (!allowed.has(mode)) throw new Error('Unknown memory command');
const env = {...process.env, PYTHONUTF8: '1'};
if (!/^(node|electron)(.exe)?$/i.test(basename(process.execPath))) {
  env.KIMI_MEMORY_HOST_EXECUTABLE = process.execPath;
}
const platform = `${process.platform}-${process.arch}`;
const binaryName = process.platform === 'win32' ? 'kimi-codex-memory.exe' : 'kimi-codex-memory';
let binary = join(root, 'runtime', platform, 'kimi-codex-memory', binaryName);
let args = process.argv.slice(2);
if (!existsSync(binary)) {
  // Only developer-generated plugins contain this file; release plugins are self-contained.
  const devConfig = join(root, 'development.json');
  if (existsSync(devConfig)) {
    const config = JSON.parse(readFileSync(devConfig, 'utf8'));
    binary = config.python;
    env.PYTHONPATH = join(root, 'python');
    env.KIMI_MEMORY_HOME = config.home;
    args = ['-m', 'kimi_memory', ...args];
  } else {
    if (mode === 'hook') {
      process.stdout.write('{}\n');
      process.exit(0);
    }
    process.stderr.write('Install the release plugin from /plugins marketplace, not the source archive.\n');
    process.exit(1);
  }
}
const child = spawn(binary, args.length ? args : ['hook'], {
  cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
});
process.stdin.pipe(child.stdin);
child.stdin.on('error', () => {});
child.stdout.pipe(process.stdout);
child.stderr.pipe(process.stderr);
child.on('error', () => {
  if (mode === 'hook') process.stdout.write('{}\n');
  process.exitCode = mode === 'hook' ? 0 : 1;
});
child.on('close', code => { process.exitCode = mode === 'hook' ? 0 : (code ?? 1); });
