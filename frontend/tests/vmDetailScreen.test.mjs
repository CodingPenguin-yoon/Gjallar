import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  buildVmDetailModel,
  loadVmDetailModel,
  VM_OPERATION_QUERY_LIMIT,
} = await import('../src/features/workloads/detail/model.js')
const {
  insightFindingPath,
  operationsTargetPath,
  vmDetailPath,
  vmDetailPathFromTarget,
  vmidFromTarget,
  vmTargetId,
  workloadActionPath,
} = await import('../src/shared/navigation/targetPaths.js')

const vm = {
  vmid: 306,
  name: 'app-306',
  node_id: 'node-a',
  status: 'stopped',
  template: false,
  cpu: 4,
  memory_mb: 8192,
  disk_gb: 64,
  ip_addresses: ['192.168.2.30'],
  guest_agent: { available: true, ip_addresses: ['192.168.2.30'] },
  tags: ['production'],
  storage_id: 'local-lvm',
  disks: [{ device: 'scsi0', size_gb: 64, storage_id: 'local-lvm' }],
}

const vmMeta = {
  source: 'live_read_only',
  observed_at: '2026-08-26T01:00:00Z',
  freshness: 'fresh',
  availability: {
    available: true,
    complete: true,
    sources: {
      vm_config: { available: true, complete: true, expected_targets: 1, observed_targets: 1, failed_targets: [] },
      guest_agent: { available: true, complete: true, expected_targets: 0, observed_targets: 0, failed_targets: [] },
      vm_detail: { available: true, complete: true, expected_targets: 1, observed_targets: 1, failed_targets: [] },
    },
  },
}

function section(category, findings = []) {
  return {
    status: findings.length ? 'attention' : 'ready',
    available: true,
    source: `${category}-source`,
    observed_at: '2026-08-26T01:00:00Z',
    freshness: 'fresh',
    rule_version: `${category}.v1`,
    summary: { finding_count: findings.length },
    findings,
    read_only: true,
    allowed_actions: [],
  }
}

const exactFinding = {
  finding_id: 'readiness-306',
  severity: 'warning',
  status: 'active',
  code: 'guest_agent_unavailable',
  title: 'Guest agent unavailable',
  message: 'Review agent evidence.',
  target: { type: 'proxmox_vm', id: 'vmid:306' },
  source: 'proxmox_inventory',
  observed_at: '2026-08-26T01:00:00Z',
  freshness: 'fresh',
  rule_version: 'readiness.v1',
  evidence: { vmid: 306 },
  read_only: true,
  allowed_actions: [],
}

const insights = {
  generated_at: '2026-08-26T01:00:00Z',
  status: 'attention',
  execution_mode: 'observe_only',
  read_only: true,
  allowed_actions: [],
  connection: { state: 'connected' },
  sections: {
    risk: section('risk'),
    readiness: section('readiness', [exactFinding, { ...exactFinding, finding_id: 'readiness-307', target: { type: 'proxmox_vm', id: 'vmid:307' } }]),
    capacity: section('capacity'),
    placement: section('placement'),
  },
}

const operations = [
  {
    operation_id: 'operation-new', operation_type: 'vm_start', status: 'succeeded',
    target_type: 'proxmox_vm', target_id: 'vmid:306', current_stage: 'verification',
    updated_at: '2026-08-26T02:00:00Z', actor: { username: 'operator' },
  },
  {
    operation_id: 'operation-old', operation_type: 'vm_shutdown', status: 'succeeded',
    target_type: 'proxmox_vm', target_id: 'vmid:306', current_stage: 'verification',
    updated_at: '2026-08-26T01:00:00Z', actor: { username: 'operator' },
  },
  {
    operation_id: 'operation-other', operation_type: 'vm_start', status: 'succeeded',
    target_type: 'proxmox_vm', target_id: 'vmid:307', current_stage: 'verification',
    updated_at: '2026-08-26T03:00:00Z', actor: { username: 'operator' },
  },
]

const model = buildVmDetailModel({ requestedVmid: '306', vm, vmMeta, insights, operations })
assert.equal(model.vm.vmid, 306)
assert.equal(model.vm.targetType, 'proxmox_vm')
assert.equal(model.vm.targetId, 'vmid:306')
assert.deepEqual(model.vm.allowedActions, ['start'])
assert.deepEqual(model.findings.map((finding) => finding.id), ['readiness-306'])
assert.deepEqual(model.operations.map((operation) => operation.id), ['operation-new', 'operation-old'])
assert.equal(model.context.insightsStatus, 'available')
assert.equal(model.context.findingCoverageComplete, true)
assert.equal(model.context.operationsStatus, 'available')
assert.equal(model.context.operationQueryLimit, VM_OPERATION_QUERY_LIMIT)
assert.equal(model.observation.status, 'available')
assert.equal(model.observation.freshness, 'fresh')
assert.equal(model.observation.sources.vmConfig.status, 'available')
assert.equal(model.observation.sources.guestAgent.status, 'not_applicable')

assert.throws(
  () => buildVmDetailModel({ requestedVmid: 306, vm: { ...vm, vmid: 307 } }),
  /일치하지 않습니다/,
  'Exact VM context must reject a mismatched inventory identity',
)
assert.throws(() => buildVmDetailModel({ requestedVmid: '../306', vm }), /VMID/)

const calls = []
let progressiveModel = null
const loaded = await loadVmDetailModel({
  getVmWithMeta: async (vmid) => {
    calls.push(['getVmWithMeta', vmid])
    return { data: vm, meta: vmMeta }
  },
  getInsights: async () => {
    calls.push(['getInsights'])
    return insights
  },
  listOperations: async (filters) => {
    calls.push(['listOperations', filters])
    return operations
  },
}, '306', { onVmLoaded: (next) => { progressiveModel = next } })

assert.deepEqual(calls, [
  ['getVmWithMeta', 306],
  ['getInsights'],
  ['listOperations', { target_type: 'proxmox_vm', target_id: 'vmid:306', limit: VM_OPERATION_QUERY_LIMIT }],
])
assert.equal(progressiveModel.vm.targetId, 'vmid:306')
assert.equal(progressiveModel.context.insightsStatus, 'loading')
assert.equal(progressiveModel.context.operationsStatus, 'loading')
assert.equal(loaded.findings.length, 1)
assert.equal(loaded.operations.length, 2)

const partial = await loadVmDetailModel({
  getVmWithMeta: async () => ({ data: vm, meta: vmMeta }),
  getInsights: async () => { throw new Error('insights unavailable') },
  listOperations: async () => operations,
}, 306)
assert.equal(partial.vm.name, 'app-306', 'Exact VM state must survive optional Insights failure')
assert.equal(partial.context.insightsStatus, 'unavailable')
assert.equal(partial.context.operationsStatus, 'available')

const failedSourceMeta = {
  ...vmMeta,
  freshness: 'partial',
  availability: {
    available: true,
    complete: false,
    sources: {
      vm_config: { available: false, complete: false, expected_targets: 1, observed_targets: 0, failed_targets: ['node-a:306'] },
      guest_agent: { available: false, complete: false, expected_targets: 1, observed_targets: 0, failed_targets: ['node-a:306'] },
      vm_detail: { available: false, complete: false, expected_targets: 1, observed_targets: 0, failed_targets: ['node-a:306'] },
    },
  },
}
const failedSources = buildVmDetailModel({
  requestedVmid: 306,
  vm: { ...vm, status: 'running', ip_addresses: [], guest_agent: { available: false, ip_addresses: [] }, disks: [], tags: [] },
  vmMeta: failedSourceMeta,
  insights,
  operations,
})
assert.equal(failedSources.observation.status, 'partial')
assert.equal(failedSources.observation.freshness, 'partial')
assert.equal(failedSources.observation.sources.vmConfig.status, 'unavailable')
assert.equal(failedSources.observation.sources.guestAgent.status, 'unavailable')
assert.equal(failedSources.observation.sources.vmDetail.status, 'unavailable')
assert.deepEqual(failedSources.observation.sources.vmConfig.failedTargets, ['node-a:306'])

const uncertainInsights = {
  ...insights,
  sections: {
    risk: section('risk'),
    readiness: {
      ...section('readiness'),
      status: 'unknown',
      freshness: 'partial',
    },
    capacity: section('capacity'),
    placement: section('placement'),
  },
}
const uncertainFindingAbsence = buildVmDetailModel({
  requestedVmid: 306,
  vm,
  vmMeta,
  insights: uncertainInsights,
  operations,
})
assert.equal(uncertainFindingAbsence.findings.length, 0)
assert.equal(uncertainFindingAbsence.context.insightsStatus, 'partial')
assert.deepEqual(uncertainFindingAbsence.context.uncertainInsightCategories, ['readiness'])
assert.deepEqual(uncertainFindingAbsence.context.truncatedInsightCategories, [])
assert.equal(uncertainFindingAbsence.context.insightsTruncated, false)
assert.equal(uncertainFindingAbsence.context.findingCoverageComplete, false)

const truncatedInsights = {
  ...insights,
  sections: {
    risk: section('risk'),
    readiness: section('readiness'),
    capacity: section('capacity'),
    placement: {
      ...section('placement'),
      summary: { finding_count: 10, returned_finding_count: 0, truncated: true },
    },
  },
}
const truncatedFindingAbsence = buildVmDetailModel({
  requestedVmid: 306,
  vm,
  vmMeta,
  insights: truncatedInsights,
  operations,
})
assert.equal(truncatedFindingAbsence.findings.length, 0)
assert.equal(truncatedFindingAbsence.context.insightsStatus, 'available')
assert.deepEqual(truncatedFindingAbsence.context.uncertainInsightCategories, [])
assert.deepEqual(truncatedFindingAbsence.context.truncatedInsightCategories, ['placement'])
assert.equal(truncatedFindingAbsence.context.insightsTruncated, true)
assert.equal(truncatedFindingAbsence.context.findingCoverageComplete, false)

assert.equal(vmTargetId('0306'), 'vmid:306')
assert.equal(vmidFromTarget('proxmox_vm', 'vmid:306'), '306')
assert.equal(vmidFromTarget('vm', '306'), '306', 'Known compatibility VM targets may still deep-link exactly')
assert.equal(vmidFromTarget('job', '306'), null)
assert.equal(vmDetailPath(306), '/instances/306')
assert.equal(vmDetailPathFromTarget('proxmox_vm', 'vmid:306'), '/instances/306')
assert.equal(vmDetailPathFromTarget('proxmox_vm', 'name:app-306'), null)
assert.equal(
  insightFindingPath({ category: 'readiness', id: 'readiness-306', targetType: 'proxmox_vm', targetId: 'vmid:306' }),
  '/insights/readiness?target_type=proxmox_vm&target_id=vmid%3A306&finding=readiness-306',
)
assert.equal(operationsTargetPath('proxmox_vm', 'vmid:306'), '/operations?target_type=proxmox_vm&target_id=vmid%3A306')
assert.equal(workloadActionPath(306, 'start'), '/instances?vmid=306&action=start')
assert.equal(workloadActionPath(306, 'delete'), '/instances', 'Unsupported mutations must not gain a deep-link entry')

const app = readFileSync(new URL('../src/app/App.jsx', import.meta.url), 'utf8')
const page = readFileSync(new URL('../src/pages/workloads/VmDetailPage.jsx', import.meta.url), 'utf8')
const detail = readFileSync(new URL('../src/features/workloads/detail/VmDetail.jsx', import.meta.url), 'utf8')
const detailModel = readFileSync(new URL('../src/features/workloads/detail/model.js', import.meta.url), 'utf8')
const inventory = readFileSync(new URL('../src/features/workloads/inventory/WorkloadInventory.jsx', import.meta.url), 'utf8')
const insightsExplorer = readFileSync(new URL('../src/features/insights/InsightsExplorer.jsx', import.meta.url), 'utf8')
const insightsModel = readFileSync(new URL('../src/features/insights/model.js', import.meta.url), 'utf8')
const operationsList = readFileSync(new URL('../src/pages/operations/OperationsListPage.jsx', import.meta.url), 'utf8')

assert.match(app, /path="\/instances\/:vmid" element=\{vmDetailRoute\}/)
assert.match(app, /inventoryRoute\([\s\S]*<VmDetailPage canMutate=\{canMutate\}/, 'Exact VM reads may survive partial inventory while mutations keep their separate live gate')
assert.match(page, /<VmDetail canMutate=\{canMutate\}/)
assert.match(detailModel, /client\.getVmWithMeta\(Number\(exactVmid\)\)/)
assert.match(detailModel, /target_type: 'proxmox_vm'/)
assert.match(detailModel, /target_id: initialModel\.vm\.targetId/)
assert.match(detail, /VM 작업/)
assert.match(detail, /빈 값은 실제 자원 부재를 뜻하지 않습니다/)
assert.match(detail, /findingCoverageComplete/)
assert.match(detail, /active finding 부재를 확정할 수 없습니다/)
assert.match(detail, /insightFindingPath\(finding\)/)
assert.match(detail, /encodeURIComponent\(operation\.id\)/)
assert.doesNotMatch(detail, /apiV1Client\.(?:startVm|shutdownVm)\(/, 'VM detail must reuse the existing Workloads acknowledgement flow')
assert.match(inventory, /vmDetailPath\(vm\.vmid\)/)
assert.match(inventory, /insightFindingPath\(primaryFinding\)/)
assert.match(inventory, /requestedAction === 'start'/)
assert.match(insightsExplorer, /vmDetailPathFromTarget\(finding\.targetType, finding\.targetId\)/)
assert.match(insightsModel, /finding\.targetType === targetType/)
assert.match(insightsExplorer, /selectExactTargetFindingView/)
assert.match(operationsList, /target_type: requestedTargetType, target_id: requestedTargetId/)
assert.match(operationsList, /vmDetailPathFromTarget\(operation\.targetType, operation\.targetId\)/)

console.log('exact VM context and target-preserving deep-link contract exercised')

const unrelatedFailure = buildVmDetailModel({requestedVmid: 306, vm, vmMeta: {
  ...vmMeta, availability: {...vmMeta.availability, complete: false},
}})
assert.equal(unrelatedFailure.observation.status, 'available', 'Other resources must not degrade an observed VM')
