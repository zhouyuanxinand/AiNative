import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('./sourceUploadQueue.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
const module = { exports: {} };
new Function('require', 'module', 'exports', outputText)(require, module, module.exports);
const { emptySourceQueue, appendSourceFiles, applySourceSuggestions, moveSourceFile, choosePrimarySource, removeSourceFile, reconcileSourcePrimary, sourceQueueIssue, sourceBatchItems, createSourceBatchAttempt } = module.exports;
let sequence = 0;
const id = () => `q-${++sequence}`;
const file = (name, size = 10, lastModified = 1) => ({ name, size, lastModified, type: 'application/pdf' });
const add = (queue, files, existing = {}, role = 'unknown') => appendSourceFiles(queue, files, existing, id, role);
const suggest = (queue, entries, existing = {}) => applySourceSuggestions(queue, entries.map(([id, role]) => ({ id, role, reason: '文件名建议', method: 'filename' })), queue.items.map(item => item.id), existing);

test('collects files without uploading and leaves unclassified files pending', () => {
  const result = add(emptySourceQueue(), [file('需求.pdf'), file('未知.pdf')]);
  assert.equal(result.queue.items.length, 2);
  assert.equal(result.accepted.length, 2);
  assert.ok(result.queue.items.every(item => item.role === 'unknown' && item.classifying));
  assert.match(sourceQueueIssue(result.queue), /分类/);
});

test('filename suggestions select one primary per category and keep supplements in their original category', () => {
  let queue = add(emptySourceQueue(), [file('a.pdf'), file('b.pdf'), file('c.pdf')]).queue;
  const [a, b, c] = queue.items;
  queue = suggest(queue, [[a.id, 'tech'], [b.id, 'tech'], [c.id, 'spec']]);
  assert.equal(sourceQueueIssue(queue), '');
  assert.deepEqual(sourceBatchItems(queue).map(item => [item.role, item.primary]), [['tech', true], ['tech', false], ['spec', true]]);
});

test('existing primary inputs stay selected until the user explicitly replaces one', () => {
  const existing = { tech: 'existing-tech' };
  let queue = add(emptySourceQueue(existing), [file('new.pdf'), file('extra.pdf')], existing, 'tech').queue;
  assert.ok(sourceBatchItems(queue).every(item => !item.primary));
  queue = choosePrimarySource(queue, 'tech', queue.items[1].id, existing);
  assert.deepEqual(sourceBatchItems(queue).map(item => item.primary), [false, true]);
  queue = choosePrimarySource(queue, 'tech', 'existing', existing);
  assert.ok(sourceBatchItems(queue).every(item => !item.primary));
});

test('slow classification cannot replace manual moves and cannot resurrect removed files', () => {
  let queue = add(emptySourceQueue(), [file('a.pdf'), file('b.pdf')]).queue;
  const [a, b] = queue.items;
  queue = moveSourceFile(queue, a.id, 'spec', {});
  queue = removeSourceFile(queue, b.id, {});
  queue = applySourceSuggestions(queue, [{ id: a.id, role: 'tech' }, { id: b.id, role: 'reference' }], [a.id, b.id], {});
  assert.equal(queue.items.length, 1);
  assert.equal(queue.items[0].role, 'spec');
  assert.equal(queue.items[0].manual, true);
  assert.equal(queue.items[0].classifying, false);
});

test('moving a primary file selects a valid replacement without making two primaries', () => {
  let queue = add(emptySourceQueue(), [file('a.pdf'), file('b.pdf')], {}, 'tech').queue;
  queue = moveSourceFile(queue, queue.items[0].id, 'spec', {});
  assert.deepEqual(sourceBatchItems(queue).map(item => [item.role, item.primary]), [['spec', true], ['tech', true]]);
  queue = moveSourceFile(queue, queue.items[1].id, 'spec', {});
  assert.deepEqual(sourceBatchItems(queue).map(item => item.primary), [true, false]);
});

test('removing the selected primary promotes the remaining file and references never become primary', () => {
  let queue = add(emptySourceQueue(), [file('a.pdf'), file('b.pdf')], {}, 'tech').queue;
  queue = removeSourceFile(queue, queue.items[0].id, {});
  assert.equal(sourceBatchItems(queue)[0].primary, true);
  queue = moveSourceFile(queue, queue.items[0].id, 'reference', {});
  assert.equal(sourceBatchItems(queue)[0].primary, false);
});

test('duplicates and empty files are rejected while distinct revisions remain selectable', () => {
  const result = add(emptySourceQueue(), [file('a.pdf'), file('a.pdf'), file('a.pdf', 20), file('empty.pdf', 0)], {}, 'reference');
  assert.equal(result.queue.items.length, 2);
  assert.equal(result.accepted.length, 2);
  assert.match(result.issues.join(' '), /重复/);
  assert.match(result.issues.join(' '), /空/);
});

test('a batch never silently includes more than 50 files', () => {
  const result = add(emptySourceQueue(), Array.from({ length: 52 }, (_, index) => file(`${index}.pdf`)), {}, 'reference');
  assert.equal(result.queue.items.length, 50);
  assert.equal(result.accepted.length, 50);
  assert.match(result.issues.join(' '), /50/);
});

test('a failed suggestion request leaves files movable and cannot create an accidental reference', () => {
  let queue = add(emptySourceQueue(), [file('unknown.pdf')]).queue;
  queue = applySourceSuggestions(queue, [], [queue.items[0].id], {});
  assert.equal(queue.items[0].classifying, false);
  assert.equal(queue.items[0].role, 'unknown');
  assert.throws(() => sourceBatchItems(queue), /分类/);
  queue = moveSourceFile(queue, queue.items[0].id, 'reference', {});
  assert.equal(sourceQueueIssue(queue), '');
});

test('concurrent suggestions preserve the other pending request and react to current input changes', () => {
  let queue = add(emptySourceQueue({ tech: 'old' }), [file('a.pdf'), file('b.pdf')], { tech: 'old' }).queue;
  const [a, b] = queue.items;
  queue = applySourceSuggestions(queue, [{ id: a.id, role: 'tech' }], [a.id], { tech: 'old' });
  assert.equal(queue.items.find(item => item.id === b.id).classifying, true);
  assert.equal(queue.primary.tech, 'existing');
  queue = reconcileSourcePrimary(queue, {});
  assert.equal(queue.primary.tech, a.id);
  queue = applySourceSuggestions(queue, [{ id: b.id, role: 'reference' }], [b.id], {});
  assert.equal(sourceQueueIssue(queue), '');
});

test('an uncertain upload retains its exact files, primary decisions, key and project version for retry', () => {
  let queue = add(emptySourceQueue(), [file('需求.pdf'), file('补充.pdf')], {}, 'tech').queue;
  const first = queue.items[0];
  const attempt = createSourceBatchAttempt(queue, 'same-uncertain-key', 7);
  queue = moveSourceFile(queue, first.id, 'spec', {});
  queue = removeSourceFile(queue, queue.items[1].id, {});
  assert.equal(attempt.key, 'same-uncertain-key');
  assert.equal(attempt.expectedVersion, 7);
  assert.deepEqual(attempt.items.map(item => [item.file.name, item.role, item.primary]), [['需求.pdf', 'tech', true], ['补充.pdf', 'tech', false]]);
  assert.equal(queue.items.length, 1);
});
