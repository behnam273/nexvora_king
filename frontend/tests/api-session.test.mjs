import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const api = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
globalThis.window = new EventTarget();
const unauthorized = () => new Response(JSON.stringify({ detail: 'expired' }), { status: 401 });

test('protected 401 signals expiration; login failure and other errors do not', async () => {
  let events = 0;
  window.addEventListener(api.SESSION_EXPIRED_EVENT, () => events++);
  api.setCsrfToken('session');
  globalThis.fetch = async () => unauthorized();
  await assert.rejects(api.apiFetch('/api/v1/auth/login', { method: 'POST' }));
  assert.equal(events, 0);
  await assert.rejects(api.apiFetch('/api/v1/dashboard'));
  assert.equal(events, 1);
  globalThis.fetch = async () => new Response('', { status: 500 });
  await assert.rejects(api.apiFetch('/api/v1/dashboard'));
  assert.equal(events, 1);
});

test('a stale 401 cannot invalidate a newly established session', async () => {
  let events = 0;
  window.addEventListener(api.SESSION_EXPIRED_EVENT, () => events++);
  api.setCsrfToken('old');
  let resolve;
  globalThis.fetch = () => new Promise(r => { resolve = r; });
  const pending = api.apiFetch('/api/v1/dashboard');
  api.setCsrfToken('new');
  resolve(unauthorized());
  await assert.rejects(pending);
  assert.equal(events, 0);
  assert.equal(api.getCsrfToken(), 'new');
});
