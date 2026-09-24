// The token lifecycle below is vendored verbatim from the pinned Kimi source.
import { join, resolve } from 'node:path';
import { OAuthManager } from '../vendor/kimi-oauth/oauth-manager';
import { FileTokenStorage } from '../vendor/kimi-oauth/storage';
import { KIMI_CODE_FLOW_CONFIG } from '../vendor/kimi-oauth/constants';
import { createKimiDefaultHeaders } from '../vendor/kimi-oauth/identity';

async function main() {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 65536) throw new Error('Input too large');
  }
  const request = JSON.parse(input);
  const home = resolve(request.home);
  const headers = createKimiDefaultHeaders({
    homeDir: home, productName: 'kimi-codex-memory', version: request.version,
    platform: 'kimi_code_cli', userAgentSuffix: 'Kimi Code memory plugin',
  });
  if (request.operation === 'headers') {
    process.stdout.write(JSON.stringify({headers}));
    return;
  }
  const key = request.key;
  const name = key === 'oauth/kimi-code' || key === 'kimi-code'
    ? 'kimi-code' : key.startsWith('oauth/') ? key.slice(6) : key;
  if (!/^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}$/.test(name)) throw new Error('Invalid token key');
  const host = new URL(request.oauth_host || KIMI_CODE_FLOW_CONFIG.oauthHost);
  if (host.username || host.password || host.search || host.hash ||
      (host.protocol !== 'https:' && !['127.0.0.1', '[::1]', 'localhost'].includes(host.hostname))) {
    throw new Error('Unsafe OAuth endpoint');
  }
  // The upstream transport is reused, but credential redirects are never permitted.
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url, init) => originalFetch(url, {...init, redirect: 'error'});
  const manager = new OAuthManager({
    config: {...KIMI_CODE_FLOW_CONFIG, name, oauthHost: host.href.endsWith('/') ? host.href.slice(0, -1) : host.href},
    storage: new FileTokenStorage(join(home, 'credentials')),
    configDir: home, deviceHeaders: () => headers,
  });
  const access_token = await manager.ensureFresh({force: request.force === true});
  process.stdout.write(JSON.stringify({access_token, headers}));
}
main().catch(() => {
  // Upstream errors can contain provider response bodies; never forward them.
  process.stdout.write(JSON.stringify({error: 'Kimi authentication unavailable'}));
  process.exitCode = 1;
});
