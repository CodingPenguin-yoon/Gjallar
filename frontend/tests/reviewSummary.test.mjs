import assert from 'node:assert/strict'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { buildReviewConfirmSummary } = await importExpected(
  '../src/utils/reviewSummary.js',
  'Review & Confirm summary utility',
)

const summary = buildReviewConfirmSummary({
  vmName: 'gjallar-vm-demo',
  vmid: 120,
  targetNode: 'yoonmanserver2',
  storage: 'local-lvm',
  template: 'ubuntu-template',
  hardware: { cpu: 2, memoryMb: 4096, diskGb: 40 },
  network: { mode: 'static', bridge: 'vmbr0' },
  terraformStatePath: '/var/lib/gjallar/test-state.tfstate',
  firstPowerOnIncluded: true,
  smokeTimeoutSummary: 'cloud-init 15m, guest-agent 5m, IP 5m, SSH 5m',
  risks: [{ level: 'red', code: 'bridge_missing' }],
  planArtifactLink: '/api/v1/jobs/job-1/artifacts/plan',
  plannedGitDiffSummary: '1 VM manifest, 1 generated file',
})

assert.deepEqual(
  summary.requiredItems.map((item) => item.id),
  [
    'vm_name',
    'vmid',
    'target_node',
    'storage',
    'template',
    'hardware',
    'network_ip',
    'terraform_state_path',
    'first_power_on',
    'smoke_timeout_summary',
    'risk_summary',
    'plan_artifact_link',
    'planned_git_diff_summary',
  ],
)
assert.equal(summary.canApprove, false)
assert.equal(summary.canExecute, false)

const incompleteSummary = buildReviewConfirmSummary({ risks: [] })
assert.equal(incompleteSummary.canApprove, false)
assert.equal(incompleteSummary.canExecute, false)
assert.match(incompleteSummary.decisionReason, /required|missing/i)

const missingHardwareSummary = buildReviewConfirmSummary({
  vmName: 'gjallar-vm-demo',
  vmid: 120,
  targetNode: 'yoonmanserver2',
  storage: 'local-lvm',
  template: 'ubuntu-template',
  network: { mode: 'static', bridge: 'vmbr0' },
  terraformStatePath: '/var/lib/gjallar/test-state.tfstate',
  firstPowerOnIncluded: true,
  smokeTimeoutSummary: 'cloud-init 15m',
  risks: [],
  planArtifactLink: '/api/v1/jobs/job-1/artifacts/plan',
  plannedGitDiffSummary: '1 VM manifest',
})
assert.equal(missingHardwareSummary.canApprove, false)
assert.ok(missingHardwareSummary.missingRequiredItemIds.includes('hardware'))

const missingNetworkSummary = buildReviewConfirmSummary({
  vmName: 'gjallar-vm-demo',
  vmid: 120,
  targetNode: 'yoonmanserver2',
  storage: 'local-lvm',
  template: 'ubuntu-template',
  hardware: { cpu: 2, memoryMb: 4096, diskGb: 40 },
  terraformStatePath: '/var/lib/gjallar/test-state.tfstate',
  firstPowerOnIncluded: true,
  smokeTimeoutSummary: 'cloud-init 15m',
  risks: [],
  planArtifactLink: '/api/v1/jobs/job-1/artifacts/plan',
  plannedGitDiffSummary: '1 VM manifest',
})
assert.equal(missingNetworkSummary.canApprove, false)
assert.ok(missingNetworkSummary.missingRequiredItemIds.includes('network_ip'))


const completeGreenReviewInput = {
  vmName: 'gjallar-vm-demo',
  vmid: 120,
  targetNode: 'yoonmanserver2',
  storage: 'local-lvm',
  template: 'ubuntu-template',
  hardware: { cpu: 2, memoryMb: 4096, diskGb: 40 },
  network: { mode: 'static', bridge: 'vmbr0' },
  terraformStatePath: '/var/lib/gjallar/test-state.tfstate',
  firstPowerOnIncluded: true,
  smokeTimeoutSummary: 'cloud-init 15m',
  risks: [],
  planArtifactLink: '/api/v1/jobs/job-1/artifacts/plan',
  plannedGitDiffSummary: '1 VM manifest',
}

for (const malformedRisks of ['', 0, null]) {
  const malformedRiskSummary = buildReviewConfirmSummary({
    ...completeGreenReviewInput,
    risks: malformedRisks,
  })
  assert.equal(malformedRiskSummary.canApprove, false)
  assert.equal(malformedRiskSummary.canExecute, false)
  assert.match(malformedRiskSummary.decisionReason, /malformed|risk|array/i)
}


const nullRiskEntrySummary = buildReviewConfirmSummary({
  ...completeGreenReviewInput,
  risks: [null],
})
assert.equal(nullRiskEntrySummary.canApprove, false)
assert.equal(nullRiskEntrySummary.canExecute, false)
assert.match(nullRiskEntrySummary.decisionReason, /malformed|unknown|risk/i)

console.log('reviewSummary RED contract exercised')
