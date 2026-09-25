import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import { randomUUID } from '../src/shared/requestId.js'

const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
try {
  const expected = '12345678-1234-4234-8234-123456789abc'
  const native = { randomUUID() { assert.equal(this, native); return expected } }
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: native })
  assert.equal(randomUUID(), expected)
  // Ordinary HTTP exposes getRandomValues, but not randomUUID.
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {
    getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
  } })
  const ids = Array.from({ length: 1000 }, () => randomUUID())
  assert.equal(new Set(ids).size, ids.length)
  for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {
    getRandomValues(bytes) { bytes.fill(255); return bytes },
  } })
  assert.equal(randomUUID(), 'ffffffff-ffff-4fff-bfff-ffffffffffff')
} finally {
  if (original) Object.defineProperty(globalThis, 'crypto', original)
  else delete globalThis.crypto
}
const src = new URL('../src/', import.meta.url)
for (const path of readdirSync(src, { recursive: true })) {
  if (!/\.(js|jsx)$/.test(path) || path === 'shared/requestId.js') continue
  const source = readFileSync(new URL(path, src), 'utf8')
  assert.doesNotMatch(source, /\bcrypto\.randomUUID\(/, path)
}
console.log('HTTP-compatible request UUID tests passed')
