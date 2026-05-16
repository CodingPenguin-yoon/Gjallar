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
  buildInfraExplorerModel,
  buildJobsViewModel,
  buildRisksViewModel,
} = await importExpected('../src/utils/apiV1ViewModels.js', 'read-only /api/v1 view model utilities')

const infra = buildInfraExplorerModel({
  nodes: [
    { node_id: 'yoonmanserver2', name: 'yoonmanserver2', status: 'online' },
    { node_id: 'yoonmanserver3', name: 'yoonmanserver3', status: 'online' },
  ],
  vms: [
    {
      vmid: 101,
      name: 'app-01',
      node_id: 'yoonmanserver2',
      status: 'running',
      ip_addresses: ['172.17.0.1', '192.168.2.141', '172.18.0.1'],
      cpu_cores: 2,
      memory_mb: 4096,
      disks: [{ size_gb: 40 }],
      template: false,
    },
    { vmid: 102, vm_name: 'db-01', node: 'yoonmanserver2', status: 'stopped', memory_gb: 8, disk_gb: 80 },
    { vmid: 103, name: 'template-01', node_id: 'yoonmanserver2', status: 'stopped', template: true },
    { vmid: 104, name: 'orphan', status: 'running' },
    { vmid: 105, name: 'unknown-node-stopped', status: 'stopped' },
    { name: 'missing-vmid', node_id: 'yoonmanserver3', status: 'stopped' },
    { id: 'vm-x', name: 'non-numeric-vmid', node_id: 'yoonmanserver3', status: 'stopped' },
  ],
})
assert.equal(infra.readOnly, true)
assert.deepEqual(infra.allowedActions, [])
assert.equal(infra.summary.totalVms, 7)
assert.equal(infra.summary.runningVms, 2)
assert.equal(infra.summary.stoppedVms, 5)
assert.deepEqual(infra.nodes.map((node) => node.id), ['yoonmanserver2', 'yoonmanserver3', 'unknown'])
assert.deepEqual(infra.nodes[0].vms.map((vm) => vm.name), ['app-01', 'db-01', 'template-01'])
assert.equal(infra.nodes[0].vms[0].primaryIp, '192.168.2.141')
assert.deepEqual(infra.nodes[0].vms[0].hiddenIpAddresses, ['172.17.0.1', '172.18.0.1'])
assert.equal(infra.nodes[0].vms[0].hiddenIpCount, 2)
assert.equal(infra.nodes[0].vms[0].memoryGb, 4)
assert.equal(infra.nodes[0].vms[0].diskGb, 40)
assert.equal(infra.nodes[0].vms[0].readOnly, true)
assert.deepEqual(infra.nodes[0].vms[0].allowedActions, [])
assert.deepEqual(infra.nodes[0].vms[1].allowedActions, ['start'])
assert.deepEqual(infra.nodes[0].vms[2].allowedActions, [])
assert.deepEqual(infra.nodes[1].vms.map((vm) => vm.allowedActions), [[], []])
assert.deepEqual(infra.nodes[2].vms.map((vm) => vm.allowedActions), [[], []])

const jobs = buildJobsViewModel([
  {
    job_id: 'job-plan',
    job_type: 'vm_create_plan',
    status: 'completed',
    target_id: 'yoonmanserver2',
    risk_level: 'green',
    artifact_count: 4,
    risk_count: 0,
    started_at: '2026-05-09T02:40:00+09:00',
    finished_at: '2026-05-09T02:41:00+09:00',
    artifacts_url: '/api/v1/jobs/job-plan/artifacts',
  },
  { job_id: 'job-risk', job_type: 'vm_create_preflight', status: 'blocked', risk_level: 'red', artifact_count: 1, risk_count: 2 },
  { job_id: 'job-running', job_type: 'vm_create_plan', status: 'running', risk_level: 'yellow' },
])
assert.equal(jobs.readOnly, true)
assert.deepEqual(jobs.allowedActions, [])
assert.equal(jobs.summary.total, 3)
assert.equal(jobs.summary.completed, 1)
assert.equal(jobs.summary.blocked, 1)
assert.equal(jobs.summary.running, 1)
assert.equal(jobs.summary.failed, 0)
assert.equal(jobs.items[0].id, 'job-plan')
assert.equal(jobs.items[0].artifactCount, 4)
assert.equal(jobs.items[0].artifactsUrl, '/api/v1/jobs/job-plan/artifacts')
assert.equal(jobs.items[1].tone, 'red')

const risks = buildRisksViewModel([
  { risk_id: 'job-risk:ip_collision', job_id: 'job-risk', level: 'red', code: 'ip_collision', message: 'IP collision', artifacts_url: '/api/v1/jobs/job-risk/artifacts' },
  { risk_id: 'job-risk:dhcp', job_id: 'job-risk', level: 'yellow', code: 'dhcp_requires_discovery' },
  { risk_id: 'job-plan:ok', job_id: 'job-plan', level: 'green', code: 'no_risk' },
])
assert.equal(risks.readOnly, true)
assert.deepEqual(risks.allowedActions, [])
assert.equal(risks.summary.total, 3)
assert.equal(risks.summary.red, 1)
assert.equal(risks.summary.yellow, 1)
assert.equal(risks.summary.green, 1)
assert.equal(risks.items[0].id, 'job-risk:ip_collision')
assert.equal(risks.items[0].level, 'red')
assert.equal(risks.items[0].artifactsUrl, '/api/v1/jobs/job-risk/artifacts')

const source = readFileSync(new URL('../src/utils/apiV1ViewModels.js', import.meta.url), 'utf8')
const forbiddenAction = (...parts) => parts.join('')
for (const blockedAction of [
  forbiddenAction('termi', 'nate'),
  forbiddenAction('del', 'ete'),
  forbiddenAction('res', 'ize'),
  forbiddenAction('force', ' stop'),
  forbiddenAction('res', 'et'),
  forbiddenAction('archive', 'Task'),
  forbiddenAction('Event', 'Source'),
]) {
  assert.ok(!source.toLowerCase().includes(blockedAction.toLowerCase()), `read-only view model must not expose ${blockedAction}`)
}

console.log('apiV1ViewModels RED contract exercised')
