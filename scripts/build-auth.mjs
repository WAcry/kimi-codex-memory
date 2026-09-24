import { build } from 'esbuild';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
await mkdir('src/kimi_memory/native', {recursive:true});
await build({entryPoints:['bridge/auth.ts'], bundle:true, platform:'node', target:'node22',
  format:'esm', outfile:'src/kimi_memory/native/auth.mjs', legalComments:'eof',
  banner:{js:"import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"}});
await copyFile('vendor/kimi-oauth/LICENSE', 'src/kimi_memory/native/KIMI-LICENSE');
await copyFile('node_modules/proper-lockfile/LICENSE', 'src/kimi_memory/native/LOCKFILE-LICENSE');
const dependencies = ['proper-lockfile', 'graceful-fs', 'retry', 'signal-exit'];
let notices = '';
for (const name of dependencies) {
  const base = 'node_modules/' + name + '/';
  const pkg = JSON.parse(await readFile(base + 'package.json', 'utf8'));
  let license;
  for (const file of ['LICENSE', 'License', 'LICENSE.md', 'LICENSE.txt']) {
    try { license = await readFile(base + file, 'utf8'); break; } catch {}
  }
  if (!license) throw new Error('Missing bundled dependency license: ' + name);
  notices += '\n===== ' + name + '@' + pkg.version + ' =====\n' + license;
}
await writeFile('src/kimi_memory/native/THIRD-PARTY-NOTICES', notices);
