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
  unwrapApiV1EnvelopeWithMeta,
} = await importExpected('../src/services/apiV1.js', 'PRD /api/v1 client')

assert.equal(API_V1_BASE_URL, '/api/v1')
assert.equal(API_V1_ENDPOINTS.authLogin, '/auth/login')
assert.equal(API_V1_ENDPOINTS.authLogout, '/auth/logout')
assert.equal(API_V1_ENDPOINTS.authMe, '/auth/me')
assert.equal(API_V1_ENDPOINTS.authChangePassword, '/auth/change-password')
assert.equal(API_V1_ENDPOINTS.adminUsers, '/admin/users')
assert.equal(API_V1_ENDPOINTS.adminUserRole('user/name'), '/admin/users/user%2Fname/role')
assert.equal(API_V1_ENDPOINTS.adminUserDisable('user/name'), '/admin/users/user%2Fname/disable')
assert.equal(API_V1_ENDPOINTS.adminUserResetPassword('user/name'), '/admin/users/user%2Fname/reset-password')
assert.equal(API_V1_ENDPOINTS.adminSessions, '/admin/sessions')
assert.equal(API_V1_ENDPOINTS.adminSessionRevoke('sess/1'), '/admin/sessions/sess%2F1/revoke')
assert.equal(API_V1_ENDPOINTS.proxmoxConnection, '/setup/proxmox/connection')
assert.equal(API_V1_ENDPOINTS.jobs, '/jobs')
assert.equal(API_V1_ENDPOINTS.risks, '/risks')
assert.equal(API_V1_ENDPOINTS.insights, '/insights')
assert.equal(API_V1_ENDPOINTS.operations, '/operations')
assert.equal(API_V1_ENDPOINTS.operation('operation/a'), '/operations/operation%2Fa')
assert.equal(API_V1_ENDPOINTS.guidedQmVmUnlock, '/operations/guided-qm/vm-unlock')
assert.equal(API_V1_ENDPOINTS.operationAttestation('operation/a'), '/operations/operation%2Fa/operator-attestation')
assert.equal(API_V1_ENDPOINTS.operationVerification('operation/a'), '/operations/operation%2Fa/verification')
assert.equal(API_V1_ENDPOINTS.vms, '/vms')
assert.equal(API_V1_ENDPOINTS.nodes, '/nodes')
assert.equal(API_V1_ENDPOINTS.vmStart('node/a', 306), '/nodes/node%2Fa/vms/306/actions/start')
assert.equal(API_V1_ENDPOINTS.vmShutdown('node/a', 306), '/nodes/node%2Fa/vms/306/actions/shutdown')
assert.equal(API_V1_ENDPOINTS.postCreateReadinessEvidence('node/a', 306), '/nodes/node%2Fa/vms/306/post-create-readiness-evidence')
assert.equal(API_V1_ENDPOINTS.jobArtifacts('job/a b'), '/jobs/job%2Fa%20b/artifacts')
assert.equal(API_V1_ENDPOINTS.vmCreatePreflight('draft/1'), '/vm-create/draft%2F1/preflight')
assert.equal(API_V1_ENDPOINTS.vmCreatePlan('draft/1'), '/vm-create/draft%2F1/plan')
assert.equal(API_V1_ENDPOINTS.vmCreateApprove('draft/1'), '/vm-create/draft%2F1/approve')
assert.equal(API_V1_ENDPOINTS.vmCreateProxmoxPreview('draft/1'), '/vm-create/draft%2F1/proxmox-preview')
assert.equal(API_V1_ENDPOINTS.vmCreateProxmoxCreate('draft/1'), '/vm-create/draft%2F1/proxmox-create')

const calls = []
const responseMeta = {
  mode: 'read_only',
  source: 'live_read_only',
  observed_at: '2026-08-25T01:00:00Z',
  freshness: 'fresh',
  connection: { state: 'connected', source: 'live_read_only', freshness: 'fresh' },
}
const fakeFetch = async (url, options = {}) => {
  calls.push({ url, options })
  return {
    ok: true,
    status: 200,
    json: async () => ({
      ok: true,
      data: { url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null },
      meta: responseMeta,
    }),
  }
}

const client = createApiV1Client({ baseUrl: '/custom/api/v1', fetchImpl: fakeFetch })
assert.deepEqual((await client.login('yoon', 'secret')).body, { username: 'yoon', password: 'secret' })
assert.equal(calls.at(-1).url, '/custom/api/v1/auth/login')
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal((await client.me()).url, '/custom/api/v1/auth/me')
assert.equal(calls.at(-1).options.method, 'GET')
assert.deepEqual((await client.logout()).body, {})
assert.equal(calls.at(-1).url, '/custom/api/v1/auth/logout')
assert.equal(calls.at(-1).options.method, 'POST')
assert.deepEqual((await client.changePassword('old-secret', 'new-secret')).body, { current_password: 'old-secret', new_password: 'new-secret' })
assert.equal(calls.at(-1).url, '/custom/api/v1/auth/change-password')
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal((await client.listAdminUsers()).url, '/custom/api/v1/admin/users')
assert.equal(calls.at(-1).options.method, 'GET')
assert.deepEqual((await client.createAdminUser({ username: 'kim', password: 'secret', role: 'viewer' })).body, { username: 'kim', password: 'secret', role: 'viewer' })
assert.equal(calls.at(-1).url, '/custom/api/v1/admin/users')
assert.equal(calls.at(-1).options.method, 'POST')
assert.deepEqual((await client.setAdminUserRole('kim/admin', 'operator')).body, { role: 'operator' })
assert.equal(calls.at(-1).url, '/custom/api/v1/admin/users/kim%2Fadmin/role')
assert.equal(calls.at(-1).options.method, 'PATCH')
assert.deepEqual((await client.disableAdminUser('kim/admin')).body, {})
assert.equal(calls.at(-1).url, '/custom/api/v1/admin/users/kim%2Fadmin/disable')
assert.equal(calls.at(-1).options.method, 'POST')
assert.deepEqual((await client.resetAdminUserPassword('kim/admin', 'new-secret')).body, { password: 'new-secret' })
assert.equal(calls.at(-1).url, '/custom/api/v1/admin/users/kim%2Fadmin/reset-password')
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal((await client.listAdminSessions()).url, '/custom/api/v1/admin/sessions')
assert.equal(calls.at(-1).options.method, 'GET')
assert.deepEqual((await client.revokeAdminSession('sess/1')).body, {})
assert.equal(calls.at(-1).url, '/custom/api/v1/admin/sessions/sess%2F1/revoke')
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal((await client.proxmoxConnection()).url, '/custom/api/v1/setup/proxmox/connection')
assert.equal(calls.at(-1).options.method, 'GET')
assert.equal((await client.listJobs()).url, '/custom/api/v1/jobs')
assert.equal((await client.getJob('job/a b')).url, '/custom/api/v1/jobs/job%2Fa%20b')
assert.equal((await client.listJobArtifacts('job/a b')).url, '/custom/api/v1/jobs/job%2Fa%20b/artifacts')
assert.equal((await client.listRisks()).url, '/custom/api/v1/risks')
assert.equal((await client.getInsights()).url, '/custom/api/v1/insights')
assert.equal((await client.listOperations({ status: 'awaiting_operator', limit: 25 })).url, '/custom/api/v1/operations?status=awaiting_operator&limit=25')
assert.equal((await client.getOperation('operation/a')).url, '/custom/api/v1/operations/operation%2Fa')
assert.deepEqual((await client.planGuidedQmVmUnlock({ node_id: 'node-a', vmid: 306 })).body, { node_id: 'node-a', vmid: 306 })
assert.equal(calls.at(-1).url, '/custom/api/v1/operations/guided-qm/vm-unlock')
assert.deepEqual((await client.attestOperation('operation/a', { command_executed: true })).body, { command_executed: true })
assert.equal(calls.at(-1).url, '/custom/api/v1/operations/operation%2Fa/operator-attestation')
assert.deepEqual((await client.verifyOperation('operation/a', { plan_digest: 'sha256:plan' })).body, { plan_digest: 'sha256:plan' })
assert.equal(calls.at(-1).url, '/custom/api/v1/operations/operation%2Fa/verification')
assert.equal((await client.listNodes()).url, '/custom/api/v1/nodes')
assert.equal((await client.listVms()).url, '/custom/api/v1/vms')
assert.deepEqual(await client.listNodesWithMeta(), {
  data: { url: '/custom/api/v1/nodes', method: 'GET', body: null },
  meta: responseMeta,
})
assert.deepEqual(await client.listVmsWithMeta(), {
  data: { url: '/custom/api/v1/vms', method: 'GET', body: null },
  meta: responseMeta,
})
assert.equal((await client.getVm(101)).url, '/custom/api/v1/vms/101')
assert.deepEqual((await client.startVm('node/a', 306, { vm_start_acknowledged: true })).body, { vm_start_acknowledged: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/nodes/node%2Fa/vms/306/actions/start')
assert.deepEqual((await client.shutdownVm('node/a', 306, { vm_shutdown_acknowledged: true })).body, { vm_shutdown_acknowledged: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/nodes/node%2Fa/vms/306/actions/shutdown')
assert.deepEqual((await client.recordPostCreateReadinessEvidence('node/a', 306, { post_create_readiness_evidence_acknowledged: true })).body, { post_create_readiness_evidence_acknowledged: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/nodes/node%2Fa/vms/306/post-create-readiness-evidence')
assert.equal((await client.listProfiles()).url, '/custom/api/v1/profiles')
assert.equal((await client.listTemplates()).url, '/custom/api/v1/templates')
assert.equal((await client.listStorage()).url, '/custom/api/v1/storage')
assert.equal((await client.listNetworks()).url, '/custom/api/v1/networks')
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

for (const call of calls) {
  assert.equal(call.options.credentials, 'include', `${call.url} must include browser session cookies`)
}

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

const nonJsonFailureClient = createApiV1Client({
  baseUrl: '/custom/api/v1',
  fetchImpl: async () => ({
    ok: false,
    status: 500,
    text: async () => 'Internal Server Error',
  }),
})
await assert.rejects(
  () => nonJsonFailureClient.getInsights(),
  /API v1 request failed with status 500: Internal Server Error/,
)

assert.deepEqual(unwrapApiV1Envelope({ ok: true, data: [1, 2] }), [1, 2])
assert.deepEqual(
  unwrapApiV1EnvelopeWithMeta({ ok: true, data: [1, 2], meta: { source: 'live_read_only' } }),
  { data: [1, 2], meta: { source: 'live_read_only' } },
)
assert.deepEqual(unwrapApiV1EnvelopeWithMeta({ ok: true, data: [] }), { data: [], meta: {} })
assert.throws(
  () => unwrapApiV1Envelope({ ok: false, error: { code: 'blocked', message: 'red risk' } }),
  /red risk/,
)
assert.throws(() => unwrapApiV1Envelope({ data: [] }), /Malformed|ok/i)

const source = readFileSync(new URL('../src/shared/api/apiV1.js', import.meta.url), 'utf8')
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
]) {
  assert.ok(!source.includes(forbidden), `apiV1 client must not reintroduce legacy endpoint ${forbidden}`)
}
assert.doesNotMatch(source, /['"]\/drs(?:\/|['"])/, 'apiV1 client must not expose DRS endpoints')
assert.doesNotMatch(source, /\b(?:getDrs|listDrs|checkDrs|createDrs|updateDrs|drsPolicies|drsPolicy|reconcilePreviewDrs)\w*\b/, 'apiV1 client must not expose DRS methods')

console.log('apiV1Client RED contract exercised')
