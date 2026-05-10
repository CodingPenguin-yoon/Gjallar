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
  applyCreateVmTerraformPlan,
  commitCreateVmManifest,
  prepareCreateVmTerraformPlan,
} = await importExpected('../src/utils/createVmFlow.js', 'Create VM PRD flow utility')

const input = {
  operatorId: 'hermes-ui',
  jobId: 'job-ui-create',
  targetNodeId: 'yoonmanserver2',
  storageId: 'nas-server',
  networkId: 'server-net',
  bridgeId: 'vmbr0',
  staticIp: '192.168.2.149',
  ipMode: 'static',
  templateId: 'ubuntu-template',
  templateVmid: 9000,
  templateNodeId: 'yoonmanserver2',
}

assert.deepEqual(buildCreateVmPayload(input), {
  operator_id: 'hermes-ui',
  job_id: 'job-ui-create',
  target_node_id: 'yoonmanserver2',
  storage_id: 'nas-server',
  network_id: 'server-net',
  bridge_id: 'vmbr0',
  static_ip: '192.168.2.149',
  ip_mode: 'static',
  template_id: 'ubuntu-template',
  template_vmid: 9000,
  template_node_id: 'yoonmanserver2',
})

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
      vm_name: 'gjallar-vm-job-ui-create',
      proposed_vmid: 120,
      target_node_id: payload.target_node_id,
      storage_id: payload.storage_id,
      template_id: payload.template_id,
      template_vmid: payload.template_vmid,
      template_node_id: payload.template_node_id,
      hardware: { cpu: 2, memory_mb: 4096, disk_gb: 40 },
      network: { network_id: payload.network_id, ip_mode: payload.ip_mode, static_ip: payload.static_ip, bridge_id: payload.bridge_id },
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
      storage_id: payload.storage_id || 'local-lvm',
      template_id: payload.template_id,
      template_vmid: payload.template_vmid,
      template_node_id: payload.template_node_id,
      hardware: { cpu: 2, memory_mb: 4096, disk_gb: 40 },
      network: { network_id: payload.network_id, bridge_id: payload.bridge_id, ip_mode: payload.ip_mode, ip_address: payload.static_ip },
      terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      first_power_on_included: false,
      smoke_timeout_summary: { cloud_init_minutes: 15, guest_agent_minutes: 5, ip_discovery_minutes: 5, ssh_minutes: 5 },
      risk_summary: { level: 'green', red: [], yellow: [] },
      review_confirm: {
        vm_name: 'gjallar-vm-job-ui-create',
        vmid: 120,
        target_node_id: payload.target_node_id,
        storage_id: payload.storage_id || 'local-lvm',
        template_id: payload.template_id,
        template_vmid: payload.template_vmid,
        template_node_id: payload.template_node_id,
        hardware: { cpu: 2, memory_mb: 4096, disk_gb: 40 },
        network: { network_id: payload.network_id, bridge_id: payload.bridge_id, ip_mode: payload.ip_mode, ip_address: payload.static_ip },
        terraform_state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
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
  async prepareVmDraftTerraformPlan(draftId, payload) {
    calls.push(['prepareVmDraftTerraformPlan', draftId, payload])
    return {
      job_id: payload.job_id,
      manifest_id: 'vm-job-ui-create',
      workspace_dir: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace',
      terraform_dir: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace/terraform',
      backend_config_path: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace/terraform/backend.hcl',
      tfvars_path: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace/terraform/terraform.auto.tfvars.json',
      plan_path: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace/terraform/tfplan',
      state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      commands: [
        ['terraform', 'init', '-input=false', '-backend-config=backend.hcl'],
        ['terraform', 'plan', '-input=false', '-out=tfplan', '-var-file=terraform.auto.tfvars.json'],
      ],
      terraform_plan_ran: payload.run_terraform_plan === true,
      terraform_plan_results: payload.run_terraform_plan ? [{ stdout: 'plan ok', stderr: '', returncode: 0 }] : [],
      terraform_apply_enabled: false,
      proxmox_mutation_enabled: false,
      side_effects: ['terraform_workspace_created'],
    }
  },
  async applyVmDraftTerraformPlan(draftId, payload) {
    calls.push(['applyVmDraftTerraformPlan', draftId, payload])
    return {
      job_id: payload.job_id,
      manifest_id: 'vm-job-ui-create',
      workspace_dir: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace',
      terraform_dir: '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace/terraform',
      state_path: '/tmp/gjallar-state/job-ui-create.tfstate',
      manifest_path: 'manifests/vms/vm-job-ui-create.yaml',
      manifest_commit_sha: payload.manifest_commit_sha,
      manifest_status: { phase: 'applied', last_error: '', updated_at: '2026-05-10T00:00:00Z' },
      manifest_status_commit_sha: 'def456',
      terraform_apply_ran: true,
      terraform_apply_results: [{ stdout: 'apply ok', stderr: '', returncode: 0 }],
      terraform_apply_enabled: true,
      proxmox_mutation_enabled: true,
      side_effects: ['terraform_workspace_created', 'terraform_apply_invoked'],
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
      proxmox_mutation_enabled: false,
      side_effects: ['iac_manifest_written', 'iac_git_commit_created'],
    }
  },
}

const model = await loadCreateVmReviewModel(fakeClient, input)
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft'])
assert.equal(model.readiness.iacRoot, '/Users/yoon/mnt/nfs/IaC')
assert.equal(model.readiness.terraformStateRoot, '/Users/yoon/mnt/nfs/IaC-state/gjallar')
assert.equal(model.readiness.readyForPlan, true)
assert.equal(model.readiness.readyForExecute, false)
assert.equal(model.draft.id, 'draft-job-ui-create')
assert.equal(model.draft.storageId, 'nas-server')
assert.equal(model.draft.templateVmid, 9000)
assert.equal(model.preflight.level, 'green')
assert.equal(model.plan.executionIntent, 'dry_run_plan_only')
assert.equal(model.review.vmName, 'gjallar-vm-job-ui-create')
assert.equal(model.review.canApprove, true)
assert.equal(model.review.canPrepareTerraformPlan, true)
assert.equal(model.review.canCommitManifest, false)
assert.equal(model.review.canApplyTerraform, false)
assert.equal(model.review.canExecute, false, 'UI must not expose execute even if backend approval says can_execute')
assert.equal(model.review.firstPowerOnIncluded, false)
assert.equal(model.review.executeDisabledReason, '실제 VM 생성은 Terraform apply 승인 단계에서만 실행됩니다.')
assert.equal(model.artifacts[0].id, 'artifact-plan')
assert.deepEqual(model.sideEffects, [])

const approval = await approveCreateVmReview(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(approval.canApprove, true)
assert.equal(approval.canExecute, false)
assert.equal(approval.executeDisabledReason, '실제 VM 생성은 Terraform apply 승인 단계에서만 실행됩니다.')
assert.deepEqual(approval.sideEffects, [])

const terraformPlan = await prepareCreateVmTerraformPlan(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft', 'prepareVmDraftTerraformPlan'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(calls.at(-1)[2].run_terraform_plan, false)
assert.equal(calls.at(-1)[2].terraform_plan_acknowledged, false)
assert.equal(terraformPlan.status, 'prepared')
assert.equal(terraformPlan.terraformDir, '/tmp/gjallar-set6-api-preview/job-ui-create/terraform-workspace/terraform')
assert.match(terraformPlan.commandText, /terraform init/)
assert.equal(terraformPlan.planRan, false)
assert.equal(terraformPlan.applyEnabled, false)
assert.equal(terraformPlan.proxmoxMutationEnabled, false)
assert.deepEqual(terraformPlan.sideEffects, ['terraform_workspace_created'])

const terraformPlanRun = await prepareCreateVmTerraformPlan(fakeClient, model, {
  yellowRiskAcknowledged: false,
  runTerraformPlan: true,
  terraformPlanAcknowledged: true,
})
assert.equal(calls.at(-1)[0], 'prepareVmDraftTerraformPlan')
assert.equal(calls.at(-1)[2].run_terraform_plan, true)
assert.equal(calls.at(-1)[2].terraform_plan_acknowledged, true)
assert.equal(terraformPlanRun.status, 'planned')
assert.equal(terraformPlanRun.planRan, true)

model.review.canCommitManifest = true
const commit = await commitCreateVmManifest(fakeClient, model, { yellowRiskAcknowledged: false })
assert.deepEqual(calls.map((call) => call[0]), ['getVmCreateReadiness', 'createVmDraft', 'preflightVmDraft', 'planVmDraft', 'approveVmDraft', 'prepareVmDraftTerraformPlan', 'prepareVmDraftTerraformPlan', 'commitVmDraftManifest'])
assert.equal(calls.at(-1)[2].plan_artifact_id, 'artifact-plan')
assert.equal(calls.at(-1)[2].review_summary_checksum, 'sha256:abc123')
assert.equal(commit.status, 'committed')
assert.equal(commit.manifestPath, 'manifests/vms/vm-job-ui-create.yaml')
assert.equal(commit.commitSha, 'abc123')
assert.equal(commit.manifestStatus.phase, 'pending')
assert.equal(commit.applyEnabled, false)
assert.equal(commit.proxmoxMutationEnabled, false)
assert.deepEqual(commit.sideEffects, ['iac_manifest_written', 'iac_git_commit_created'])

const apply = await applyCreateVmTerraformPlan(fakeClient, model, {
  yellowRiskAcknowledged: false,
  manifestCommitSha: commit.commitSha,
  expectedPlanPath: terraformPlanRun.planPath,
  terraformPlanAcknowledged: true,
  terraformApplyAcknowledged: true,
  proxmoxMutationAcknowledged: true,
})
assert.equal(calls.at(-1)[0], 'applyVmDraftTerraformPlan')
assert.equal(calls.at(-1)[2].manifest_commit_sha, 'abc123')
assert.equal(calls.at(-1)[2].expected_plan_path, terraformPlanRun.planPath)
assert.equal(calls.at(-1)[2].terraform_plan_acknowledged, true)
assert.equal(calls.at(-1)[2].terraform_apply_acknowledged, true)
assert.equal(calls.at(-1)[2].proxmox_mutation_acknowledged, true)
assert.equal(apply.status, 'applied')
assert.equal(apply.applyEnabled, true)
assert.equal(apply.proxmoxMutationEnabled, true)
assert.equal(apply.manifestStatus.phase, 'applied')
assert.equal(apply.manifestStatusCommitSha, 'def456')
assert.match(apply.stdout, /apply ok/)

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
assert.match(source, /새 VM 만들기/)
assert.match(source, /템플릿/)
assert.match(source, /스토리지/)
assert.match(source, /네트워크/)
assert.match(source, /listStorage/)
assert.match(source, /검토 시작/)
assert.match(source, /검토 내용 승인/)
assert.match(source, /실행 준비 파일 만들기/)
assert.match(source, /생성 변경 미리보기/)
assert.match(source, /생성 요청 저장/)
assert.match(source, /꺼진 상태로 VM 만들기/)
assert.match(source, /Proxmox에 꺼진 상태의 VM을 실제로 만드는 것을 승인합니다/)
assert.match(source, /useNavigate/)
assert.match(source, /\/jobs\?job=/)
assert.doesNotMatch(source, /요청 보관/)
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
  forbidden('Proxmox', ' write'),
  forbidden('window.', 'confirm'),
  forbidden('window.', 'prompt'),
]) {
  assert.ok(!source.toLowerCase().includes(blocked.toLowerCase()), `Create VM wizard must not expose legacy/live term: ${blocked}`)
}

console.log('createVmFlow RED contract exercised')
