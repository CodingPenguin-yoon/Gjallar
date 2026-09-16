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
  power_policy: 'stopped',
  first_power_on_included: false,
})
assert.equal('network_id' in buildCreateVmPayload(input), false)
assert.equal('ssh_public_key' in buildCreateVmPayload(input), false)
assert.equal(buildCreateVmPayload({ ...input, powerPolicy: 'boot_and_verify' }).first_power_on_included, true)
assert.equal(buildCreateVmPayload({ ...input, powerPolicy: 'boot_and_verify' }).power_policy, 'boot_and_verify')

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
  power_policy: 'stopped',
  first_power_on_included: false,
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
  power_policy: 'stopped',
  first_power_on_included: false,
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
  creationMode: 'profile',
  vmid: '',
  vmName: '',
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
  cloudInitUser: '',
  sshPublicKey: '',
  passwordLogin: false,
  powerPolicy: 'stopped',
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
      first_power_on_included: payload.first_power_on_included,
      power_policy: payload.power_policy,
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
      operation_id: payload.job_id,
      operation: {
        operation_id: payload.job_id,
        operation_type: 'vm_create',
        status: 'awaiting_approval',
        target_id: 'vmid:120',
      },
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
      first_power_on_included: payload.first_power_on_included,
      power_policy: payload.power_policy,
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
        first_power_on_included: payload.first_power_on_included,
        power_policy: payload.power_policy,
        smoke_timeout_summary: { cloud_init_minutes: 15, guest_agent_minutes: 5, ip_discovery_minutes: 5, ssh_minutes: 5 },
        risk_summary: { level: 'green', red: [], yellow: [] },
        plan_artifact_id: 'artifact-plan',
        planned_git_diff_summary: '1 generated manifest',
        review_summary_checksum: 'sha256:abc123',
      },
      artifacts: [{ artifact_id: 'artifact-plan', type: 'plan', path: 'db://job-artifacts/artifact-plan', storage_backend: 'db' }],
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
      operation_id: payload.job_id,
      operation: { operation_id: payload.job_id, operation_type: 'vm_create', status: 'approved' },
    }
  },
  async previewVmDraftProxmox(draftId, payload) {
    calls.push(['previewVmDraftProxmox', draftId, payload])
    return {
      job_id: payload.job_id,
      operation_id: payload.job_id,
      operation: { operation_id: payload.job_id, operation_type: 'vm_create', status: 'approved' },
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
      artifacts: [{ artifact_id: 'artifact-proxmox-preview', type: 'proxmox_create_preview', path: 'db://job-artifacts/artifact-proxmox-preview', storage_backend: 'db' }],
      side_effects: [],
    }
  },
  async createVmDraftProxmox(draftId, payload) {
    calls.push(['createVmDraftProxmox', draftId, payload])
    return {
      job_id: payload.job_id,
      operation_id: payload.job_id,
      operation: { operation_id: payload.job_id, operation_type: 'vm_create', status: 'succeeded' },
      manifest_id: 'vm-job-ui-create',
      proxmox_preview: {
        clone: { endpoint: '/nodes/yoonmanserver2/qemu/9000/clone' },
      },
      proxmox_create_ran: true,
      proxmox_create_status: 'applied',
      proxmox_create_enabled: true,
      proxmox_mutation_enabled: true,
      observed_after: {
        status: 'stopped',
        exists: true,
        fingerprint: { hash: 'sha256:abc456' },
      },
      observed_after_artifact: { artifact_id: 'artifact-observed', type: 'observed_after', path: 'db://job-artifacts/artifact-observed', storage_backend: 'db' },
      side_effects: ['proxmox_clone_invoked', 'proxmox_post_check_observed'],
    }
  },
}

const model = await loadCreateVmReviewModel(fakeClient, input)
assert.deepEqual(calls.map((call) => call[0]), ['createVmDraft', 'preflightVmDraft', 'planVmDraft'])
assert.equal(model.draft.id, 'draft-job-ui-create')
assert.equal(model.draft.profileId, 'general-vm')
assert.equal(model.draft.storageId, 'nas-server')
assert.equal(model.draft.templateVmid, 9000)
assert.equal(model.preflight.level, 'green')
assert.equal(model.plan.executionIntent, 'dry_run_plan_only')
assert.equal(model.operation.id, 'job-ui-create')
assert.equal(model.operation.type, 'vm_create')
assert.equal(model.operation.status, 'awaiting_approval')
assert.equal(model.review.vmName, 'gjallar-vm-job-ui-create')
assert.equal(model.review.profileId, 'general-vm')
assert.equal(model.review.profileHardwareLimits.disk_gb.max, 500)
assert.equal(model.review.canApprove, true)
assert.equal(model.review.canPreviewProxmox, true)
assert.equal(model.review.canCommitManifest, false)
assert.equal(model.review.canCreateProxmox, true)
assert.equal(model.review.canExecute, false, 'UI must not expose direct create without final acknowledgement')
assert.equal(model.review.firstPowerOnIncluded, false)
assert.equal(model.review.powerPolicy, 'stopped')
assert.equal(model.review.executeDisabledReason, '실제 VM 생성은 승인과 최종 체크 후 Proxmox native create에서만 실행됩니다.')
assert.equal(model.payload.prefix, 25)
assert.equal(model.payload.profile_id, 'general-vm')
assert.equal(model.payload.gateway, '192.168.2.254')
assert.equal(model.payload.power_policy, 'stopped')
assert.equal(model.payload.first_power_on_included, false)
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
assert.deepEqual(calls.map((call) => call[0]), ['createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(approval.canApprove, true)
assert.equal(approval.canExecute, false)
assert.equal(approval.operationId, 'job-ui-create')
assert.equal(approval.executeDisabledReason, '실제 VM 생성은 승인과 최종 체크 후 Proxmox native create에서만 실행됩니다.')
assert.deepEqual(approval.sideEffects, [])

const preview = await previewCreateVmProxmox(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft', 'previewVmDraftProxmox'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.ok(!('run_terraform_plan' in calls.at(-1)[2]))
assert.ok(!('terraform_plan_acknowledged' in calls.at(-1)[2]))
assert.equal(preview.status, 'previewed')
assert.equal(preview.clone.endpoint, '/nodes/yoonmanserver2/qemu/9000/clone')
assert.equal(preview.proxmoxMutationEnabled, false)
assert.equal(preview.operationId, 'job-ui-create')
assert.deepEqual(preview.sideEffects, [])

model.review.canCreateProxmox = true
const created = await createVmWithProxmox(fakeClient, model, {
  yellowRiskAcknowledged: false,
  proxmoxMutationAcknowledged: true,
})
assert.equal(calls.at(-1)[0], 'createVmDraftProxmox')
assert.equal('manifest_commit_sha' in calls.at(-1)[2], false)
assert.equal(calls.at(-1)[2].proxmox_mutation_acknowledged, true)
assert.ok(!('expected_plan_path' in calls.at(-1)[2]))
assert.ok(!('terraform_plan_acknowledged' in calls.at(-1)[2]))
assert.ok(!('terraform_apply_acknowledged' in calls.at(-1)[2]))
assert.equal(created.status, 'applied')
assert.equal(created.createEnabled, true)
assert.equal(created.proxmoxMutationEnabled, true)
assert.equal(created.observedAfter.status, 'stopped')
assert.equal(created.observedAfterPath, '')
assert.equal(created.observedAfterArtifactId, 'artifact-observed')
assert.equal(created.fingerprintHash, 'sha256:abc456')
assert.equal(created.operationId, 'job-ui-create')
assert.equal(created.operation.status, 'succeeded')

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
assert.ok(!source.includes('commitVmDraftManifest'), 'active frontend flow must not call legacy GitOps execute helper')
const wizardSource = readFileSync(new URL('../src/components/CreateInstanceWizard.jsx', import.meta.url), 'utf8')
assert.ok(wizardSource.includes('apiV1Client.listNetworks()'), 'Create VM wizard must load live bridge inventory')
assert.ok(wizardSource.includes('apiV1Client.listProfiles()'), 'Create VM wizard must load profile inventory')
assert.ok(!wizardSource.includes('profilesReady'), 'Direct template input must not depend on profile availability')
assert.ok(wizardSource.includes('presetUnavailable'), 'A selected missing preset must remain blocked')
assert.ok(wizardSource.includes('profileError'), 'Create VM wizard must surface profile API failure or empty state')
assert.ok(wizardSource.includes('sshPublicKey'), 'Create VM wizard must expose SSH public key input')
assert.ok(wizardSource.includes('cloudInitUser'), 'Create VM wizard must expose cloud-init user input')
assert.ok(wizardSource.includes('/operations/${encodeURIComponent(operationId)}'), 'Create VM must open the common Operation timeline when linkage exists')
assert.ok(wizardSource.includes('/operations/jobs?job=${encodeURIComponent(jobId)}'), 'Create VM must retain the legacy Jobs fallback')
assert.match(wizardSource, /compatibility=operation/, 'Create VM Jobs fallback must identify the compatibility view')
assert.ok(!wizardSource.includes(['apiV1Client.getNetwork', 'Policy()'].join('')), 'Create VM wizard must use live bridge inventory as bridge source')

console.log('createVmFlow native Proxmox contract exercised')

const directPayload = buildCreateVmPayload({ creationMode: 'template', profileId: 'general-vm', templateVmid: 9001, templateNodeId: 'node-b', hardware: { cpu: 4, memoryMb: 8192, diskGb: 80 } })
assert.equal(directPayload.creation_mode, 'template')
assert.equal('profile_id' in directPayload, false)
assert.equal(directPayload.template_node_id, 'node-b')
assert.deepEqual(directPayload.hardware_overrides, { cpu: 4, memory_mb: 8192, disk_gb: 80 })

assert.match(wizardSource, /IP를 읽지 못한 기존 VM/, 'Guest agent observation must name the existing VMs whose IP could not be read')
assert.match(wizardSource, /\{check\.message\}/, 'Observation checks must explain mode-specific risk')

assert.equal(buildCreateVmPayload({vmid: '4321', vmName: 'app-server-01'}).vmid, '4321')
assert.equal(buildCreateVmPayload({vmid: '4321', vmName: 'app-server-01'}).vm_name, 'app-server-01')
assert.ok(!('vmid' in buildCreateVmPayload({vmid: ''})))
assert.equal(buildCreateVmInputFromConfig({vmid: '4321', vmName: 'app-server-01'}).vmid, '4321')

const vmNamePattern = wizardSource.match(/pattern="([^"]+)"/)[1]
const vmNameRegex = new RegExp(`^(?:${vmNamePattern})$`, 'v')
assert.ok(vmNameRegex.test('app-server-01'))
assert.ok(!vmNameRegex.test('bad name'))
assert.ok(!vmNameRegex.test('bad_name'))

const stalePreflight = {
  risk_level: 'red',
  checks: [{ code: 'stale_observation', status: 'fail', level: 'red' }],
  risks: [{ code: 'stale_observation' }],
  side_effects: [],
}
const staticIpCheck = {
  code: 'static_ip_available',
  status: 'warn',
  level: 'yellow',
  detail: {
    static_ip: '192.168.2.149',
    result: 'unverified',
    conflicts: [],
    inventory: { status: 'no_conflict_observed', guest_agent_complete: false, failed_targets: ['node-a:101'] },
    ping: { status: 'no_reply', reason: 'no_echo_reply', source: 'icmp', execution_location: 'gjallar_backend' },
  },
}
const reviewedPreflight = { risk_level: 'yellow', checks: [staticIpCheck], risks: [{ code: 'static_ip_unverified' }], side_effects: [] }
const planSnapshot = await fakeClient.planVmDraft('draft-job-ui-create', buildCreateVmPayload(input))
const latestObservationModel = await loadCreateVmReviewModel({
  ...fakeClient,
  async preflightVmDraft() { return stalePreflight },
  async planVmDraft() { return { ...planSnapshot, preflight: reviewedPreflight, risk_summary: { level: 'yellow', yellow: reviewedPreflight.risks } } },
}, input)
assert.equal(latestObservationModel.preflight.level, 'yellow')
assert.deepEqual(latestObservationModel.preflight.checks, [staticIpCheck], 'The displayed evidence must match the approved plan, rather than the earlier ping result')
assert.deepEqual(latestObservationModel.preflight.risks, reviewedPreflight.risks)
assert.equal(latestObservationModel.review.canApprove, true)
assert.equal(latestObservationModel.review.requiresStaticIpConfirmation, true)
assert.match(wizardSource, /model\.review\.requiresStaticIpConfirmation/, 'Unverified static IP must select the explicit IP confirmation label')
assert.match(wizardSource, /입력한 IP는 제가 직접 확보한 IP입니다/, 'Yellow acknowledgement must include the operator confirmation of IP allocation')

const conflictingCheck = {
  ...staticIpCheck,
  status: 'fail',
  level: 'red',
  detail: { ...staticIpCheck.detail, result: 'in_use', ping: { ...staticIpCheck.detail.ping, status: 'reply', reason: 'echo_reply' } },
}
const newlyConflictingModel = await loadCreateVmReviewModel({
  ...fakeClient,
  async preflightVmDraft() { return reviewedPreflight },
  async planVmDraft() {
    return { ...planSnapshot, preflight: { risk_level: 'red', checks: [conflictingCheck] }, risk_summary: { level: 'red', red: [{ code: 'static_ip_in_use' }] } }
  },
}, input)
assert.deepEqual(newlyConflictingModel.preflight.checks, [conflictingCheck], 'A newly received ping response must replace the earlier unverified result')
assert.equal(newlyConflictingModel.review.canApprove, false)
assert.equal(newlyConflictingModel.review.requiresStaticIpConfirmation, false)
assert.equal(model.review.requiresStaticIpConfirmation, false, 'Legacy plan responses without embedded preflight must retain their original evidence')

await approveCreateVmReview(fakeClient, latestObservationModel, { yellowRiskAcknowledged: true })
assert.equal(calls.at(-1)[2].yellow_risk_acknowledged, true, 'IP confirmation must use the existing acknowledgement contract')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
