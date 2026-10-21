/** Exercise Vite's actual proxy routing with a synthetic local auth backend. */
import assert from 'node:assert/strict';
import { createServer as createHttpServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const calls = [];
const backend = createHttpServer((request, response) => {
  calls.push({ url: request.url, host: request.headers.host });
  const url = new URL(request.url, `http://${request.headers.host}`);
  url.searchParams.delete('userid');
  url.searchParams.delete('token');
  response.writeHead(307, {
    Location: url.href,
    'Set-Cookie': 'jtb_sv_username=test-user; HttpOnly; Path=/',
  });
  response.end();
});
await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve));
let vite;
try {
  vite = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    logLevel: 'error', server: { host: '127.0.0.1', port: 0 },
  });
  for (const proxy of Object.values(vite.config.server.proxy)) {
    proxy.target = `http://127.0.0.1:${backend.address().port}`;
  }
  await vite.listen();
  const origin = `http://127.0.0.1:${vite.httpServer.address().port}`;
  for (const path of [
    '/?userid=synthetic-user&token=synthetic-token&appid=9086',
    '/?accept_language=zh-CN&appid=9086&userid=synthetic-user&token=synthetic-token',
    '/review/test?token=synthetic-token&userid=synthetic-user',
    '/?userid=synthetic-user',
  ]) {
    const response = await fetch(origin + path, { redirect: 'manual' });
    assert.equal(response.status, 307, `OA callback must reach backend: ${path}`);
    assert.ok(response.headers.get('set-cookie')?.includes('jtb_sv_username'));
    assert.equal(new URL(response.headers.get('location')).origin, origin);
    assert.equal(calls.at(-1).url, path);
    assert.equal(calls.at(-1).host, new URL(origin).host, 'Preserve the published Vite port');
    assert.ok(!response.headers.get('location').includes('synthetic-token'));
  }
  const callbackCount = calls.length;
  const normal = await fetch(origin + '/?accept_language=zh-CN&appid=9086');
  assert.equal(normal.status, 200);
  assert.match(await normal.text(), /@vite\/client/);
  assert.equal(calls.length, callbackCount, 'Ordinary pages must keep Vite hot reload');
  console.log('Vite OA callback proxy checks passed');
} finally {
  if (vite) await vite.close();
  await new Promise(resolve => backend.close(resolve));
}
