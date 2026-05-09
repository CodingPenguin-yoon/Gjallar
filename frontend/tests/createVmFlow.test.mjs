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
  buildCreateVmPayload,
  loadCreateVmReviewModel,
  approveCreateVmReview,
} = await importExpected('../src/utils/createVmFlow.js', 'Create VM PRD flow utility')

const input = {
  operatorId: 'hermes-ui',
  jobId: 'job-ui-create',
  targetNodeId: 'yoonmanserver2',
  staticIp: '192.168.2.149',
  ipMode: 'static',
}

assert.deepEqual(buildCreateVmPayload(input), {
  operator_id: 'hermes-ui',
  job_id: 'job-ui-create',
  target_node_id: 'yoonmanserver2',
  static_ip: '192.168.2.149',
  ip_mode: 'static',
})

const calls = []
const fakeClient = {
  async createVmDraft(payload) {
    calls.push(['createVmDraft', payload])
    return {
      draft_id: 'draft-job-ui-create',
      job_id: payload.job_id,
      operator_id: payload.operator_id,
      vm_name: 'gjallar-vm-job-ui-create',
      proposed_vmid: 120,
      target_node_id: payload.target_node_id,
      hardware: { cpu: 2, memory_mb: 4096, disk_gb: 40 },
      network: { network_id: 'server-net', ip_mode: payload.ip_mode, static_ip: payload.static_ip, bridge_id: 'vmbr0' },
      terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      first_power_on_included: true,
      side_effects: [],
    }
  },
  async preflightVmDraft(draftId, payload) {
    calls.push(['preflightVmDraft', draftId, payload])
    return {
      draft_id: draftId,
      risk_level: 'green',
      checks: [{ code: 'template_available', status: 'pass', level: 'green', message: 'template ready' }],
      risks: [],
      selected_storage_id: 'local-lvm',
      selected_template_id: 'ubuntu-template',
      selected_bridge_id: 'vmbr0',
      side_effects: [],
    }
  },
  async planVmDraft(draftId, payload) {
    calls.push(['planVmDraft', draftId, payload])
    return {
      draft_id: draftId,
      job_id: payload.job_id,
      execution_intent: 'dry_run_plan_only',
      vm_name: 'gjallar-vm-job-ui-create',
      vmid: 120,
      target_node_id: payload.target_node_id,
      storage_id: 'local-lvm',
      template_id: 'ubuntu-template',
      hardware: { cpu: 2, memory_mb: 4096, disk_gb: 40 },
      network: { network_id: 'server-net', bridge_id: 'vmbr0', ip_mode: payload.ip_mode, ip_address: payload.static_ip },
      terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      first_power_on_included: true,
      smoke_timeout_summary: { cloud_init_minutes: 15, guest_agent_minutes: 5, ip_discovery_minutes: 5, ssh_minutes: 5 },
      risk_summary: { level: 'green', red: [], yellow: [] },
      review_confirm: {
        vm_name: 'gjallar-vm-job-ui-create',
        vmid: 120,
        target_node_id: payload.target_node_id,
        storage_id: 'local-lvm',
        template_id: 'ubuntu-template',
        hardware: { cpu: 2, memory_mb: 4096, disk_gb: 40 },
        network: { network_id: 'server-net', bridge_id: 'vmbr0', ip_mode: payload.ip_mode, ip_address: payload.static_ip },
        terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
        first_power_on_included: true,
        smoke_timeout_summary: { cloud_init_minutes: 15, guest_agent_minutes: 5, ip_discovery_minutes: 5, ssh_minutes: 5 },
        risk_summary: { level: 'green', red: [], yellow: [] },
        plan_artifact_id: 'artifact-plan',
        planned_git_diff_summary: '1 generated manifest',
        review_summary_checksum: 'sha256:abc123',
      },
      artifacts: [{ artifact_id: 'artifact-plan', type: 'plan', path: '/tmp/plan.json' }],
      side_effects: [],
    }
  },
  async approveVmDraft(draftId, payload) {
    calls.push(['approveVmDraft', draftId, payload])
    return {
      can_approve: true,
      can_execute: true,
      requires_yellow_ack: false,
      reason: 'approved',
      side_effects: [],
      approval_record: { decision: 'approved' },
    }
  },
  async executeVmDraft() {
    calls.push(['executeVmDraft'])
    throw new Error('UI must not call execute from F7')
  },
}

const model = await loadCreateVmReviewModel(fakeClient, input)
assert.deepEqual(calls.map((call) => call[0]), ['createVmDraft', 'preflightVmDraft', 'planVmDraft'])
assert.equal(model.draft.id, 'draft-job-ui-create')
assert.equal(model.preflight.level, 'green')
assert.equal(model.plan.executionIntent, 'dry_run_plan_only')
assert.equal(model.review.vmName, 'gjallar-vm-job-ui-create')
assert.equal(model.review.canApprove, true)
assert.equal(model.review.canExecute, false, 'UI must not expose execute even if backend approval says can_execute')
assert.equal(model.review.executeDisabledReason, 'execute requires explicit live approval outside this MVP UI slice')
assert.equal(model.artifacts[0].id, 'artifact-plan')
assert.deepEqual(model.sideEffects, [])

const approval = await approveCreateVmReview(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(approval.canApprove, true)
assert.equal(approval.canExecute, false)
assert.equal(approval.executeDisabledReason, 'execute requires explicit live approval outside this MVP UI slice')
assert.deepEqual(approval.sideEffects, [])


const deniedApproval = await approveCreateVmReview(
  {
    ...fakeClient,
    async approveVmDraft(draftId, payload) {
      calls.push(['approveVmDraftDenied', draftId, payload])
      return {
        can_approve: false,
        can_execute: false,
        requires_yellow_ack: true,
        reason: 'yellow risk acknowledgement required',
        side_effects: [],
      }
    },
  },
  model,
  { yellowRiskAcknowledged: false },
)
assert.equal(deniedApproval.canApprove, false)
assert.equal(deniedApproval.canExecute, false)
assert.equal(deniedApproval.status, 'blocked')
assert.equal(deniedApproval.tone, 'yellow')
assert.match(deniedApproval.operatorMessage, /not approved|blocked|acknowledgement/i)
assert.deepEqual(deniedApproval.sideEffects, [])

const source = readFileSync(new URL('../src/components/CreateInstanceWizard.jsx', import.meta.url), 'utf8')
assert.match(source, /apiV1Client/)
assert.match(source, /loadCreateVmReviewModel/)
assert.match(source, /approveCreateVmReview/)
assert.doesNotMatch(source, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'Create VM wizard must not import the legacy /api client')

const forbidden = (...parts) => parts.join('')
for (const blocked of [
  forbidden('get', 'Servers'),
  forbidden('get', 'Templates'),
  forbidden('get', 'ServerStorage'),
  forbidden('get', 'ServerNetworks'),
  forbidden('check', 'IpAvailability'),
  forbidden('check', 'Provisioning'),
  forbidden('on', 'Provision'),
  forbidden('is', 'Provisioning'),
  forbidden('/api/', 'provision'),
  forbidden('execute', 'VmDraft'),
  forbidden('execute', ' button'),
  forbidden('Terraform', ' apply'),
  forbidden('Proxmox', ' write'),
  forbidden('window.', 'confirm'),
  forbidden('window.', 'prompt'),
]) {
  assert.ok(!source.toLowerCase().includes(blocked.toLowerCase()), `Create VM wizard must not expose legacy/live term: ${blocked}`)
}

console.log('createVmFlow RED contract exercised')
