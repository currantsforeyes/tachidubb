// Vitest setup: runs before every test file.
//
// Three things views assume but jsdom doesn't provide:
//   1. fetch       -> the route table in api.js (views fetch on mount)
//   2. cleanup     -> RTL auto-cleanup needs a global afterEach, which is off
//                     when vitest globals are disabled, so we do it manually
//   3. confirm/alert -> jsdom throws "not implemented"; JobRow/RedubModal use them
import { afterEach, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/react';

import { installFetch, resetApi } from './api.js';

installFetch();

// Node ≥22 gates its built-in localStorage behind --localstorage-file and,
// without it, the global is an accessor that warns and yields undefined
// (shadowing jsdom's). The app persists form prefs via _lsGet/_lsSet, so
// give it a real store — this keeps those code paths honest instead of
// silently falling back in a try/catch.
// Detect via the property descriptor: touching `localStorage` itself would
// emit Node's ExperimentalWarning on every run, and an existing data
// property (jsdom or a real Node store) is left alone.
const storageDesc = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
const needsStorage = !storageDesc || 'get' in storageDesc || storageDesc.value == null;
if (needsStorage) {
  const store = new Map();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k) => (store.has(String(k)) ? store.get(String(k)) : null),
      setItem: (k, v) => store.set(String(k), String(v)),
      removeItem: (k) => store.delete(String(k)),
      clear: () => store.clear(),
      key: (i) => [...store.keys()][i] ?? null,
      get length() { return store.size; },
    },
  });
}

beforeEach(() => {
  resetApi();
  // HomeView persists form prefs to localStorage; isolate tests from each other.
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

if (!globalThis.confirm) globalThis.confirm = () => true;
if (!globalThis.alert) globalThis.alert = () => {};
if (!globalThis.scrollTo) globalThis.scrollTo = () => {};
