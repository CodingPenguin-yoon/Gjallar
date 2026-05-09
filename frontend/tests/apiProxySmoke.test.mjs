import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { API_V1_BASE_URL, API_V1_ENDPOINTS } = await importExpected(
  '../src/services/apiV1.js',
  'PRD /api/v1 client'
)

const viteConfigSource = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8')
assert.match(viteConfigSource, /proxy:\s*\{[\s\S]*['"]\/api['"]\s*:/, 'Vite dev server must proxy the backend /api surface')
assert.match(viteConfigSource, /VITE_BACKEND_URL|127\.0\.0\.1:8001/, 'Vite proxy must still target the backend runtime')

const requiredSmokePaths = [
  `${API_V1_BASE_URL}${API_V1_ENDPOINTS.nodes}`,
  `${API_V1_BASE_URL}${API_V1_ENDPOINTS.vms}`,
  `${API_V1_BASE_URL}${API_V1_ENDPOINTS.jobs}`,
  `${API_V1_BASE_URL}${API_V1_ENDPOINTS.risks}`,
]

assert.deepEqual(
  requiredSmokePaths,
  [
    '/api/v1/nodes',
    '/api/v1/vms',
    '/api/v1/jobs',
    '/api/v1/risks',
  ],
  'Frontend smoke coverage must include proxied inventory, jobs, and risks endpoints'
)

console.log('apiProxySmoke RED contract exercised')
