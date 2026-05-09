import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, CheckCircle2, Clock3, FileText, RefreshCw, Search, ShieldAlert } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { formatJobTimestamp, loadJobsScreenModel, statusToneClass } from '../utils/jobsScreen'

function SummaryCard({ label, value, tone = 'slate' }) {
  const classes = {
    slate: 'border-slate-200 bg-white text-slate-900',
    green: 'border-green-200 bg-green-50 text-green-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-800',
  }
  return (
    <div className={`rounded-xl border p-4 ${classes[tone] || classes.slate}`}>
      <div className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-2 text-2xl font-bold">{value}</div>
    </div>
  )
}

function JobStatusBadge({ job }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${statusToneClass(job.tone || job.status)}`}>
      {job.status}
    </span>
  )
}

function JobCard({ job, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(job.id)}
      className={`w-full rounded-xl border p-4 text-left transition ${
        selected ? 'border-blue-500 bg-blue-50 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">{job.type}</div>
          <div className="mt-1 truncate text-xs text-slate-500">Job ID: {job.id}</div>
          <div className="mt-1 truncate text-xs text-slate-500">Target: {job.targetId}</div>
        </div>
        <JobStatusBadge job={job} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
        <div>Risk: {job.riskLevel}</div>
        <div>Artifacts: {job.artifactCount}</div>
        <div>Started: {formatJobTimestamp(job.startedAt)}</div>
        <div>Finished: {formatJobTimestamp(job.finishedAt)}</div>
      </div>
    </button>
  )
}

function SelectedJobPanel({ job, artifacts }) {
  if (!job) {
    return (
      <section className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
        Select a job to inspect read-only details and artifacts.
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected run</div>
          <h2 className="mt-1 text-xl font-bold text-slate-900">{job.type}</h2>
          <p className="mt-1 text-sm text-slate-500">{job.id}</p>
        </div>
        <JobStatusBadge job={job} />
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">Target</div>
          <div className="mt-1 font-medium text-slate-900">{job.targetId}</div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">Risk level</div>
          <div className="mt-1 font-medium text-slate-900">{job.riskLevel}</div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">Started</div>
          <div className="mt-1 font-medium text-slate-900">{formatJobTimestamp(job.startedAt)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">Finished</div>
          <div className="mt-1 font-medium text-slate-900">{formatJobTimestamp(job.finishedAt)}</div>
        </div>
      </div>

      <div className="mt-6">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
          <FileText className="h-4 w-4" />
          Artifacts
        </div>
        {artifacts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">No artifacts published for this job.</div>
        ) : (
          <div className="space-y-2">
            {artifacts.map((artifact) => (
              <div key={artifact.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-slate-900">{artifact.kind}</span>
                  <span className="text-xs text-slate-500">{artifact.id}</span>
                </div>
                <div className="mt-1 break-all text-xs text-slate-500">{artifact.path}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function filterJobs(jobs, query) {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return jobs
  return jobs.filter((job) => [job.id, job.type, job.status, job.targetId, job.riskLevel].some((value) => String(value ?? '').toLowerCase().includes(normalized)))
}

function TaskBoard() {
  const [model, setModel] = useState(null)
  const [selectedJobId, setSelectedJobId] = useState(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async (jobId = selectedJobId) => {
    setLoading(true)
    setError(null)
    try {
      const nextModel = await loadJobsScreenModel(apiV1Client, { selectedJobId: jobId })
      setModel(nextModel)
      if (!jobId && nextModel.selectedJob?.id) {
        setSelectedJobId(nextModel.selectedJob.id)
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load Jobs/Runs')
    } finally {
      setLoading(false)
    }
  }, [selectedJobId])

  useEffect(() => {
    loadModel()
  }, [])

  const selectJob = useCallback((jobId) => {
    setSelectedJobId(jobId)
    loadModel(jobId)
  }, [loadModel])

  const jobs = useMemo(() => filterJobs(model?.jobs || [], query), [model, query])
  const summary = model?.summary || { total: 0, running: 0, completed: 0, blocked: 0, failed: 0 }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-blue-600">
            <Activity className="h-4 w-4" />
            PRD /api/v1
          </div>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Jobs / Runs</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Read-only execution history for VM create preflight, plan, approval, and safe boundary jobs. Live execution controls are intentionally absent.
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadModel(selectedJobId)}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <SummaryCard label="Total" value={summary.total} />
        <SummaryCard label="Running" value={summary.running} tone="amber" />
        <SummaryCard label="Completed" value={summary.completed} tone="green" />
        <SummaryCard label="Blocked" value={summary.blocked} tone="red" />
        <SummaryCard label="Failed" value={summary.failed} tone="red" />
      </div>

      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
        <div className="flex items-start gap-2">
          <ShieldAlert className="mt-0.5 h-4 w-4" />
          <div>
            <div className="font-semibold">Read-only safety boundary</div>
            <div>This screen can inspect jobs and artifacts only. It has no retry, cancel, live-run, or VM mutation controls.</div>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr]">
        <section className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter jobs by id, type, target, risk, status"
              className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {loading && !model ? (
            <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Loading jobs…</div>
          ) : jobs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No jobs match the current filter.</div>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} selected={model?.selectedJob?.id === job.id} onSelect={selectJob} />
              ))}
            </div>
          )}
        </section>

        <SelectedJobPanel job={model?.selectedJob} artifacts={model?.artifacts || []} />
      </div>
    </div>
  )
}

export default TaskBoard
