import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const {
  API_V1_BASE_URL,
  API_V1_ENDPOINTS,
  createApiV1Client,
  unwrapApiV1Envelope,
} = await importExpected('../src/services/apiV1.js', 'PRD /api/v1 client')

assert.equal(API_V1_BASE_URL, '/api/v1')
assert.equal(API_V1_ENDPOINTS.jobs, '/jobs')
assert.equal(API_V1_ENDPOINTS.risks, '/risks')
assert.equal(API_V1_ENDPOINTS.vms, '/vms')
assert.equal(API_V1_ENDPOINTS.nodes, '/nodes')
assert.equal(API_V1_ENDPOINTS.drsSummary, '/drs/summary')
assert.equal(API_V1_ENDPOINTS.drsRecommendations, '/drs/recommendations')
assert.equal(API_V1_ENDPOINTS.drsRecommendation('rec/1'), '/drs/recommendations/rec%2F1')
assert.equal(API_V1_ENDPOINTS.drsRecommendationCheck('rec/1'), '/drs/recommendations/rec%2F1/check')
assert.equal(API_V1_ENDPOINTS.vmStart('node/a', 306), '/nodes/node%2Fa/vms/306/actions/start')
assert.equal(API_V1_ENDPOINTS.jobArtifacts('job/a b'), '/jobs/job%2Fa%20b/artifacts')
assert.equal(API_V1_ENDPOINTS.vmCreateReadiness, '/vm-create/readiness')
assert.equal(API_V1_ENDPOINTS.vmCreatePreflight('draft/1'), '/vm-create/draft%2F1/preflight')
assert.equal(API_V1_ENDPOINTS.vmCreatePlan('draft/1'), '/vm-create/draft%2F1/plan')
assert.equal(API_V1_ENDPOINTS.vmCreateApprove('draft/1'), '/vm-create/draft%2F1/approve')
assert.equal(API_V1_ENDPOINTS.vmCreateProxmoxPreview('draft/1'), '/vm-create/draft%2F1/proxmox-preview')
assert.equal(API_V1_ENDPOINTS.vmCreateProxmoxCreate('draft/1'), '/vm-create/draft%2F1/proxmox-create')

const calls = []
const fakeFetch = async (url, options = {}) => {
  calls.push({ url, options })
  return {
    ok: true,
    status: 200,
    json: async () => ({
      ok: true,
      data: { url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null },
      meta: { mode: 'read_only' },
    }),
  }
}

const client = createApiV1Client({ baseUrl: '/custom/api/v1', fetchImpl: fakeFetch })
assert.equal((await client.listJobs()).url, '/custom/api/v1/jobs')
assert.equal((await client.getJob('job/a b')).url, '/custom/api/v1/jobs/job%2Fa%20b')
assert.equal((await client.listJobArtifacts('job/a b')).url, '/custom/api/v1/jobs/job%2Fa%20b/artifacts')
assert.equal((await client.listRisks()).url, '/custom/api/v1/risks')
assert.equal((await client.listNodes()).url, '/custom/api/v1/nodes')
assert.equal((await client.listVms()).url, '/custom/api/v1/vms')
assert.equal((await client.getVm(101)).url, '/custom/api/v1/vms/101')
assert.deepEqual((await client.startVm('node/a', 306, { vm_start_acknowledged: true })).body, { vm_start_acknowledged: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/nodes/node%2Fa/vms/306/actions/start')
assert.equal((await client.listProfiles()).url, '/custom/api/v1/profiles')
assert.equal((await client.listTemplates()).url, '/custom/api/v1/templates')
assert.equal((await client.listStorage()).url, '/custom/api/v1/storage')
assert.equal((await client.listNetworks()).url, '/custom/api/v1/networks')
assert.equal((await client.getDrsSummary()).url, '/custom/api/v1/drs/summary')
assert.equal((await client.listDrsRecommendations()).url, '/custom/api/v1/drs/recommendations')
assert.equal((await client.getDrsRecommendation('rec/1')).url, '/custom/api/v1/drs/recommendations/rec%2F1')
assert.deepEqual((await client.checkDrsRecommendation('rec/1', { reference_only: true })).body, { reference_only: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/drs/recommendations/rec%2F1/check')
assert.equal((await client.getVmCreateReadiness()).url, '/custom/api/v1/vm-create/readiness')
assert.deepEqual((await client.createVmDraft({ operator_id: 'hermes' })).body, { operator_id: 'hermes' })
assert.equal(calls.at(-1).options.method, 'POST')
assert.deepEqual((await client.preflightVmDraft('draft/1', { static_ip: '192.168.2.141' })).body, { static_ip: '192.168.2.141' })
assert.equal(calls.at(-1).url, '/custom/api/v1/vm-create/draft%2F1/preflight')
assert.deepEqual((await client.planVmDraft('draft/1', { target_node_id: 'yoonmanserver2' })).body, { target_node_id: 'yoonmanserver2' })
assert.equal(calls.at(-1).url, '/custom/api/v1/vm-create/draft%2F1/plan')
assert.deepEqual((await client.approveVmDraft('draft/1', { plan_artifact_id: 'artifact-plan' })).body, { plan_artifact_id: 'artifact-plan' })
assert.equal(calls.at(-1).url, '/custom/api/v1/vm-create/draft%2F1/approve')
assert.deepEqual((await client.previewVmDraftProxmox('draft/1', { plan_artifact_id: 'artifact-plan' })).body, { plan_artifact_id: 'artifact-plan' })
assert.equal(calls.at(-1).url, '/custom/api/v1/vm-create/draft%2F1/proxmox-preview')
assert.deepEqual((await client.createVmDraftProxmox('draft/1', { proxmox_mutation_acknowledged: true })).body, { proxmox_mutation_acknowledged: true })
assert.equal(calls.at(-1).url, '/custom/api/v1/vm-create/draft%2F1/proxmox-create')

const failingClient = createApiV1Client({
  baseUrl: '/custom/api/v1',
  fetchImpl: async () => ({
    ok: false,
    status: 409,
    json: async () => ({
      detail: {
        code: 'PROXMOX_CREATE_FAILED',
        message: 'Native Proxmox create failed',
      },
    }),
  }),
})
await assert.rejects(
  () => failingClient.createVmDraftProxmox('draft/1', {}),
  /Native Proxmox create failed/,
)

assert.deepEqual(unwrapApiV1Envelope({ ok: true, data: [1, 2] }), [1, 2])
assert.throws(
  () => unwrapApiV1Envelope({ ok: false, error: { code: 'blocked', message: 'red risk' } }),
  /red risk/,
)
assert.throws(() => unwrapApiV1Envelope({ data: [] }), /Malformed|ok/i)

const source = readFileSync(new URL('../src/services/apiV1.js', import.meta.url), 'utf8')
const forbiddenEndpoint = (...parts) => parts.join('')
for (const forbidden of [
  forbiddenEndpoint('/api', '/tasks'),
  forbiddenEndpoint('/api', '/status'),
  forbiddenEndpoint('/api', '/logs'),
  forbiddenEndpoint('/api', '/provision'),
  forbiddenEndpoint('/api', '/instances', '/terminate'),
  forbiddenEndpoint('/api', '/instances', '/action'),
  forbiddenEndpoint('/api', '/instances', '/resources'),
  forbiddenEndpoint('/api', '/llm'),
  forbiddenEndpoint('/vm-create/', 'execute'),
  forbiddenEndpoint('/vm-create/', 'archive'),
  forbiddenEndpoint('/drs/recommendations/', 'approve'),
  forbiddenEndpoint('/drs/recommendations/', 'migrate'),
  forbiddenEndpoint('/drs/recommendations/', 'live-migrate'),
  forbiddenEndpoint('/drs/recommendations/', 'check-now'),
]) {
  assert.ok(!source.includes(forbidden), `apiV1 client must not reintroduce legacy endpoint ${forbidden}`)
}

console.log('apiV1Client RED contract exercised')
