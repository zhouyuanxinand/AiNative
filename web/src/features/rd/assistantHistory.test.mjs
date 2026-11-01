import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('./assistantHistory.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { mergeAssistantHistory } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

const sequences = (start, end) => Array.from({ length: end - start + 1 }, (_, index) => start + index);
const message = seq => ({ id: `message-${seq}`, seq, role: 'assistant', content: `record ${seq}`, created_at: '2026-10-30T00:00:00Z', mode: 'local_guidance', input_revision: 1, answered_version: 1, stale: false });
function serverPage(all, before) {
  const eligible = all.filter(seq => before === undefined || seq < before);
  const rows = eligible.slice(-20);
  return { messages: rows.map(message), suggestions: [], context: { stage: 'input', project_version: 1, input_revision: 1 }, history: { total: all.length, limit: 20, has_more: eligible.length > 20, next_before: eligible.length > 20 ? rows[0] : null } };
}
function readRemaining(history, all) {
  for (let requests = 0; history.history.has_more; requests++) {
    assert(requests < 20, 'history pagination must make bounded progress');
    assert.notEqual(history.history.next_before, null);
    history = mergeAssistantHistory(history, serverPage(all, history.history.next_before), true);
  }
  assert.deepEqual(history.messages.map(row => row.seq), all);
  assert.equal(history.history.next_before, null);
  return history;
}

test('another tab can create a gap after a previously complete 20-message history', () => {
  const previous = serverPage(sequences(1, 20));
  const all = sequences(1, 42);
  const merged = mergeAssistantHistory(previous, serverPage(all));
  assert.equal(merged.messages.length, 40);
  assert.equal(merged.history.has_more, true);
  assert.equal(merged.history.next_before, 23, 'load before the new window to recover 21 and 22');
  assert.equal(readRemaining(merged, all).messages.length, 42);
});

test('filling a newer gap still leaves the earlier prefix reachable', () => {
  const original = sequences(1, 100);
  const previous = mergeAssistantHistory(serverPage(original), serverPage(original, 81), true);
  assert.equal(previous.history.next_before, 61);
  const all = sequences(1, 122);
  const merged = mergeAssistantHistory(previous, serverPage(all));
  assert.equal(merged.history.next_before, 103, 'fill the disjoint latest window before returning to earlier history');
  readRemaining(merged, all);
});

test('overlapping refresh preserves the earlier cursor, and fully loaded history needs no extra page', () => {
  const original = sequences(1, 100);
  const previous = mergeAssistantHistory(serverPage(original), serverPage(original, 81), true);
  const all = sequences(1, 102);
  const merged = mergeAssistantHistory(previous, serverPage(all));
  assert.equal(merged.history.next_before, 61);
  readRemaining(merged, all);
  const complete = mergeAssistantHistory(serverPage(sequences(1, 20)), serverPage(sequences(1, 22)));
  assert.equal(complete.messages.length, 22);
  assert.equal(complete.history.has_more, false);
});

test('sequence gaps belonging to other scopes do not imply missing current-case messages', () => {
  const own = sequences(1, 42).map(seq => seq * 3);
  const previous = serverPage(own.slice(0, 20));
  const merged = mergeAssistantHistory(previous, serverPage(own));
  assert.equal(merged.history.next_before, 69);
  readRemaining(merged, own);
});

test('a stale disjoint older response cannot erase the prefix cursor of a newer loaded page', () => {
  const previous = serverPage(sequences(1, 100));
  const merged = mergeAssistantHistory(previous, serverPage(sequences(1, 20)));
  assert.equal(merged.history.has_more, true);
  assert.equal(merged.history.next_before, 81);
  readRemaining(merged, sequences(1, 100));
});
