import { build } from 'esbuild';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, dirname, relative } from 'node:path';
import { createHash } from 'node:crypto';

const root = resolve(process.env.KIMI_MEMORY_VENDOR_REQUESTER || 'vendor/kimi-requester/human');
const output = 'src/kimi_memory/native/model.mjs';
const result = await build({
  entryPoints:['bridge/model.ts'],bundle:true,platform:'node',target:'node22',format:'esm',
  outfile:output,minify:true,legalComments:'eof',metafile:true,nodePaths:[resolve('node_modules')],
  banner:{js:"import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"},
  plugins:[{name:'native-kimi-module-paths',setup(build) {
    build.onResolve({filter:/^#(?:native)?\//}, args => ({path:resolve(root,args.path.replace(/^#(?:native)?\//,'')) + '.ts'}));
  }}],
});
if (process.env.KIMI_MEMORY_BUILD_METADATA) {
  await writeFile(process.env.KIMI_MEMORY_BUILD_METADATA, JSON.stringify(result.metafile, null, 2));
}
if (process.env.KIMI_MEMORY_VENDOR_REQUESTER) {
  const records = [];
  for (const name of Object.keys(result.metafile.inputs).sort()) {
    const absolute = resolve(name);
    if (!absolute.startsWith(root + '/')) continue;
    const local = 'vendor/kimi-requester/human/' + relative(root,absolute);
    await mkdir(dirname(local),{recursive:true});
    await copyFile(absolute,local);
    records.push({path:local,upstream_path:'packages/agent-core-v2/src/human/' + relative(root,absolute),
      sha256:createHash('sha256').update(await readFile(absolute)).digest('hex')});
  }
  await writeFile('vendor/kimi-requester/files.json',JSON.stringify(records,null,2)+'\n');
}
const notices = [];
const packages = new Set(Object.keys(result.metafile.inputs).flatMap(name => {
  const relativeName = name.replaceAll('\\','/');
  const match = /(?:^|\/)node_modules\/((?:@[^/]+\/)?[^/]+)/.exec(relativeName);
  return match ? [match[1]] : [];
}));
for (const name of [...packages].sort()) {
  const base = 'node_modules/'+name+'/';
  const pkg = JSON.parse(await readFile(base+'package.json','utf8'));
  let license;
  for (const file of ['LICENSE','LICENSE.md','LICENSE.txt']) {
    try {license = await readFile(base+file,'utf8');break;} catch {}
  }
  if (!license && name === 'standardwebhooks') {
    license = await readFile('vendor/kimi-requester/licenses/standardwebhooks-LICENSE','utf8');
  }
  if (!license) throw new Error('Missing license: '+name);
  notices.push('===== '+name+'@'+pkg.version+' =====\n'+license);
}
await writeFile('src/kimi_memory/native/MODEL-THIRD-PARTY-NOTICES',notices.join('\n'));
