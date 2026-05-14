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
  buildCreateVmInputFromConfig,
  loadCreateVmReviewModel,
  approveCreateVmReview,
  commitCreateVmManifest,
  createVmWithProxmox,
  decorateTemplateOptionsForProfile,
  normalizeTemplateOptions,
  previewCreateVmProxmox,
  selectPreferredTemplate,
  validateTemplateSelection,
} = await importExpected('../src/utils/createVmFlow.js', 'Create VM native flow utility')

const TEST_SSH_PUBLIC_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g gjallar@test'
const TEST_SSH_FINGERPRINT = 'SHA256:mKqU+0K8OhKmA8bBQi9Rz0Q5l7/g160hIP+rJYSTNj4'

const input = {
  operatorId: 'hermes-ui',
  jobId: 'job-ui-create',
  profileId: 'general-vm',
  targetNodeId: 'yoonmanserver2',
  storageId: 'nas-server',
  networkId: 'evil-net',
  bridgeId: 'vmbr0',
  staticIp: '192.168.2.149',
  prefix: 25,
  gateway: '192.168.2.254',
  ipMode: 'static',
  templateId: 'ubuntu-template',
  templateVmid: 9000,
  templateNodeId: 'yoonmanserver2',
  hardware: { cpu: 2, memoryMb: 4096, diskGb: 50 },
  cloudInitUser: 'ubuntu',
  sshPublicKey: TEST_SSH_PUBLIC_KEY,
}

assert.deepEqual(buildCreateVmPayload(input), {
  operator_id: 'hermes-ui',
  job_id: 'job-ui-create',
  profile_id: 'general-vm',
  target_node_id: 'yoonmanserver2',
  storage_id: 'nas-server',
  bridge_id: 'vmbr0',
  static_ip: '192.168.2.149',
  prefix: 25,
  gateway: '192.168.2.254',
  ip_mode: 'static',
  template_id: 'ubuntu-template',
  template_vmid: 9000,
  template_node_id: 'yoonmanserver2',
  hardware_overrides: { cpu: 2, memory_mb: 4096, disk_gb: 50 },
  access: {
    cloud_init_user: 'ubuntu',
    ssh_public_key: TEST_SSH_PUBLIC_KEY,
    password_login: false,
  },
})
assert.equal('network_id' in buildCreateVmPayload(input), false)
assert.equal('ssh_public_key' in buildCreateVmPayload(input), false)

assert.deepEqual(buildCreateVmPayload({
  operatorId: 'nested-test',
  network: {
    networkId: 'evil-net',
    bridgeId: 'vmbr0',
    staticIp: '192.168.2.149',
    prefix: 25,
    gateway: '192.168.2.254',
    ipMode: 'static',
  },
}), {
  operator_id: 'nested-test',
  bridge_id: 'vmbr0',
  static_ip: '192.168.2.149',
  prefix: 25,
  gateway: '192.168.2.254',
  ip_mode: 'static',
  access: { password_login: false },
})

assert.deepEqual(buildCreateVmPayload({
  operatorId: 'nested-access',
  access: {
    username: 'debian',
    sshPublicKey: TEST_SSH_PUBLIC_KEY,
    passwordLogin: true,
  },
}), {
  operator_id: 'nested-access',
  access: {
    cloud_init_user: 'debian',
    ssh_public_key: TEST_SSH_PUBLIC_KEY,
    password_login: false,
  },
})

assert.deepEqual(buildCreateVmInputFromConfig({
  profileId: 'runtime-server',
  network: {
    staticIp: '192.168.2.151',
    prefix: 26,
    gateway: '192.168.2.253',
  },
}, {
  operatorId: 'fallback-operator',
  jobId: 'fallback-job',
  profileId: 'general-vm',
  targetNodeId: 'yoonmanserver2',
}), {
  operatorId: 'fallback-operator',
  jobId: 'fallback-job',
  profileId: 'runtime-server',
  targetNodeId: 'yoonmanserver2',
  storageId: '',
  bridgeId: '',
  staticIp: '192.168.2.151',
  prefix: 26,
  gateway: '192.168.2.253',
  ipMode: 'static',
  templateId: '',
  templateVmid: '',
  templateNodeId: '',
  templateKey: '',
  cloudInitUser: 'yoon',
  sshPublicKey: '',
  passwordLogin: false,
})

const strictTemplateProfile = { templateRequirements: { requireCloudInit: true, requireQemuGuestAgent: true } }
const relaxedTemplateProfile = { templateRequirements: { requireCloudInit: false, requireQemuGuestAgent: false } }
const normalizedTemplates = normalizeTemplateOptions([
  { template_id: 'ubuntu-no-cloudinit', vmid: 9001, node_id: 'node-a', name: 'ubuntu-no-cloudinit', cloud_init_ready: false, guest_agent_ready: true, disk_gb: 50 },
  { template_id: 'ubuntu-no-agent', vmid: 9002, node_id: 'node-a', name: 'ubuntu-no-agent', cloud_init_ready: true, guest_agent_ready: false, disk_gb: 50 },
  { template_id: 'ubuntu-ready', vmid: 9003, node_id: 'node-a', name: 'ubuntu-ready', cloud_init_ready: true, guest_agent_ready: true, disk_gb: 50 },
  { template_id: 'ubuntu-unknown', vmid: 9004, node_id: 'node-a', name: 'ubuntu-unknown', disk_gb: 50 },
])

assert.equal(normalizedTemplates.length, 4, 'all live templates remain listed after normalization')
assert.equal(normalizedTemplates.find((template) => template.templateId === 'ubuntu-ready').cloudInitReady, true)
assert.equal(normalizedTemplates.find((template) => template.templateId === 'ubuntu-ready').guestAgentReady, true)
assert.equal(normalizedTemplates.find((template) => template.templateId === 'ubuntu-unknown').cloudInitReady, false)
assert.equal(normalizedTemplates.find((template) => template.templateId === 'ubuntu-unknown').guestAgentReady, false)

const strictDecoratedTemplates = decorateTemplateOptionsForProfile(normalizedTemplates, strictTemplateProfile)
assert.equal(strictDecoratedTemplates.length, 4, 'disabling templates must not remove them from the option list')
assert.deepEqual(
  strictDecoratedTemplates.find((template) => template.templateId === 'ubuntu-no-cloudinit').requirementFailures.map((failure) => failure.code),
  ['cloud_init_required'],
)
assert.deepEqual(
  strictDecoratedTemplates.find((template) => template.templateId === 'ubuntu-no-agent').requirementFailures.map((failure) => failure.code),
  ['guest_agent_required'],
)
assert.equal(strictDecoratedTemplates.find((template) => template.templateId === 'ubuntu-ready').disabled, false)
assert.equal(selectPreferredTemplate(normalizedTemplates, strictTemplateProfile, 'node-a/9001').templateId, 'ubuntu-ready')
assert.equal(validateTemplateSelection(normalizedTemplates, strictTemplateProfile, 'node-a/9003').ok, true)

const relaxedDecoratedTemplates = decorateTemplateOptionsForProfile(normalizedTemplates, relaxedTemplateProfile)
assert.equal(relaxedDecoratedTemplates.find((template) => template.templateId === 'ubuntu-unknown').disabled, false)

const allInvalidTemplateGuard = validateTemplateSelection(
  normalizedTemplates.filter((template) => template.templateId !== 'ubuntu-ready'),
  strictTemplateProfile,
  '',
)
assert.equal(allInvalidTemplateGuard.ok, false)
assert.match(allInvalidTemplateGuard.reason, /요구사항|템플릿/)

const calls = []
const fakeClient = {
  async getVmCreateReadiness() {
    calls.push(['getVmCreateReadiness'])
    return {
      shared_root: '/Users/yoon/mnt/nfs',
      iac_root: '/Users/yoon/mnt/nfs/IaC',
      terraform_state_root: '/Users/yoon/mnt/nfs/IaC-state/gjallar',
      ready_for_plan: true,
      ready_for_execute: false,
      risk_level: 'yellow',
      checks: [{ code: 'iac_git_repo_available', status: 'fail', level: 'yellow', message: 'IaC root is not a Git checkout yet' }],
      risks: [{ level: 'yellow', code: 'iac_git_repo_missing', message: 'IaC root is not a Git checkout yet' }],
      side_effects: [],
    }
  },
  async createVmDraft(payload) {
    calls.push(['createVmDraft', payload])
    return {
      draft_id: 'draft-job-ui-create',
      job_id: payload.job_id,
      operator_id: payload.operator_id,
      profile_id: payload.profile_id,
      vm_name: 'gjallar-vm-job-ui-create',
      proposed_vmid: 120,
      target_node_id: payload.target_node_id,
      storage_id: payload.storage_id,
      template_id: payload.template_id,
      template_vmid: payload.template_vmid,
      template_node_id: payload.template_node_id,
      hardware: { cpu: 2, memory_mb: 4096, disk_gb: 50 },
      network: {
        ip_mode: payload.ip_mode,
        static_ip: payload.static_ip,
        prefix: payload.prefix,
        gateway: payload.gateway,
        bridge_id: payload.bridge_id,
      },
      access: {
        username: payload.access?.cloud_init_user || 'yoon',
        cloud_init_user: payload.access?.cloud_init_user || 'yoon',
        password_login: false,
        ssh_key_present: Boolean(payload.access?.ssh_public_key),
        ssh_key_valid: Boolean(payload.access?.ssh_public_key),
        fingerprint: payload.access?.ssh_public_key ? TEST_SSH_FINGERPRINT : '',
        source: payload.access?.ssh_public_key ? 'request' : 'backend_default_env',
      },
      terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      first_power_on_included: false,
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
      selected_storage_id: payload.storage_id || 'local-lvm',
      selected_template_id: payload.template_id,
      selected_template_vmid: payload.template_vmid,
      selected_template_node_id: payload.template_node_id,
      selected_bridge_id: payload.bridge_id,
      access: {
        username: payload.access?.cloud_init_user || 'yoon',
        cloud_init_user: payload.access?.cloud_init_user || 'yoon',
        password_login: false,
        ssh_key_present: Boolean(payload.access?.ssh_public_key),
        ssh_key_valid: Boolean(payload.access?.ssh_public_key),
        fingerprint: payload.access?.ssh_public_key ? TEST_SSH_FINGERPRINT : '',
        source: payload.access?.ssh_public_key ? 'request' : 'backend_default_env',
      },
      side_effects: [],
    }
  },
  async planVmDraft(draftId, payload) {
    calls.push(['planVmDraft', draftId, payload])
    return {
      draft_id: draftId,
      job_id: payload.job_id,
      execution_intent: 'dry_run_plan_only',
      profile_id: payload.profile_id,
      vm_name: 'gjallar-vm-job-ui-create',
      vmid: 120,
      target_node_id: payload.target_node_id,
      storage_id: payload.storage_id || 'local-lvm',
      template_id: payload.template_id,
      template_vmid: payload.template_vmid,
      template_node_id: payload.template_node_id,
      hardware: { cpu: 2, memory_mb: 4096, disk_gb: 50 },
      profile_hardware_limits: {
        cpu: { default: 2, min: 1, max: 8 },
        memory_mb: { default: 4096, min: 1024, max: 32768 },
        disk_gb: { default: 50, min: 50, max: 500 },
      },
      network: {
        bridge_id: payload.bridge_id,
        ip_mode: payload.ip_mode,
        static_ip: payload.static_ip,
        prefix: payload.prefix,
        gateway: payload.gateway,
        ip_address: payload.static_ip,
      },
      access: {
        username: payload.access?.cloud_init_user || 'yoon',
        cloud_init_user: payload.access?.cloud_init_user || 'yoon',
        password_login: false,
        ssh_key_present: Boolean(payload.access?.ssh_public_key),
        ssh_key_valid: Boolean(payload.access?.ssh_public_key),
        fingerprint: payload.access?.ssh_public_key ? TEST_SSH_FINGERPRINT : '',
        source: payload.access?.ssh_public_key ? 'request' : 'backend_default_env',
      },
      selected_template: { template_id: payload.template_id, vmid: payload.template_vmid, node_id: payload.template_node_id },
      selected_bridge: { bridge_id: payload.bridge_id, node_id: payload.target_node_id, active: true },
      terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      first_power_on_included: false,
      smoke_timeout_summary: { cloud_init_minutes: 15, guest_agent_minutes: 5, ip_discovery_minutes: 5, ssh_minutes: 5 },
      risk_summary: { level: 'green', red: [], yellow: [] },
      review_confirm: {
        profile_id: payload.profile_id,
        vm_name: 'gjallar-vm-job-ui-create',
        vmid: 120,
        target_node_id: payload.target_node_id,
        storage_id: payload.storage_id || 'local-lvm',
        template_id: payload.template_id,
        template_vmid: payload.template_vmid,
        template_node_id: payload.template_node_id,
        hardware: { cpu: 2, memory_mb: 4096, disk_gb: 50 },
        profile_hardware_limits: {
          cpu: { default: 2, min: 1, max: 8 },
          memory_mb: { default: 4096, min: 1024, max: 32768 },
          disk_gb: { default: 50, min: 50, max: 500 },
        },
        network: {
          bridge_id: payload.bridge_id,
          ip_mode: payload.ip_mode,
          static_ip: payload.static_ip,
          prefix: payload.prefix,
          gateway: payload.gateway,
          ip_address: payload.static_ip,
        },
        access: {
          username: payload.access?.cloud_init_user || 'yoon',
          cloud_init_user: payload.access?.cloud_init_user || 'yoon',
          password_login: false,
          ssh_key_present: Boolean(payload.access?.ssh_public_key),
          ssh_key_valid: Boolean(payload.access?.ssh_public_key),
          fingerprint: payload.access?.ssh_public_key ? TEST_SSH_FINGERPRINT : '',
          source: payload.access?.ssh_public_key ? 'request' : 'backend_default_env',
        },
        selected_template: { template_id: payload.template_id, vmid: payload.template_vmid, node_id: payload.template_node_id },
        selected_bridge: { bridge_id: payload.bridge_id, node_id: payload.target_node_id, active: true },
        terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
        iac_root: '/Users/yoon/mnt/nfs/IaC',
        terraform_state_root: '/Users/yoon/mnt/nfs/IaC-state/gjallar',
        iac_ready_for_plan: true,
        iac_ready_for_execute: false,
        first_power_on_included: false,
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
  async previewVmDraftProxmox(draftId, payload) {
    calls.push(['previewVmDraftProxmox', draftId, payload])
    return {
      job_id: payload.job_id,
      manifest_id: 'vm-job-ui-create',
      clone: {
        endpoint: '/nodes/yoonmanserver2/qemu/9000/clone',
        template_node: 'yoonmanserver2',
        template_vmid: 9000,
        newid: 120,
        name: 'gjallar-vm-job-ui-create',
        target: 'yoonmanserver2',
        storage: 'nas-server',
        full: 1,
      },
      config: { cores: 2, memory: 4096, agent: 'enabled=1', onboot: 0, net0: 'virtio,bridge=vmbr0', ipconfig0: 'ip=192.168.2.149/25,gw=192.168.2.254' },
      post_check: { required_status: 'stopped', powered_on_success_allowed: false },
      proxmox_create_enabled: false,
      proxmox_mutation_enabled: false,
      terraform_apply_enabled: false,
      artifacts: [{ artifact_id: 'artifact-proxmox-preview', type: 'proxmox_create_preview', path: '/tmp/proxmox_create_preview.json' }],
      side_effects: [],
    }
  },
  async createVmDraftProxmox(draftId, payload) {
    calls.push(['createVmDraftProxmox', draftId, payload])
    return {
      job_id: payload.job_id,
      manifest_id: 'vm-job-ui-create',
      manifest_path: 'manifests/vms/vm-job-ui-create.yaml',
      manifest_commit_sha: payload.manifest_commit_sha,
      manifest_status: { phase: 'applied', last_error: '', updated_at: '2026-05-10T00:00:00Z' },
      manifest_status_commit_sha: 'def456',
      proxmox_create_ran: true,
      proxmox_create_status: 'applied',
      proxmox_create_enabled: true,
      proxmox_mutation_enabled: true,
      terraform_apply_enabled: false,
      observed_after: {
        status: 'stopped',
        exists: true,
        fingerprint: { hash: 'sha256:abc456' },
      },
      observed_after_artifact: { artifact_id: 'artifact-observed', type: 'observed_after', path: '/tmp/observed_after.json' },
      side_effects: ['iac_manifest_status_applied', 'proxmox_clone_invoked', 'proxmox_post_check_observed'],
    }
  },
  async commitVmDraftManifest(draftId, payload) {
    calls.push(['commitVmDraftManifest', draftId, payload])
    return {
      execution_intent: 'gitops_commit_only',
      manifest_path: 'manifests/vms/vm-job-ui-create.yaml',
      manifest_status: { phase: 'pending', last_error: '', updated_at: '' },
      commit_sha: 'abc123',
      terraform_apply_enabled: false,
      proxmox_create_enabled: false,
      proxmox_mutation_enabled: false,
      side_effects: ['iac_manifest_written', 'iac_git_commit_created'],
    }
  },
}

const model = await loadCreateVmReviewModel(fakeClient, input)
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft'])
assert.equal(model.readiness.iacRoot, '/Users/yoon/mnt/nfs/IaC')
assert.equal(model.readiness.legacyStateRoot, '/Users/yoon/mnt/nfs/IaC-state/gjallar')
assert.equal(model.readiness.readyForPlan, true)
assert.equal(model.readiness.readyForExecute, false)
assert.equal(model.draft.id, 'draft-job-ui-create')
assert.equal(model.draft.profileId, 'general-vm')
assert.equal(model.draft.storageId, 'nas-server')
assert.equal(model.draft.templateVmid, 9000)
assert.equal(model.preflight.level, 'green')
assert.equal(model.plan.executionIntent, 'dry_run_plan_only')
assert.equal(model.review.vmName, 'gjallar-vm-job-ui-create')
assert.equal(model.review.profileId, 'general-vm')
assert.equal(model.review.profileHardwareLimits.disk_gb.max, 500)
assert.equal(model.review.canApprove, true)
assert.equal(model.review.canPreviewProxmox, true)
assert.equal(model.review.canCommitManifest, false)
assert.equal(model.review.canCreateProxmox, false)
assert.equal(model.review.canExecute, false, 'UI must not expose direct create before manifest commit and final acknowledgement')
assert.equal(model.review.firstPowerOnIncluded, false)
assert.equal(model.review.executeDisabledReason, '실제 VM 생성은 요청 저장 후 Proxmox native create에서만 실행됩니다.')
assert.equal(model.payload.prefix, 25)
assert.equal(model.payload.profile_id, 'general-vm')
assert.equal(model.payload.gateway, '192.168.2.254')
assert.equal('network_id' in model.payload, false)
assert.equal('networkId' in model.payload, false)
assert.equal(model.review.network.static_ip, '192.168.2.149')
assert.equal(model.review.network.prefix, 25)
assert.equal(model.review.network.gateway, '192.168.2.254')
assert.equal(model.payload.access.cloud_init_user, 'ubuntu')
assert.equal(model.payload.access.ssh_public_key, TEST_SSH_PUBLIC_KEY)
assert.equal(model.payload.access.password_login, false)
assert.equal(model.review.access.username, 'ubuntu')
assert.equal(model.review.access.sshKeyPresent, true)
assert.equal(model.review.access.fingerprint, TEST_SSH_FINGERPRINT)
assert.equal(model.review.access.source, 'request')
assert.ok(!JSON.stringify(model.review).includes(TEST_SSH_PUBLIC_KEY.split(' ')[1]))
assert.equal(model.artifacts[0].id, 'artifact-plan')
assert.deepEqual(model.sideEffects, [])

const approval = await approveCreateVmReview(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(approval.canApprove, true)
assert.equal(approval.canExecute, false)
assert.equal(approval.executeDisabledReason, '실제 VM 생성은 요청 저장 후 Proxmox native create에서만 실행됩니다.')
assert.deepEqual(approval.sideEffects, [])

const preview = await previewCreateVmProxmox(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft', 'previewVmDraftProxmox'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.ok(!('run_terraform_plan' in calls.at(-1)[2]))
assert.ok(!('terraform_plan_acknowledged' in calls.at(-1)[2]))
assert.equal(preview.status, 'previewed')
assert.equal(preview.clone.endpoint, '/nodes/yoonmanserver2/qemu/9000/clone')
assert.equal(preview.proxmoxMutationEnabled, false)
assert.deepEqual(preview.sideEffects, [])

model.review.canCommitManifest = true
model.review.canCreateProxmox = true
const commit = await commitCreateVmManifest(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft', 'previewVmDraftProxmox', 'commitVmDraftManifest'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(commit.status, 'committed')
assert.equal(commit.manifestPath, 'manifests/vms/vm-job-ui-create.yaml')
assert.equal(commit.commitSha, 'abc123')
assert.equal(commit.manifestStatus.phase, 'pending')
assert.equal(commit.createEnabled, false)
assert.equal(commit.proxmoxMutationEnabled, false)
assert.deepEqual(commit.sideEffects, ['iac_manifest_written', 'iac_git_commit_created'])

const created = await createVmWithProxmox(fakeClient, model, {
  yellowRiskAcknowledged: false,
  manifestCommitSha: commit.commitSha,
  proxmoxMutationAcknowledged: true,
})
assert.equal(calls.at(-1)[0], 'createVmDraftProxmox')
assert.equal(calls.at(-1)[2].manifest_commit_sha, 'abc123')
assert.equal(calls.at(-1)[2].proxmox_mutation_acknowledged, true)
assert.ok(!('expected_plan_path' in calls.at(-1)[2]))
assert.ok(!('terraform_plan_acknowledged' in calls.at(-1)[2]))
assert.ok(!('terraform_apply_acknowledged' in calls.at(-1)[2]))
assert.equal(created.status, 'applied')
assert.equal(created.createEnabled, true)
assert.equal(created.proxmoxMutationEnabled, true)
assert.equal(created.manifestStatus.phase, 'applied')
assert.equal(created.manifestStatusCommitSha, 'def456')
assert.equal(created.observedAfter.status, 'stopped')
assert.equal(created.observedAfterPath, '/tmp/observed_after.json')
assert.equal(created.fingerprintHash, 'sha256:abc456')

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
assert.match(deniedApproval.operatorMessage, /승인할 수 없습니다|acknowledgement/i)

const source = readFileSync(new URL('../src/utils/createVmFlow.js', import.meta.url), 'utf8')
assert.ok(!source.includes('prepareVmDraftTerraformPlan'), 'active frontend flow must not call Terraform plan helper')
assert.ok(!source.includes('applyVmDraftTerraformPlan'), 'active frontend flow must not call Terraform apply helper')
const wizardSource = readFileSync(new URL('../src/components/CreateInstanceWizard.jsx', import.meta.url), 'utf8')
assert.ok(wizardSource.includes('apiV1Client.listNetworks()'), 'Create VM wizard must load live bridge inventory')
assert.ok(wizardSource.includes('apiV1Client.listProfiles()'), 'Create VM wizard must load profile inventory')
assert.ok(wizardSource.includes('sshPublicKey'), 'Create VM wizard must expose SSH public key input')
assert.ok(wizardSource.includes('cloudInitUser'), 'Create VM wizard must expose cloud-init user input')
assert.ok(!wizardSource.includes('apiV1Client.getNetworkPolicy()'), 'Create VM wizard must not use NetworkPolicy as bridge source')

console.log('createVmFlow native Proxmox contract exercised')
