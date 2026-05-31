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
assert.equal(API_V1_ENDPOINTS.jobs, '/jobs')
assert.equal(API_V1_ENDPOINTS.risks, '/risks')
assert.equal(API_V1_ENDPOINTS.vms, '/vms')
assert.equal(API_V1_ENDPOINTS.nodes, '/nodes')
assert.equal(API_V1_ENDPOINTS.drsSummary, '/drs/summary')
assert.equal(API_V1_ENDPOINTS.drsRecommendations, '/drs/recommendations')
assert.equal(API_V1_ENDPOINTS.drsRecommendation('rec/1'), '/drs/recommendations/rec%2F1')
assert.equal(API_V1_ENDPOINTS.drsRecommendationCheck('rec/1'), '/drs/recommendations/rec%2F1/check')
assert.equal(API_V1_ENDPOINTS.drsRecommendationApprovalPackets('rec/1'), '/drs/recommendations/rec%2F1/approval-packets')
assert.equal(API_V1_ENDPOINTS.drsPolicies, '/drs/policies')
assert.equal(API_V1_ENDPOINTS.drsPolicy('vmid/1'), '/drs/policies/vmid%2F1')
assert.equal(API_V1_ENDPOINTS.drsMigrationJobReconcilePreview('job/1'), '/drs/migration-jobs/job%2F1/reconcile-preview')
assert.equal(API_V1_ENDPOINTS.vmStart('node/a', 306), '/nodes/node%2Fa/vms/306/actions/start')
assert.equal(API_V1_ENDPOINTS.postCreateReadinessEvidence('node/a', 306), '/nodes/node%2Fa/vms/306/post-create-readiness-evidence')
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
assert.deepEqual((await client.recordPostCreateReadinessEvidence('node/a', 306, { post_create_readiness_evidence_acknowledged: true })).body, { post_create_readiness_evidence_acknowledged: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/nodes/node%2Fa/vms/306/post-create-readiness-evidence')
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
assert.deepEqual((await client.createDrsApprovalPacket('rec/1', { warning_acknowledged: true })).body, { warning_acknowledged: true })
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/drs/recommendations/rec%2F1/approval-packets')
assert.equal((await client.drsPolicies()).url, '/custom/api/v1/drs/policies')
assert.equal(calls.at(-1).options.method, 'GET')
assert.equal((await client.drsPolicy('vmid/1')).url, '/custom/api/v1/drs/policies/vmid%2F1')
assert.deepEqual((await client.updateDrsPolicy('vmid/1', { policy: 'allowed' })).body, { policy: 'allowed' })
assert.equal(calls.at(-1).options.method, 'PUT')
assert.equal(calls.at(-1).url, '/custom/api/v1/drs/policies/vmid%2F1')
assert.deepEqual((await client.reconcilePreviewDrsMigrationJob('job/1', {})).body, {})
assert.equal(calls.at(-1).options.method, 'POST')
assert.equal(calls.at(-1).url, '/custom/api/v1/drs/migration-jobs/job%2F1/reconcile-preview')
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
  () => nonJsonFailureClient.getDrsSummary(),
  /API v1 request failed with status 500: Internal Server Error/,
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
assert.doesNotMatch(source, /executeDrsMigrationJob|drsMigrationJobExecute/, 'apiV1 client must not expose DRS migration execute mutation helpers')
assert.match(source, /updateDrsPolicy/, 'apiV1 client must expose manual DRS policy update helper')
assert.match(source, /method: 'PUT'/, 'apiV1 client must support PUT for policy updates')

console.log('apiV1Client RED contract exercised')
