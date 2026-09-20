import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
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
const VmResourcePanels = lazy(() => import('./VmResourcePanels'))

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
          <Play className="h-4 w-4" /> 시작 검토
        </Link>
      ) : null}
      {canShutdown ? (
        <Link to={workloadActionPath(vm.vmid, 'shutdown')} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900 hover:bg-amber-100">
          <Power className="h-4 w-4" /> 정상 종료 검토
        </Link>
      ) : null}
      {canGuideUnlock ? (
        <Link
          to={`/operations/guided-qm/vm-unlock?node_id=${encodeURIComponent(vm.nodeId)}&vmid=${encodeURIComponent(vm.vmid)}`}
          className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-100"
        >
          <Terminal className="h-4 w-4" /> 잠금 해제 안내
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
  const [conversion, setConversion] = useState(null)
  const [deletion, setDeletion] = useState(null)
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

  if (conversion?.vmid === vmid) {
    return <section role="status" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-xl font-semibold">VM {vmid} 템플릿 전환을 확인했습니다</h2>
      <p className="text-sm">정지된 template 상태, 실제 base volume과 관련 설정 보존을 확인했습니다. 원본 직접 부팅은 사용할 수 없습니다.</p>
      <ul className="space-y-1 break-all text-sm">{conversion.result.observed_after.volumes.map(row => <li key={row.volume_id}>{row.slot} · {row.volume_id} · {row.size_bytes / 1024 ** 3} GiB</li>)}</ul>
      <p className="text-sm text-amber-900">게스트 준비는 운영자 확인이며 실제 배포 검증은 남아 있습니다. 생성용 template scope에 이 VMID를 포함하도록 연결 권한을 갱신한 뒤 테스트 배포하세요.</p>
      <div className="flex flex-wrap gap-4 text-sm font-semibold">
        <Link className="underline" to={`/operations/${encodeURIComponent(conversion.result.operation_id)}`}>전환 결과·이력</Link>
        <Link className="underline" to="/settings/proxmox">생성 연결 권한 갱신</Link>
        <Link className="underline" to={`/instances/create?${new URLSearchParams({template_node: conversion.nodeId, template_vmid: vmid})}`}>테스트 VM 배포</Link>
        <Link className="underline" to="/instances">Workloads로 돌아가기</Link>
      </div>
    </section>
  }

  if (deletion?.vmid === vmid) {
    return <section role="status" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-xl font-semibold">VM {vmid} 삭제를 확인했습니다</h2>
      <p className="text-sm">PVE 작업 완료, VMID 미사용과 아래 volume의 부재를 확인했습니다. 삭제 전 상세 상태는 더 이상 표시하지 않습니다.</p>
      <ul className="space-y-1 break-all text-sm">{deletion.result.observed_after.deleted_volumes.map(volume => <li key={volume}>삭제 확인: {volume}</li>)}</ul>
      <ul className="space-y-1 break-all text-sm">{deletion.result.observed_after.preserved_volumes.map(volume => <li key={volume}>보존 확인: {volume}</li>)}</ul>
      <div className="flex flex-wrap gap-4 text-sm font-semibold">
        <Link className="underline" to={`/operations/${encodeURIComponent(deletion.result.operation_id)}`}>삭제 결과·이력</Link>
        <Link className="underline" to="/instances">Workloads로 돌아가기</Link>
      </div>
    </section>
  }

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
    <section className="space-y-3">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link to="/instances" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-950">
            <ArrowLeft className="h-4 w-4" /> VM 목록
          </Link>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(vm.status)}`}>{vm.status}</span>
            <span className="font-mono text-xs text-slate-500">{vm.targetId}</span>
          </div>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">{vm.name}</h2>
          <p className="mt-1 text-sm text-slate-600">현재 상태를 확인하고 VM 작업과 결과를 이어서 확인합니다.</p>
          <Link className="mt-2 inline-block text-sm font-semibold underline" to={`/insights/metrics?${new URLSearchParams({kind: 'vm', node: vm.nodeId, vmid: vm.vmid})}`}>사용량·PVE 추이</Link>
        </div>
        <button
          type="button"
          onClick={() => loadModel()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> 새로고침
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
                : `Guest Agent 응답을 확인하지 못했습니다 (${sourceStatusLabel(observation.sources.guestAgent.status)}). Proxmox의 agent 사용 설정과 VM 내부 서비스 상태를 확인하세요.`
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
        <h3 id="vm-action-entry-title" className="text-xl font-semibold text-slate-950">VM 작업</h3>
        <p className="mt-1 text-sm text-slate-600">시작·정상 종료는 대상과 영향을 확인한 뒤 실행합니다.</p>
        <div className="mt-4"><ActionEntries vm={vm} canMutate={canMutate} /></div>
        {!vm.template && canMutate && <Link className="mr-2 mt-3 inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100" to={`/instances/${vm.vmid}/migrate?${new URLSearchParams({node: vm.nodeId})}`}>정지 VM 노드 이동</Link>}
        {!vm.template && <Link className="mt-3 inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100" to={`/instances/${vm.vmid}/backups?${new URLSearchParams({node: vm.nodeId, storage: vm.storageId || ''})}`}>백업 목록·새 백업</Link>}
        {canMutate && !vm.template && <Suspense fallback={<p className="mt-4 text-sm text-slate-500">VM 변경 도구 불러오는 중…</p>}>
          <VmResourcePanels key={`${vm.nodeId}:${vm.vmid}`} vm={vm} onUpdated={loadModel} onConverted={result => {requestGeneration.current += 1; setConversion({vmid, nodeId: vm.nodeId, result})}} onDeleted={result => {requestGeneration.current += 1; setDeletion({vmid, result})}} />
        </Suspense>}
      </section>

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="vm-insights-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="vm-insights-title" className="flex items-center gap-2 text-xl font-semibold text-slate-950"><Activity className="h-5 w-5" /> 관련 진단</h3>
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
              <h3 id="vm-operations-title" className="flex items-center gap-2 text-xl font-semibold text-slate-950"><Clock3 className="h-5 w-5" /> 최근 작업</h3>
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

      <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <summary className="cursor-pointer text-lg font-semibold text-slate-950">설정 관찰 상세 · 잠금·태그·디스크</summary>
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
      </details>
    </section>
  )
}
