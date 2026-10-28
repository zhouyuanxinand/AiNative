import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

// Exercise the real Vite adapter, including TypeScript constructs Node's
// strip-only loader does not transform in transitive API dependencies.
const bundled = await build({ entryPoints: ['src/features/taskbook/api/jobs.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
const { clarifyIndicators } = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);

test('manual clarification retry retains the request key and successful response completes the intent', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, ...init });
    if (calls.length === 1) throw new TypeError('network result unknown');
    return new Response(JSON.stringify({ jid: 'child', parent_jid: 'parent' }), { status: 200 });
  };
  try {
    const values = { 接触电阻: '条件：常温' };
    await assert.rejects(clarifyIndicators('parent', values), /unknown/);
    assert.equal(calls.length, 1, 'failed requests must wait for a manual retry');
    await clarifyIndicators('parent', values);
    const key = calls[0].headers['Idempotency-Key'];
    assert.ok(key);
    assert.equal(calls[1].headers['Idempotency-Key'], key);
    await clarifyIndicators('parent', values);
    assert.notEqual(calls[2].headers['Idempotency-Key'], key);
  } finally { globalThis.fetch = original; }
});

test('changed clarification content creates a new intent while returning to retained input reuses its key', async () => {
  const original = globalThis.fetch;
  const keys = [];
  globalThis.fetch = async (_url, init) => {
    keys.push(init.headers['Idempotency-Key']);
    throw new TypeError('network result unknown');
  };
  try {
    await assert.rejects(clarifyIndicators('other-parent', { A: '条件：常温', B: '档位：一档' }));
    await assert.rejects(clarifyIndicators('other-parent', { A: '条件：低温', B: '档位：一档' }));
    await assert.rejects(clarifyIndicators('other-parent', { B: '档位：一档', A: '条件：常温' }));
    assert.ok(keys[0]);
    assert.notEqual(keys[1], keys[0]);
    assert.equal(keys[2], keys[0]);
  } finally { globalThis.fetch = original; }
});
