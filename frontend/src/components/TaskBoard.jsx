import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, FileText, RefreshCw, Search, ShieldAlert } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { apiV1Client } from '../services/apiV1'
import { formatJobTimestamp, loadJobsScreenModel, statusToneClass } from '../utils/jobsScreen'

const LIVE_JOB_STATUSES = new Set(['running', 'pending', 'in_progress', 'processing'])

function SummaryCard({ label, value, tone = 'slate' }) {
  const classes = {
    slate: 'border-slate-200 bg-white text-slate-900',
    green: 'border-green-200 bg-green-50 text-green-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-800',
  }
  return (
    <div className={`rounded-lg border p-4 ${classes[tone] || classes.slate}`}>
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

function jobStatusLabel(status) {
  if (status === 'completed') return '완료'
  if (status === 'running' || status === 'in_progress' || status === 'processing') return '진행 중'
  if (status === 'pending') return '대기'
  if (status === 'blocked') return '차단'
  if (status === 'failed' || status === 'error') return '실패'
  return status || '-'
}

function stepStatusClass(status) {
  if (status === 'completed') return 'border-green-200 bg-green-50 text-green-700'
  if (status === 'running' || status === 'in_progress') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'blocked' || status === 'failed' || status === 'error') return 'border-red-200 bg-red-50 text-red-700'
  return 'border-slate-200 bg-slate-50 text-slate-500'
}

function ProgressSteps({ job }) {
  const steps = Array.isArray(job.steps) ? job.steps : []
  if (!steps.length) return null

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-900">진행 상황</div>
        <div className="text-sm font-medium text-slate-600">{job.progressPercent}%</div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${job.progressPercent}%` }} />
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {steps.map((step) => (
          <div key={step.id} className={`rounded-lg border p-3 ${stepStatusClass(step.status)}`}>
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold">{step.label}</div>
              <div className="text-xs font-medium">{jobStatusLabel(step.status)}</div>
            </div>
            {step.message && <div className="mt-1 text-xs opacity-80">{step.message}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function CreateVmSummary({ summary }) {
  if (!summary) return null

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
        <FileText className="h-4 w-4" />
        생성 VM 요약
      </div>
      <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-lg font-bold text-slate-950">{summary.title}</div>
            <div className="mt-1 text-sm text-slate-600">{summary.subtitle}</div>
          </div>
          <span className="w-fit rounded-full border border-blue-200 bg-white px-2.5 py-1 text-xs font-semibold text-blue-700">
            {jobStatusLabel(summary.status)}
          </span>
        </div>
      </div>

      {summary.advice && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4">
          <div className="text-sm font-semibold text-red-800">{summary.advice.title}</div>
          <p className="mt-1 text-sm text-red-700">{summary.advice.message}</p>
          {Array.isArray(summary.advice.actions) && summary.advice.actions.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-red-700">
              {summary.advice.actions.map((action) => (
                <li key={action}>- {action}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {summary.sections.map((section) => (
          <section key={section.title} className="rounded-lg border border-slate-200 p-4">
            <h3 className="text-sm font-semibold text-slate-900">{section.title}</h3>
            <dl className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2">
              {section.items.map((item) => (
                <div key={`${section.title}-${item.label}`} className="min-w-0">
                  <dt className="text-xs text-slate-500">{item.label}</dt>
                  <dd className="mt-0.5 break-words text-sm font-medium text-slate-900">{item.value || '-'}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        원본 검토 기록과 증적 {summary.artifactCount}개는 감사용으로 보관됩니다.
      </p>
    </div>
  )
}

function DrsMigrationSummary({ summary }) {
  if (!summary) return null
  const artifacts = Array.isArray(summary.artifacts) ? summary.artifacts : []

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
        <FileText className="h-4 w-4" />
        DRS migration summary
      </div>
      <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-lg font-bold text-slate-950">{summary.title}</div>
            <div className="mt-1 text-sm text-slate-600">{summary.subtitle}</div>
          </div>
          <span className="w-fit rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-xs font-semibold text-emerald-700">
            {jobStatusLabel(summary.status)}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {summary.sections.map((section) => (
          <section key={section.title} className="rounded-lg border border-slate-200 p-4">
            <h3 className="text-sm font-semibold text-slate-900">{section.title}</h3>
            <dl className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2">
              {section.items.map((item) => (
                <div key={`${section.title}-${item.label}`} className="min-w-0">
                  <dt className="text-xs text-slate-500">{item.label}</dt>
                  <dd className="mt-0.5 break-words text-sm font-medium text-slate-900">{item.value || '-'}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>

      <div className="mt-4">
        <h3 className="text-sm font-semibold text-slate-900">DRS artifact metadata</h3>
        {artifacts.length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">No DRS artifacts published for this job.</div>
        ) : (
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {artifacts.map((artifact) => (
              <div key={artifact.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <span className="font-medium text-slate-900">{artifact.type}</span>
                  <span className="break-all text-right text-xs text-slate-500">{artifact.id}</span>
                </div>
                <div className="mt-2 grid gap-x-3 gap-y-1 text-xs text-slate-500 sm:grid-cols-2">
                  <span>storage: {artifact.storageBackend || '-'}</span>
                  <span>size: {artifact.sizeBytes ? `${artifact.sizeBytes} B` : '-'}</span>
                  {artifact.checksum && <span className="break-all sm:col-span-2">checksum: {artifact.checksum}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        DRS migration runs are shown for audit and reconciliation awareness only. This panel has no mutation controls.
      </p>
    </div>
  )
}

function JobCard({ job, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(job.id)}
      className={`w-full rounded-lg border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
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
      <section className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
        작업을 선택하면 진행 상황과 산출물을 확인할 수 있습니다.
      </section>
    )
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected run</div>
          <h2 className="mt-1 text-xl font-bold text-slate-900">{job.type}</h2>
          <p className="mt-1 text-sm text-slate-500">{job.id}</p>
          {job.message && <p className="mt-2 text-sm font-medium text-slate-700">{job.message}</p>}
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

      <ProgressSteps job={job} />

      {job.vmSummary ? (
        <CreateVmSummary summary={job.vmSummary} />
      ) : job.drsMigrationSummary ? (
        <DrsMigrationSummary summary={job.drsMigrationSummary} />
      ) : (
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
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span>storage: {artifact.storageBackend}</span>
                    {artifact.checksum && <span className="break-all">checksum: {artifact.checksum}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function filterJobs(jobs, query) {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return jobs
  return jobs.filter((job) => [job.id, job.type, job.status, job.targetId, job.riskLevel].some((value) => String(value ?? '').toLowerCase().includes(normalized)))
}

function TaskBoard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryJobId = searchParams.get('job')
  const compatibilityFallback = searchParams.get('compatibility') === 'operation'
  const [model, setModel] = useState(null)
  const [selectedJobId, setSelectedJobId] = useState(queryJobId)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async (jobId = null, { silent = false } = {}) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const nextModel = await loadJobsScreenModel(apiV1Client, { selectedJobId: jobId })
      setModel(nextModel)
      if (jobId) {
        setSelectedJobId(jobId)
      } else if (nextModel.selectedJob?.id) {
        setSelectedJobId(nextModel.selectedJob.id)
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load Jobs/Runs')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel(queryJobId)
  }, [loadModel, queryJobId])

  useEffect(() => {
    const job = model?.selectedJob
    if (!job || !LIVE_JOB_STATUSES.has(job.status)) return undefined
    const interval = window.setInterval(() => {
      loadModel(job.id, { silent: true })
    }, 2500)
    return () => window.clearInterval(interval)
  }, [loadModel, model?.selectedJob])

  const selectJob = useCallback((jobId) => {
    setSelectedJobId(jobId)
    setSearchParams(jobId ? { job: jobId } : {})
  }, [setSearchParams])

  const jobs = useMemo(() => filterJobs(model?.jobs || [], query), [model, query])
  const summary = model?.summary || { total: 0, running: 0, completed: 0, blocked: 0, failed: 0 }

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Activity className="h-4 w-4" />
            Recorded job history
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">Jobs / Runs</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Read-only execution history for VM create preflight, plan, approval, and safe boundary jobs. Live execution controls are intentionally absent.
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadModel(selectedJobId)}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {summary.total > 0 ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <SummaryCard label="Total" value={summary.total} />
        <SummaryCard label="Running" value={summary.running} tone="amber" />
        <SummaryCard label="Completed" value={summary.completed} tone="green" />
        <SummaryCard label="Blocked" value={summary.blocked} tone="red" />
        <SummaryCard label="Failed" value={summary.failed} tone="red" />
      </div> : null}

      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
        <div className="flex items-start gap-2">
          <ShieldAlert className="mt-0.5 h-4 w-4" />
          <div>
            <div className="font-semibold">Read-only safety boundary</div>
            <div>This screen can inspect jobs and artifacts only. It has no retry, cancel, live-run, or VM mutation controls.</div>
          </div>
        </div>
      </div>

      {compatibilityFallback ? (
        <div role="status" aria-live="polite" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Common Operation detail was not found for this historical result. Gjallar is showing the compatibility Job evidence instead.
        </div>
      ) : null}

      {error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{model ? `Refresh failed. Previous historical Job evidence remains visible. ${error}` : error}</div>
      )}

      {error && !model ? null : model && summary.total === 0 && !error ? (
        <div role="status" className="flex flex-col items-center rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center shadow-sm">
          <FileText className="h-8 w-8 text-slate-300" />
          <h3 className="mt-3 text-base font-semibold text-slate-950">기록된 historical Job이 없습니다</h3>
          <p className="mt-1 max-w-lg text-sm text-slate-500">새 검증 작업은 Operations에 기록되며, 이 화면은 이전 Job 근거가 있을 때만 표시합니다.</p>
        </div>
      ) : <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr]">
        <section className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter jobs by id, type, target, risk, status"
              className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm text-slate-900 outline-none transition focus-visible:border-slate-500 focus-visible:ring-2 focus-visible:ring-slate-100"
            />
          </div>

          {loading && !model ? (
            <div role="status" aria-live="polite" className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">Loading jobs…</div>
          ) : jobs.length === 0 ? (
            <div role="status" className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No jobs match the current filter.</div>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} selected={model?.selectedJob?.id === job.id} onSelect={selectJob} />
              ))}
            </div>
          )}
        </section>

        <SelectedJobPanel job={model?.selectedJob} artifacts={model?.artifacts || []} />
      </div>}
    </div>
  )
}

export default TaskBoard
