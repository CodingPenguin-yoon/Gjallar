import { buildJobsViewModel } from './apiV1ViewModels.js'

const READ_ONLY_ACTIONS = Object.freeze([])

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asText(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function normalizeArtifact(source = {}) {
  return {
    id: asText(source.artifact_id ?? source.id ?? source.name, 'unknown'),
    kind: asText(source.kind ?? source.type, 'artifact'),
    path: asText(source.path ?? source.href ?? source.url, '-'),
    sizeBytes: asNumber(source.size_bytes ?? source.sizeBytes, 0),
    checksum: source.sha256 ?? source.checksum ?? null,
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    raw: source,
  }
}

function normalizeSelectedJob(job) {
  if (!job) return null
  return buildJobsViewModel([job]).items[0] || null
}

function firstJobId(model) {
  return model.items[0]?.id && model.items[0].id !== 'unknown' ? model.items[0].id : null
}

export async function loadJobsScreenModel(client, { selectedJobId = null } = {}) {
  if (!client || typeof client.listJobs !== 'function') {
    throw new Error('Jobs screen requires an /api/v1 client with listJobs()')
  }

  const jobs = await client.listJobs()
  const jobsModel = buildJobsViewModel(jobs)
  const jobId = selectedJobId || firstJobId(jobsModel)

  let selectedJob = null
  let artifacts = []
  if (jobId) {
    const detail = typeof client.getJob === 'function'
      ? await client.getJob(jobId)
      : asArray(jobs).find((job) => String(job.job_id ?? job.id) === String(jobId))
    selectedJob = normalizeSelectedJob(detail)

    if (typeof client.listJobArtifacts === 'function') {
      artifacts = asArray(await client.listJobArtifacts(jobId)).map(normalizeArtifact)
    }
  }

  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    summary: jobsModel.summary,
    jobs: jobsModel.items,
    selectedJob,
    artifacts,
  }
}

export function formatJobTimestamp(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

export function statusToneClass(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'green' || normalized === 'completed' || normalized === 'success') return 'bg-green-50 text-green-700 border-green-200'
  if (normalized === 'yellow' || normalized === 'running' || normalized === 'pending' || normalized === 'in_progress') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (normalized === 'red' || normalized === 'failed' || normalized === 'error' || normalized === 'blocked') return 'bg-red-50 text-red-700 border-red-200'
  return 'bg-slate-50 text-slate-700 border-slate-200'
}
