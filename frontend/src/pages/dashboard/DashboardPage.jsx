import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, AlertTriangle, HardDrive, List, Plus, RefreshCw, Server } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import ClusterTrends from '../../features/monitoring/ClusterTrends'
import { aggregateValues } from '../../features/monitoring/clusterMetrics'
import RecentOperations from './RecentOperations'

const DASHBOARD_DATA_LABELS = ['Cluster', 'Nodes', 'VMs', 'Storage', 'Networks', 'Jobs/Runs', 'Risks/Alerts']

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function settledInventoryValue(result, fallback) {
  return result.status === 'fulfilled' && result.value && typeof result.value === 'object'
    ? result.value.data
    : fallback
}

function inventoryAvailability(result) {
  const availability = result.status === 'fulfilled' ? result.value?.meta?.availability : null
  return availability && typeof availability === 'object' && !Array.isArray(availability)
    ? availability
    : null
}

function inventoryObservation(results) {
  for (const result of results) {
    const availability = inventoryAvailability(result)
    if (availability) return availability
  }
  return { available: false, complete: false, sources: {} }
}

function inventoryResultAvailable(result) {
  return inventoryAvailability(result)?.available === true
}

function inventorySourceComplete(result, source) {
  return inventoryAvailability(result)?.sources?.[source]?.complete === true
}

function dashboardPartialError(results, observation) {
  const failed = results
    .map((result, index) => (result.status === 'rejected' ? DASHBOARD_DATA_LABELS[index] : null))
    .filter(Boolean)
  const observations = [observation, ...results.slice(0, 5).map(inventoryAvailability)]
  const incompleteSources = [...new Set(observations.flatMap((item) => Object.entries(item?.sources || {})
    .filter(([, source]) => source?.complete !== true)
    .map(([source]) => source)))]
  if (!failed.length && observations.every((item) => item?.available === true
    && ['storage', 'network', 'vm_config', 'vm_detail'].every((source) => item.sources?.[source]?.complete === true))
    && incompleteSources.length === 1 && incompleteSources[0] === 'guest_agent'
  ) {
    return null
  }
  const messages = []
  if (failed.length) messages.push(`불러오기 실패: ${failed.join(', ')}`)
  if (observations.some((item) => item?.complete !== true) || incompleteSources.length) {
    messages.push(`관찰 불완전: ${incompleteSources.length ? incompleteSources.join(', ') : 'inventory source metadata unavailable'}`)
  }
  return messages.length
    ? `일부 Dashboard 데이터를 신뢰할 수 없습니다 (${messages.join(' · ')}). 사용 가능한 inventory 데이터는 계속 표시합니다.`
    : null
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function optionalNumber(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function nodeIdOf(node) {
  return node.node_id || node.nodeId || node.id || node.name || 'unknown'
}

function nodeNameOf(node) {
  return node.display_name || node.displayName || node.name || nodeIdOf(node)
}

function statusTone(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'online' || normalized === 'running') return 'green'
  if (normalized === 'offline' || normalized === 'failed') return 'red'
  return 'yellow'
}

function toneClasses(tone) {
  const tones = {
    green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800',
    red: 'border-red-200 bg-red-50 text-red-700',
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return tones[tone] || tones.slate
}

function formatGb(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '-'
  return `${Math.round(number).toLocaleString()} GiB`
}

function metricValueClass(tone) {
  if (tone === 'green') return 'text-emerald-600'
  if (tone === 'yellow') return 'text-yellow-700'
  if (tone === 'red') return 'text-red-600'
  return 'text-slate-950'
}

function MetricTile({ label, value, sub, tone = 'slate', icon: Icon }) {
  return (
    <div className="min-w-0 px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
        {Icon && <Icon className="hidden h-4 w-4 text-slate-400 2xl:block" />}
      </div>
      <div className={`mt-1 text-xl font-semibold tracking-tight ${metricValueClass(tone)}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

function UsageBar({ value, tone = 'blue' }) {
  const color = tone === 'green' ? 'bg-emerald-500' : tone === 'red' ? 'bg-red-500' : tone === 'yellow' ? 'bg-yellow-500' : 'bg-blue-500'
  const width = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
  return (
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
    </div>
  )
}

function buildDashboardModel({
  cluster = {},
  nodes = [],
  vms = [],
  storages = [],
  networks = [],
  jobs = [],
  risks = [],
  availability = {},
  observation = {},
  vmObservation = observation,
}) {
  const clusterAvailable = availability.cluster === true
  const nodesAvailable = availability.nodes === true
  const vmsAvailable = availability.vms === true
  const storagesAvailable = availability.storages === true
  const networksAvailable = availability.networks === true
  const observedNodes = nodesAvailable ? asArray(nodes) : []
  const observedVms = vmsAvailable ? asArray(vms) : []
  const observedStorages = storagesAvailable ? asArray(storages) : []
  const observedNetworks = networksAvailable ? asArray(networks) : []

  const nodeRows = observedNodes.map((node) => {
    const id = nodeIdOf(node)
    const nodeVms = vmsAvailable
      ? observedVms.filter((vm) => (vm.node_id || vm.nodeId || vm.node) === id)
      : []
    const nodeStorages = storagesAvailable
      ? asArray(node.storage).length
        ? asArray(node.storage)
        : observedStorages.filter((storage) => (storage.node_id || storage.nodeId) === id)
      : []
    const nodeNetworks = networksAvailable
      ? asArray(node.networks).length
        ? asArray(node.networks)
        : observedNetworks.filter((network) => (network.node_id || network.nodeId) === id)
      : []
    const memoryTotalGb = asNumber(node.memory_total_mb ?? node.memoryTotalMb) / 1024
    const cpuUsagePercent = optionalNumber(node.cpu_usage_percent ?? node.cpuUsagePercent)
    const memoryUsedGb = asNumber(node.memory_used_mb ?? node.memoryUsedMb) / 1024
    const memoryUsagePercent = optionalNumber(node.memory_usage_percent ?? node.memoryUsagePercent)
    const storageTotalGb = nodeStorages.reduce((sum, storage) => sum + Math.max(0, asNumber(storage.total_gb ?? storage.totalGb)), 0)
    const storageFreeGb = nodeStorages.reduce((sum, storage) => sum + Math.max(0, asNumber(storage.free_gb ?? storage.freeGb)), 0)
    return {
      id,
      name: nodeNameOf(node),
      status: node.status || 'unknown',
      cpuTotal: optionalNumber(node.cpu_total),
      memoryTotalMb: optionalNumber(node.memory_total_mb),
      memoryUsedMb: optionalNumber(node.memory_used_mb),
      tone: statusTone(node.status),
      vmCount: vmsAvailable ? nodeVms.length : null,
      runningVmCount: vmsAvailable
        ? nodeVms.filter((vm) => String(vm.status || '').toLowerCase() === 'running').length
        : null,
      cpuLabel: cpuUsagePercent !== null ? `${Math.round(cpuUsagePercent)}%` : '-',
      cpuPercent: cpuUsagePercent !== null ? cpuUsagePercent : Number.NaN,
      memoryLabel: memoryUsagePercent !== null && memoryTotalGb > 0
        ? `${memoryUsedGb.toFixed(1)} / ${memoryTotalGb.toFixed(1)} GiB`
        : '-',
      memoryPercent: memoryUsagePercent !== null ? memoryUsagePercent : Number.NaN,
      storageLabel: storagesAvailable && storageTotalGb > 0 ? `${formatGb(storageFreeGb)} free` : '-',
      networks: nodeNetworks.map((network) => network.bridge_id || network.bridgeId).filter(Boolean),
      vmsAvailable,
      storagesAvailable,
      networksAvailable,
    }
  })

  const totals = aggregateValues(nodeRows, nodeRows.map(node => node.status === 'online' ? {
    cpu_percent: node.cpuPercent,
    memory_used_bytes: node.memoryUsedMb == null ? null : node.memoryUsedMb * 1024 ** 2,
    memory_total_bytes: node.memoryTotalMb > 0 ? node.memoryTotalMb * 1024 ** 2 : null,
  } : null))
  const onlineNodes = nodeRows.filter((node) => node.tone === 'green').length
  const runningVms = vmsAvailable
    ? observedVms.filter((vm) => String(vm.status || '').toLowerCase() === 'running').length
    : null
  const storageUsage = observedStorages.flatMap(storage => {
    const total = optionalNumber(storage.total_gb ?? storage.totalGb)
    const free = optionalNumber(storage.free_gb ?? storage.freeGb)
    return total > 0 && free !== null && free >= 0 && free <= total
      ? [{ node: storage.node_id || storage.nodeId, label: storage.storage_id || storage.storageId || 'storage', percent: (total - free) / total * 100 }] : []
  }).sort((a, b) => b.percent - a.percent)
  const highestStorage = storageUsage[0]
  const bridgeCount = networksAvailable
    ? new Set(observedNetworks.map((network) => `${network.node_id || network.nodeId}:${network.bridge_id || network.bridgeId}`).filter(Boolean)).size
    : null
  const incompleteSources = Object.entries(observation?.sources || {})
    .filter(([, source]) => source?.complete !== true)
    .map(([source]) => source)

  return {
    clusterId: clusterAvailable ? cluster.cluster_id || 'gjallar-mvp' : 'unavailable',
    nodeRows,
    storageUsage,
    totals,
    summary: {
      nodesAvailable,
      nodes: nodesAvailable ? `${onlineNodes}/${nodeRows.length}` : '-',
      nodeStatus: nodesAvailable && nodeRows.length > 0 ? `${onlineNodes}/${nodeRows.length} online` : 'unavailable',
      allObservedNodesOnline: nodesAvailable && nodeRows.length > 0 && onlineNodes === nodeRows.length,
      vms: vmsAvailable ? String(observedVms.length) : '-',
      runningVms,
      guestAgentMissing: vmsAvailable && Array.isArray(vmObservation?.sources?.guest_agent?.failed_targets)
        ? new Set(vmObservation.sources.guest_agent.failed_targets).size
        : null,
      storage: storagesAvailable && highestStorage ? `${highestStorage.percent.toFixed(1)}%` : '-',
      storageSub: storagesAvailable && highestStorage ? `${highestStorage.label} · 최대 사용률` : 'storage unavailable',
      bridges: bridgeCount,
      activeJobs: availability.jobs === true
        ? asArray(jobs).filter((job) => ['running', 'pending', 'in_progress', 'processing'].includes(String(job.status || '').toLowerCase())).length
        : null,
      redRisks: availability.risks === true
        ? asArray(risks).filter((risk) => String(risk.level || risk.risk_level || '').toLowerCase() === 'red').length
        : null,
      observationComplete: observation?.complete === true,
      incompleteSources,
    },
  }
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [snapshot, setSnapshot] = useState({
    cluster: {},
    nodes: [],
    vms: [],
    storages: [],
    networks: [],
    jobs: [],
    risks: [],
    observation: {
      available: false,
      complete: false,
      sources: {},
    },
    availability: {
      cluster: false,
      nodes: false,
      vms: false,
      storages: false,
      networks: false,
      jobs: false,
      risks: false,
    },
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [observedAt, setObservedAt] = useState('')

  const loadDashboard = async () => {
    setLoading(true)
    setError(null)
    const results = await Promise.allSettled([
      apiV1Client.clusterSummaryWithMeta(),
      apiV1Client.listNodesWithMeta(),
      apiV1Client.listVmsWithMeta(),
      apiV1Client.listStorageWithMeta(),
      apiV1Client.listNetworksWithMeta(),
      apiV1Client.listJobs(),
      apiV1Client.listRisks(),
    ])
    const [cluster, nodes, vms, storages, networks, jobs, risks] = results
    const observation = inventoryObservation(results.slice(0, 5))
    setSnapshot((previous) => ({
      cluster: settledInventoryValue(cluster, previous.cluster || {}),
      nodes: settledInventoryValue(nodes, previous.nodes || []),
      vms: settledInventoryValue(vms, previous.vms || []),
      storages: settledInventoryValue(storages, previous.storages || []),
      networks: settledInventoryValue(networks, previous.networks || []),
      jobs: jobs.status === 'fulfilled' ? jobs.value : previous.jobs || [],
      risks: risks.status === 'fulfilled' ? risks.value : previous.risks || [],
      observation,
      vmObservation: inventoryAvailability(vms),
      availability: {
        cluster: inventoryResultAvailable(cluster),
        nodes: inventoryResultAvailable(nodes),
        vms: inventoryResultAvailable(vms),
        storages: inventorySourceComplete(storages, 'storage'),
        networks: inventorySourceComplete(networks, 'network'),
        jobs: jobs.status === 'fulfilled',
        risks: risks.status === 'fulfilled',
      },
    }))
    setError(dashboardPartialError(results, observation))
    setObservedAt(new Date().toISOString())
    setLoading(false)
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  const model = useMemo(() => buildDashboardModel(snapshot), [snapshot])
  const healthTone = model.nodeRows.length === 0
    ? 'slate'
    : model.summary.allObservedNodesOnline ? 'green' : 'yellow'
  const riskMetricValue = model.summary.redRisks === null ? '-' : model.summary.redRisks
  const riskMetricTone = model.summary.redRisks > 0 ? 'red' : 'slate'
  const jobMetricContext = model.summary.activeJobs === null ? '작업 조회 불가' : `진행 중 생성 작업 ${model.summary.activeJobs}개`
  const riskMetricContext = model.summary.redRisks === null ? '위험 조회 불가' : 'Red 진단 · 선택 범위'
  const incompleteVmSources = model.summary.incompleteSources.filter((source) => ['vm_config', 'vm_detail'].includes(source))
  const guestAgentContext = model.summary.guestAgentMissing > 0
    ? ` · 내부 IP 확인 불가 ${model.summary.guestAgentMissing}대`
    : model.summary.guestAgentMissing === null && model.summary.incompleteSources.includes('guest_agent')
      ? ' · 내부 IP 관찰 일부 누락'
      : ''
  const vmMetricContext = model.summary.runningVms === null
    ? 'VM inventory unavailable'
    : `실행 ${model.summary.runningVms}대 · 선택 범위${guestAgentContext}${incompleteVmSources.length ? ` · detail partial (${incompleteVmSources.join(', ')})` : ''}`
  const nodeSummaryLabel = !model.summary.nodesAvailable
    ? 'Node inventory unavailable'
    : model.nodeRows.length > 0 ? onlineNodeLabel(model.nodeRows) : 'No nodes observed'

  return (
    <section className="space-y-3 gj-overview">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">클러스터 운영 현황</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span>{model.clusterId}</span><span>· 선택된 연결 범위</span>
            <span className={healthTone === 'green' ? 'text-teal-700' : 'text-amber-700'}>{loading ? '자원 조회 중…' : model.summary.nodeStatus}</span>
            <span>· {observedAt ? `조회 완료 ${new Date(observedAt).toLocaleTimeString()}` : '조회 중'}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={loadDashboard} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            새로고침
          </button>
          <button type="button" onClick={() => navigate('/instances')} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <List className="h-4 w-4" />
            VM 목록
          </button>
          <button type="button" onClick={() => navigate('/instances/create')} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800">
            <Plus className="h-4 w-4" />
            VM 생성
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 sm:grid-cols-3 min-[850px]:grid-cols-6 [&>div]:bg-white" aria-label="클러스터 핵심 지표">
        <MetricTile label="연결 노드" value={model.summary.nodes} sub="온라인 / 선택 노드" tone={healthTone} icon={Server} />
        <MetricTile label="전체 CPU 사용률" value={model.totals.cpu_percent == null ? '—' : `${model.totals.cpu_percent.toFixed(1)}%`} sub={`${model.nodeRows.reduce((sum, node) => sum + (node.cpuTotal || 0), 0)} CPU 기준`} icon={Activity} />
        <MetricTile label="전체 메모리 사용" value={model.totals.memory_used_bytes == null ? '—' : `${(model.totals.memory_used_bytes / 1024 ** 3).toFixed(1)} GiB`} sub={model.totals.memory_total_bytes == null ? '전체 용량 관찰 불가' : `/ ${(model.totals.memory_total_bytes / 1024 ** 3).toFixed(1)} GiB 전체`} icon={Server} />
        <MetricTile label="관리 VM" value={model.summary.vms} sub={vmMetricContext} icon={Activity} />
        <MetricTile label="스토리지 최대 사용" value={model.summary.storage} sub={model.summary.storageSub.replace(' · 최대 사용률', '')} icon={HardDrive} />
        <MetricTile label="위험 진단 · Red" value={riskMetricValue} sub={riskMetricContext} tone={riskMetricTone} icon={AlertTriangle} />
      </div>

      <div>
        <section className="gj-panel min-w-0 overflow-hidden">
          <div className="gj-panel-heading flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">전체 노드 비교</h2>

            </div>
            <span className={`inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClasses(healthTone)}`}>
              {nodeSummaryLabel}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">노드</th>
                  <th className="px-3 py-2 text-left font-semibold">상태</th>
                  <th className="px-3 py-2 text-left font-semibold">관리 VM</th>
                  <th className="px-3 py-2 text-left font-semibold">CPU 사용률</th>
                  <th className="px-3 py-2 text-left font-semibold">메모리 사용</th>
                  <th className="px-3 py-2 text-left font-semibold">브리지</th>
                  <th className="px-3 py-2 text-left font-semibold">스토리지 여유</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {model.nodeRows.length === 0 ? (
                  <tr>
                    <td className="px-5 py-6 text-sm text-slate-500" colSpan={7}>
                      {model.summary.nodesAvailable ? '노드 데이터가 없습니다.' : '노드 inventory가 unavailable 상태입니다.'}
                    </td>
                  </tr>
                ) : model.nodeRows.map((node) => (
                  <tr key={node.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2">
                      <Link className="font-semibold text-teal-800 hover:underline" to={`/nodes?node=${encodeURIComponent(node.id)}`}>{node.name} →</Link>

                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClasses(node.tone)}`}>
                        <span className={`h-2 w-2 rounded-full ${node.tone === 'green' ? 'bg-emerald-500' : node.tone === 'red' ? 'bg-red-500' : 'bg-yellow-400'}`} />
                        {node.status}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900">
                        {node.vmsAvailable ? `${node.runningVmCount}/${node.vmCount}` : '-'}
                      </div>
                      <div className="text-xs text-slate-500">{node.vmsAvailable ? '실행 / 선택 범위' : 'VM inventory unavailable'}</div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900">{node.cpuLabel}</div>
                      <UsageBar value={node.cpuPercent} tone={node.cpuPercent > 85 ? 'red' : node.cpuPercent > 65 ? 'yellow' : 'blue'} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900">{node.memoryLabel}</div>
                      <UsageBar value={node.memoryPercent} tone={node.memoryPercent > 85 ? 'red' : node.memoryPercent > 65 ? 'yellow' : 'green'} />
                    </td>
                    <td className="px-3 py-2 text-slate-700">
                      {node.networksAvailable ? node.networks.length ? node.networks.join(' / ') : '-' : 'unavailable'}
                    </td>
                    <td className="px-3 py-2 text-slate-700">{node.storagesAvailable ? node.storageLabel : 'unavailable'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <div className="grid items-start gap-3 min-[900px]:grid-cols-[minmax(0,1fr)_260px]">
        <ClusterTrends nodes={model.nodeRows} refreshKey={observedAt} />
        <div className="space-y-3">
          <section className="gj-panel" aria-label="운영 확인 사항">
            <header className="gj-panel-heading flex items-center justify-between"><h2 className="text-sm font-semibold">운영 확인 사항</h2><Link className="text-xs text-teal-700 hover:underline" to="/insights/risks">진단 →</Link></header>
            <div className="divide-y divide-slate-100 text-xs">
              <p className="px-3 py-2"><span className="font-semibold">노드 연결</span><span className="float-right">{nodeSummaryLabel}</span></p>
              <p className="px-3 py-2"><span className="font-semibold">스토리지 80% 이상</span><span className="float-right">{snapshot.availability.storages ? `${model.storageUsage.filter(item => item.percent >= 80).length}개 노드 경로` : '관찰 불가'}</span></p>
              <p className="px-3 py-2 text-slate-600">{jobMetricContext} · {model.summary.guestAgentMissing == null ? '게스트 관찰 확인 필요' : `게스트 IP 미확인 ${model.summary.guestAgentMissing}대`}</p>
            </div>
            <p className="border-t border-slate-100 px-3 py-2 text-[11px] text-slate-500">공유 스토리지는 노드마다 보일 수 있습니다. VM 수는 연결에서 선택한 범위입니다.</p>
          </section>
          <RecentOperations refreshKey={observedAt} />
        </div>
      </div>
    </section>
  )
}

function onlineNodeLabel(nodes) {
  const online = nodes.filter((node) => node.tone === 'green').length
  return `${online}/${nodes.length} online`
}
