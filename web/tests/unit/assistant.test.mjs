import assert from 'node:assert/strict';
import test from 'node:test';
import { assistantEnterSubmits, assistantHistory, assistantHref, assistantPanelWidth, assistantProjectId } from '../../src/features/assistant/model/assistant.ts';

test('assistant navigation accepts platform surfaces and rejects external or administrative destinations', () => {
  for (const href of ['/', '/rd', '/rd/p-123?tab=flow#task-t-12', '/rd/p-123/tasks/t-12?view=review', '/requirements', '/tasks', '/approvals', '/taskbook', '/help/manual']) assert.equal(assistantHref(href), href);
  for (const href of ['https://evil.example/rd', '//evil.example/rd', 'javascript:alert(1)', '/api/rd/projects', '/admin', '/auth/login', '/\\evil.example/rd', '/rd\n', '/unknown']) assert.equal(assistantHref(href), null);
});
test('assistant extracts projects from project and native task surfaces only', () => {
  assert.equal(assistantProjectId('/rd/p-12'), 'p-12');
  assert.equal(assistantProjectId('/rd/p-12/tasks/t-22'), 'p-12');
  assert.equal(assistantProjectId('/rd'), undefined);
  assert.equal(assistantProjectId('/rd/p-12/anything'), undefined);
  assert.equal(assistantProjectId('/rd/%invalid'), undefined);
});
test('completed history is bounded, strips UI metadata and leaves original messages unchanged', () => {
  const messages = Array.from({ length: 20 }, (_, index) => ({ role: index % 2 ? 'assistant' : 'user', content: `${index}:${'x'.repeat(7000)}`, actions: [{ href: '/rd' }] }));
  const history = assistantHistory(messages);
  assert.equal(history.length, 12);
  assert.equal(history[0].content.startsWith('8:'), true);
  assert.equal(history.every(message => message.content.length === 6000), true);
  assert.deepEqual(Object.keys(history[0]).sort(), ['content', 'role']);
  assert.equal(messages[8].content.length, 7002);
});
test('Enter submits while newline and Chinese IME confirmation remain input operations', () => {
  assert.equal(assistantEnterSubmits({ key: 'Enter', shiftKey: false, isComposing: false }), true);
  assert.equal(assistantEnterSubmits({ key: 'Enter', shiftKey: true, isComposing: false }), false);
  assert.equal(assistantEnterSubmits({ key: 'Enter', shiftKey: false, isComposing: true }), false);
  assert.equal(assistantEnterSubmits({ key: 'Enter', shiftKey: false, isComposing: false, keyCode: 229 }), false);
});

test('desktop panel widths retain a usable business surface and remain within resizing limits', () => {
  assert.equal(assistantPanelWidth(420, 1440), 420);
  assert.equal(assistantPanelWidth(900, 1440), 640);
  assert.equal(assistantPanelWidth(200, 1440), 320);
  assert.equal(assistantPanelWidth(640, 1200), 552);
  assert.equal(assistantPanelWidth(640, 981), 333);
  assert.equal(assistantPanelWidth(420, 390), 420);
});
