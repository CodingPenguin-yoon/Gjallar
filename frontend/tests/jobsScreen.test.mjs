import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { loadJobsScreenModel } = await importExpected(
  '../src/utils/jobsScreen.js',
  'Jobs/Runs screen loader'
)

const calls = []
const fakeClient = {
  async listJobs() {
    calls.push('listJobs')
    return [
      {
        job_id: 'job-plan',
        job_type: 'vm_create_plan',
        status: 'completed',
        target_id: 'general-vm:web-01',
        risk_level: 'green',
        artifact_count: 2,
        risk_count: 0,
        started_at: '2026-05-09T14:00:00+09:00',
        finished_at: '2026-05-09T14:01:00+09:00',
        artifacts_url: '/api/v1/jobs/job-plan/artifacts',
      },
      {
        job_id: 'job-risk',
        job_type: 'vm_create_preflight',
        status: 'blocked',
        target_id: 'general-vm:db-01',
        risk_level: 'red',
        artifact_count: 1,
        risk_count: 2,
      },
    ]
  },
  async getJob(jobId) {
    calls.push(`getJob:${jobId}`)
    return {
      job_id: jobId,
      job_type: 'vm_create_plan',
      status: 'completed',
      target_id: 'general-vm:web-01',
      risk_level: 'green',
      artifact_count: 2,
      risk_count: 0,
      started_at: '2026-05-09T14:00:00+09:00',
      finished_at: '2026-05-09T14:01:00+09:00',
    }
  },
  async listJobArtifacts(jobId) {
    calls.push(`listJobArtifacts:${jobId}`)
    return [
      { artifact_id: 'plan-json', kind: 'plan', path: 'artifacts/job-plan/plan.json' },
      { artifact_id: 'review-md', kind: 'review', path: 'artifacts/job-plan/review.md' },
    ]
  },
  async getTasks() {
    calls.push('getTasks')
    throw new Error('legacy getTasks must not be called')
  },
  createTaskEventStream() {
    calls.push('createTaskEventStream')
    throw new Error('legacy task event stream must not be opened')
  },
  async archiveTask() {
    calls.push('archiveTask')
    throw new Error('legacy archiveTask must not be called')
  },
}

const model = await loadJobsScreenModel(fakeClient, { selectedJobId: 'job-plan' })
assert.deepEqual(calls, ['listJobs', 'getJob:job-plan', 'listJobArtifacts:job-plan'])
assert.equal(model.readOnly, true)
assert.deepEqual(model.allowedActions, [])
assert.equal(model.summary.total, 2)
assert.equal(model.summary.completed, 1)
assert.equal(model.summary.blocked, 1)
assert.equal(model.selectedJob.id, 'job-plan')
assert.equal(model.selectedJob.readOnly, true)
assert.deepEqual(model.selectedJob.allowedActions, [])
assert.equal(model.artifacts.length, 2)
assert.deepEqual(model.artifacts.map((artifact) => artifact.id), ['plan-json', 'review-md'])
assert.equal(model.artifacts[0].readOnly, true)
assert.deepEqual(model.artifacts[0].allowedActions, [])

const source = readFileSync(new URL('../src/components/TaskBoard.jsx', import.meta.url), 'utf8')
assert.match(source, /apiV1Client/)
assert.match(source, /loadJobsScreenModel/)
assert.doesNotMatch(source, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'TaskBoard must not import the legacy /api client')

const forbidden = (...parts) => parts.join('')
for (const blocked of [
  forbidden('create', 'TaskEventStream'),
  forbidden('archive', 'Task'),
  forbidden('get', 'Tasks'),
  forbidden('get', 'TaskDetail'),
  forbidden('Event', 'Source'),
  forbidden('/api/', 'tasks'),
  forbidden('/api/', 'logs'),
  forbidden('/api/', 'status'),
  forbidden('tf_', 'apply'),
  forbidden('Terraform', ' apply'),
  forbidden('Archive'),
  forbidden('delete'),
  forbidden('terminate'),
  forbidden('Power'),
  forbidden('window.', 'confirm'),
  forbidden('window.', 'prompt'),
]) {
  assert.ok(!source.toLowerCase().includes(blocked.toLowerCase()), `Jobs screen must not expose legacy/destructive term: ${blocked}`)
}

console.log('jobsScreen RED contract exercised')
