import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Clock3,
  HardDrive,
  Network,
  Play,
  Power,
  RefreshCw,
  Server,
  Terminal,
} from 'lucide-react'
import { insightToneClass, insightStatusTone } from '../../../entities/insight/model'
import {
  formatOperationTime,
  operationStatusTone,
  operationTypeLabel,
} from '../../../entities/operation/model'
import { apiV1Client } from '../../../shared/api/apiV1'
import { authFailureMessage } from '../../../shared/auth/permissions'
import {
  insightFindingPath,
  operationsTargetPath,
  workloadActionPath,
} from '../../../shared/navigation/targetPaths'
import { loadVmDetailModel } from './model'

function formatNumber(value, digits = 0) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return parsed.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function formatGb(value, digits = 1) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? `${formatNumber(parsed, digits)} GB` : '-'
}

function formatObservedAt(value) {
  if (!value) return 'observed time unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function sourceStatusLabel(status) {
  return String(status || 'unknown').replaceAll('_', ' ')
}

function statusTone(status) {
  if (status === 'running') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'stopped') return 'border-slate-200 bg-slate-50 text-slate-700'
  return 'border-amber-200 bg-amber-50 text-amber-800'
}

function FindingCard({ finding }) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${insightToneClass(insightStatusTone(finding.severity))}`}>
              {finding.severity}
            </span>
            <span className="font-mono text-xs text-slate-500">{finding.code}</span>
          </div>
          <h4 className="mt-2 font-semibold text-slate-950">{finding.title}</h4>
          <p className="mt-1 text-sm leading-6 text-slate-600">{finding.message}</p>
          <div className="mt-2 text-xs text-slate-500">{finding.source} · {finding.freshness} · {finding.ruleVersion}</div>
        </div>
        <Link
          to={insightFindingPath(finding)}
          className="shrink-0 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
        >
          {finding.category} 근거 열기
        </Link>
      </div>
    </article>
  )
}

function OperationCard({ operation }) {
  return (
    <Link
      to={`/operations/${encodeURIComponent(operation.id)}`}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 hover:shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-950">{operationTypeLabel(operation.type)}</div>
          <div className="mt-1 break-all font-mono text-xs text-slate-500">{operation.id}</div>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${operationStatusTone(operation.status)}`}>
          {operation.status}
        </span>
      </div>
      <div className="mt-3 text-xs text-slate-500">{operation.stage} · updated {formatOperationTime(operation.updatedAt || operation.createdAt)}</div>
    </Link>
  )
}

function ActionEntries({ vm, canMutate }) {
  const canStart = vm.allowedActions.includes('start')
  const canShutdown = vm.allowedActions.includes('shutdown')
  const canGuideUnlock = !vm.template && vm.nodeId !== 'unknown'

  if (!canMutate) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        지원 작업은 operator 또는 admin 권한과 live Proxmox 연결이 있을 때 Workloads 확인 흐름에서 시작할 수 있습니다.
      </div>
    )
  }

  return (
    <div className="flex flex-wrap gap-2">
      {canStart ? (
        <Link to={workloadActionPath(vm.vmid, 'start')} className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-100">
          <Play className="h-4 w-4" /> Start 확인
        </Link>
      ) : null}
      {canShutdown ? (
        <Link to={workloadActionPath(vm.vmid, 'shutdown')} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900 hover:bg-amber-100">
          <Power className="h-4 w-4" /> Shutdown 확인
        </Link>
      ) : null}
      {canGuideUnlock ? (
        <Link
          to={`/operations/guided-qm/vm-unlock?node_id=${encodeURIComponent(vm.nodeId)}&vmid=${encodeURIComponent(vm.vmid)}`}
          className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-100"
        >
          <Terminal className="h-4 w-4" /> Guided qm unlock
        </Link>
      ) : null}
      {!canStart && !canShutdown && !canGuideUnlock ? (
        <span className="text-sm text-slate-500">현재 관찰 상태에서 지원되는 작업 entry가 없습니다.</span>
      ) : null}
    </div>
  )
}

export default function VmDetail({ canMutate = false }) {
  const { vmid = '' } = useParams()
  const [model, setModel] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const requestGeneration = useRef(0)

  const loadModel = useCallback(async ({ clear = false } = {}) => {
    const generation = requestGeneration.current + 1
    requestGeneration.current = generation
    if (clear) setModel(null)
    setLoading(true)
    setError('')
    try {
      const nextModel = await loadVmDetailModel(apiV1Client, vmid, {
        onVmLoaded: (observedModel) => {
          if (requestGeneration.current !== generation) return
          setModel(observedModel)
          setLoading(false)
        },
      })
      if (requestGeneration.current === generation) setModel(nextModel)
    } catch (nextError) {
      if (requestGeneration.current === generation) {
        setError(authFailureMessage(nextError, 'VM 상세를 불러오지 못했습니다.'))
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false)
    }
  }, [vmid])

  useEffect(() => {
    loadModel({ clear: true })
    return () => {
      requestGeneration.current += 1
    }
  }, [loadModel])

  if (loading && !model) {
    return <div role="status" className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">Loading exact VM context...</div>
  }

  if (!model) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-800">
        <div className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4" /><span>{error || 'VM 상세를 불러오지 못했습니다.'}</span></div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" onClick={() => loadModel({ clear: true })} className="font-semibold text-red-900 underline">Retry exact VM</button>
          <Link to="/instances" className="font-semibold text-blue-700">Workloads로 돌아가기</Link>
        </div>
      </div>
    )
  }

  const { vm } = model
  const ipAddresses = Array.isArray(vm.ipAddresses) ? vm.ipAddresses : []
  const bridges = Array.isArray(vm.raw?.nic_bridge_evidence) ? vm.raw.nic_bridge_evidence : []
  const observation = model.observation
  const configObserved = observation.sources.vmConfig.status === 'available'
  const guestObserved = observation.sources.guestAgent.status === 'available'
  const guestApplicable = observation.sources.guestAgent.status !== 'not_applicable'
  const detailObserved = observation.sources.vmDetail.status === 'available'
  const ipEvidenceComplete = configObserved && (!guestApplicable || guestObserved)
  const diskEvidenceComplete = configObserved && detailObserved
  const insightLimitations = [
    model.context.unavailableInsightCategories.length > 0
      ? `unavailable: ${model.context.unavailableInsightCategories.join(', ')}`
      : '',
    model.context.uncertainInsightCategories.length > 0
      ? `unknown/stale: ${model.context.uncertainInsightCategories.join(', ')}`
      : '',
    model.context.insightsTruncated
      ? `truncated: ${model.context.truncatedInsightCategories.join(', ')}`
      : '',
  ].filter(Boolean).join('; ')

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link to="/instances" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-950">
            <ArrowLeft className="h-4 w-4" /> Workloads
          </Link>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(vm.status)}`}>{vm.status}</span>
            <span className="font-mono text-xs text-slate-500">{vm.targetId}</span>
          </div>
          <h2 className="mt-2 text-3xl font-semibold text-slate-950">{vm.name}</h2>
          <p className="mt-1 text-sm text-slate-600">Exact VM 상태에서 Insights 원인과 검증 Operation을 같은 target identity로 확인합니다.</p>
        </div>
        <button
          type="button"
          onClick={() => loadModel()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </header>

      {error ? (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          부가 문맥 새로고침에 실패해 이전 exact VM 상태를 표시합니다. {error}
        </div>
      ) : null}

      <div className={`rounded-lg border p-3 text-sm ${observation.status === 'available' ? 'border-slate-200 bg-white text-slate-700' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
        <div className="font-semibold">Inventory observation · {observation.source} · {observation.freshness} · {formatObservedAt(observation.observedAt)}</div>
        {observation.status !== 'available' ? (
          <div className="mt-1 text-xs">
            Detail coverage is {observation.status}; empty fields are not treated as confirmed absence. vm_config {sourceStatusLabel(observation.sources.vmConfig.status)} · guest_agent {sourceStatusLabel(observation.sources.guestAgent.status)} · vm_detail {sourceStatusLabel(observation.sources.vmDetail.status)}
          </div>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Server className="h-4 w-4" /> Node</div>
          <div className="mt-3 font-mono text-sm font-semibold text-slate-950">{vm.nodeId}</div>
          <div className="mt-1 text-xs text-slate-500">VMID {vm.vmid}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Compute</div>
          <div className="mt-3 text-sm font-semibold text-slate-950">{formatNumber(vm.cpuCores)} CPU · {formatGb(vm.memoryGb)}</div>
          <div className="mt-1 text-xs text-slate-500">base VM inventory observation</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Network className="h-4 w-4" /> Network evidence</div>
          <div className="mt-3 break-words font-mono text-xs font-semibold text-slate-950">{ipAddresses.join(', ') || (ipEvidenceComplete ? 'No IP evidence returned' : 'IP evidence unavailable in partial observation')}</div>
          <div className="mt-1 text-xs text-slate-500">
            {guestApplicable
              ? guestObserved
                ? `guest-agent request observed${vm.guestAgent.available ? ' with usable IP' : ' without usable IP'}`
                : `guest-agent source ${sourceStatusLabel(observation.sources.guestAgent.status)}`
              : 'guest-agent source not applicable while stopped'}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><HardDrive className="h-4 w-4" /> Storage</div>
          <div className="mt-3 text-sm font-semibold text-slate-950">{diskEvidenceComplete ? formatGb(vm.diskGb) : 'Configuration evidence unavailable'}</div>
          <div className="mt-1 text-xs text-slate-500">{diskEvidenceComplete ? vm.storageId : `vm_config ${sourceStatusLabel(observation.sources.vmConfig.status)}`}</div>
        </div>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="vm-action-entry-title">
        <h3 id="vm-action-entry-title" className="text-xl font-semibold text-slate-950">Supported action entry</h3>
        <p className="mt-1 text-sm text-slate-600">실제 Start/Shutdown은 기존 Workloads의 확인·acknowledgement 흐름에서 계속 수행합니다.</p>
        <div className="mt-4"><ActionEntries vm={vm} canMutate={canMutate} /></div>
      </section>

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="vm-insights-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="vm-insights-title" className="flex items-center gap-2 text-xl font-semibold text-slate-950"><Activity className="h-5 w-5" /> Related Insights</h3>
              <p className="mt-1 text-sm text-slate-600">target {vm.targetId}와 정확히 일치하는 finding입니다.</p>
            </div>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{model.findings.length}</span>
          </div>
          {model.context.insightsStatus === 'loading' ? (
            <div className="mt-4 text-sm text-slate-500">관련 Insights를 불러오는 중입니다.</div>
          ) : model.context.insightsStatus === 'unavailable' ? (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Insights source를 확인할 수 없습니다. 빈 finding으로 해석하지 않습니다.</div>
          ) : (
            <>
              {model.context.insightsStatus === 'partial' || model.context.insightsTruncated ? (
                <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Incomplete Insights coverage: {insightLimitations}</div>
              ) : null}
              <div className="mt-4 space-y-3">
                {model.findings.length > 0
                  ? model.findings.map((finding) => <FindingCard key={finding.id} finding={finding} />)
                  : <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
                      {model.context.findingCoverageComplete
                        ? '완전한 Insights 응답에서 이 VM과 일치하는 active finding이 없습니다.'
                        : 'Insights coverage가 불완전하여 이 VM의 active finding 부재를 확정할 수 없습니다.'}
                    </div>}
              </div>
            </>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="vm-operations-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="vm-operations-title" className="flex items-center gap-2 text-xl font-semibold text-slate-950"><Clock3 className="h-5 w-5" /> Related Operations</h3>
              <p className="mt-1 text-sm text-slate-600">exact target filter · latest {model.context.operationQueryLimit}</p>
            </div>
            <Link to={operationsTargetPath(vm.targetType, vm.targetId)} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">Filtered Operations</Link>
          </div>
          {model.context.operationsStatus === 'loading' ? (
            <div className="mt-4 text-sm text-slate-500">관련 Operations를 불러오는 중입니다.</div>
          ) : model.context.operationsStatus === 'unavailable' ? (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Operation query를 사용할 수 없습니다. 실행 이력이 없다고 해석하지 않습니다.</div>
          ) : (
            <div className="mt-4 space-y-3">
              {model.operations.length > 0
                ? model.operations.map((operation) => <OperationCard key={operation.id} operation={operation} />)
                : <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">이 VM target에 기록된 Operation이 없습니다.</div>}
            </div>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="vm-observation-details-title">
        <h3 id="vm-observation-details-title" className="text-xl font-semibold text-slate-950">Observed configuration details</h3>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase text-slate-500">Config lock</dt><dd className="mt-1 font-mono text-slate-900">{configObserved ? vm.raw?.config_lock || 'none observed' : 'unavailable in partial observation'}</dd></div>
          <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase text-slate-500">Tags</dt><dd className="mt-1 break-words text-slate-900">{configObserved ? vm.tags.join(', ') || 'none returned' : 'unavailable in partial observation'}</dd></div>
          <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase text-slate-500">NIC bridges</dt><dd className="mt-1 break-words font-mono text-xs text-slate-900">{configObserved ? bridges.map((item) => item.bridge_id).filter(Boolean).join(', ') || 'none returned' : 'unavailable in partial observation'}</dd></div>
          <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase text-slate-500">Template</dt><dd className="mt-1 text-slate-900">{vm.template ? 'yes' : 'no'}</dd></div>
        </dl>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2 text-left">Disk</th><th className="px-3 py-2 text-left">Storage</th><th className="px-3 py-2 text-right">Size</th><th className="px-3 py-2 text-left">Attributes</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {diskEvidenceComplete && vm.disks.length > 0 ? vm.disks.map((disk) => (
                <tr key={`${disk.device}:${disk.volumeId}`}>
                  <td className="px-3 py-2 font-mono text-xs text-slate-900">{disk.device}</td>
                  <td className="px-3 py-2 text-slate-700">{disk.storageId}</td>
                  <td className="px-3 py-2 text-right text-slate-700">{formatGb(disk.sizeGb)}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{[disk.format, disk.discard === 'on' ? 'discard' : '', disk.ssd === '1' ? 'ssd' : ''].filter(Boolean).join(' · ') || '-'}</td>
                </tr>
              )) : <tr><td colSpan="4" className="px-3 py-4 text-center text-slate-500">{diskEvidenceComplete ? 'No disk detail returned' : 'Disk detail unavailable in partial observation'}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  )
}
