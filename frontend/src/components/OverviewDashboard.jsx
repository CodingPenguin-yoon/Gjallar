import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Cpu,
  HardDrive,
  Loader2,
  Plus,
  RefreshCw,
  Server,
  Sparkles,
} from 'lucide-react'
import { getInstances, getNodesMonitoring, getTasks } from '../services/api'

const LIVE_TASK_STATUSES = new Set(['pending', 'running', 'deploying', 'in_progress', 'processing'])
const FAILED_TASK_STATUSES = new Set(['failed', 'error'])
const SUCCESS_TASK_STATUSES = new Set(['success', 'completed'])

function normalizeStatus(status) {
  return String(status || '').toLowerCase()
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function toPercent(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return Math.max(0, Math.min(100, parsed))
}

function storageUsagePercent(node) {
  const storages = Array.isArray(node?.storages) ? node.storages : []
  if (!storages.length) return 0
  return storages.reduce((max, storage) => Math.max(max, toPercent(storage?.usage_percent)), 0)
}

function getNodeStorages(node) {
  const storages = Array.isArray(node?.storages) ? node.storages : []
  return [...storages].sort((left, right) => {
    const leftLabel = String(left?.name || left?.storage_name || left?.storage_id || '')
    const rightLabel = String(right?.name || right?.storage_name || right?.storage_id || '')
    return leftLabel.localeCompare(rightLabel, undefined, { numeric: true, sensitivity: 'base' })
  })
}

function getStorageLabel(storage, index) {
  return storage?.name || storage?.storage_name || storage?.storage_id || `Storage ${index + 1}`
}

function getStorageKey(node, storage, index) {
  return storage?.storage_id || storage?.id || `${node?.node || node?.name || 'node'}-${getStorageLabel(storage, index)}-${index}`
}

function getNodeHealth(node) {
  if (node?.status !== 'online') {
    return {
      tone: 'critical',
      label: 'Offline',
      reason: 'Node is not online',
      cpu: toPercent(node?.cpu_usage_percent),
      memory: toPercent(node?.memory_usage_percent),
      storage: storageUsagePercent(node),
    }
  }

  const cpu = toPercent(node?.cpu_usage_percent)
  const memory = toPercent(node?.memory_usage_percent)
  const storage = storageUsagePercent(node)
  const peak = Math.max(cpu, memory, storage)

  if (peak >= 90) {
    return {
      tone: 'critical',
      label: 'Critical',
      reason: `Peak utilization ${peak.toFixed(0)}%`,
      cpu,
      memory,
      storage,
    }
  }

  if (peak >= 75) {
    return {
      tone: 'warning',
      label: 'Watch',
      reason: `Peak utilization ${peak.toFixed(0)}%`,
      cpu,
      memory,
      storage,
    }
  }

  return {
    tone: 'healthy',
    label: 'Stable',
    reason: 'Capacity is within normal range',
    cpu,
    memory,
    storage,
  }
}

function displayTaskName(task) {
  return task?.metadata?.server_name || `task-${task?.task_id?.slice(0, 8) || 'unknown'}`
}

function metricToneClass(tone) {
  if (tone === 'critical') return 'bg-red-50 text-red-700 border-red-200'
  if (tone === 'warning') return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-emerald-50 text-emerald-700 border-emerald-200'
}

function taskBadgeClass(status) {
  const normalized = normalizeStatus(status)
  if (FAILED_TASK_STATUSES.has(normalized)) return 'bg-red-50 text-red-700 border-red-200'
  if (LIVE_TASK_STATUSES.has(normalized)) return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-emerald-50 text-emerald-700 border-emerald-200'
}

function taskStatusLabel(status) {
  const normalized = normalizeStatus(status)
  if (FAILED_TASK_STATUSES.has(normalized)) return 'Failed'
  if (LIVE_TASK_STATUSES.has(normalized)) return 'Running'
  if (SUCCESS_TASK_STATUSES.has(normalized)) return 'Success'
  return status || 'Unknown'
}

function statusToneClass(tone) {
  if (tone === 'critical') return 'bg-red-50 text-red-700 border-red-200'
  if (tone === 'warning') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (tone === 'planned') return 'bg-slate-100 text-slate-700 border-slate-200'
  return 'bg-emerald-50 text-emerald-700 border-emerald-200'
}

function SummaryCard({ icon: Icon, label, value, hint, accent }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium text-slate-500">{label}</div>
          <div className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{value}</div>
          <div className="mt-2 text-sm text-slate-600">{hint}</div>
        </div>
        <div className={`rounded-2xl p-3 ${accent}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}

function MiniMeter({ label, value, toneClass }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500">
        <span className="min-w-0 truncate pr-2">{label}</span>
        <span className="font-semibold text-slate-700">{value.toFixed(0)}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div className={`h-full rounded-full transition-all ${toneClass}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}

function OverviewDashboard({ onNavigate }) {
  const [tasks, setTasks] = useState([])
  const [instances, setInstances] = useState([])
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [loadIssues, setLoadIssues] = useState([])
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null)
  const [refreshNonce, setRefreshNonce] = useState(0)

  useEffect(() => {
    let active = true

    const fetchOverviewData = async () => {
      const results = await Promise.allSettled([
        getTasks({ limit: 12, include_archived: false }),
        getInstances(),
        getNodesMonitoring(),
      ])

      if (!active) {
        return
      }

      const nextIssues = []

      if (results[0].status === 'fulfilled') {
        const taskData = results[0].value.data?.tasks || results[0].value.data || []
        setTasks(Array.isArray(taskData) ? taskData : [])
      } else {
        setTasks([])
        nextIssues.push('tasks')
      }

      if (results[1].status === 'fulfilled') {
        const instanceData =
          results[1].value.data?.vms || results[1].value.data?.instances || results[1].value.data || []
        setInstances(Array.isArray(instanceData) ? instanceData : [])
      } else {
        setInstances([])
        nextIssues.push('instances')
      }

      if (results[2].status === 'fulfilled') {
        const nodeData = results[2].value.data?.nodes || results[2].value.data || []
        setNodes(Array.isArray(nodeData) ? nodeData : [])
      } else {
        setNodes([])
        nextIssues.push('monitoring')
      }

      setLoadIssues(nextIssues)
      setLastUpdatedAt(new Date())
      setLoading(false)
      setRefreshing(false)
    }

    fetchOverviewData()
    const intervalId = setInterval(() => fetchOverviewData(), 30000)

    return () => {
      active = false
      clearInterval(intervalId)
    }
  }, [refreshNonce])

  const handleManualRefresh = () => {
    if (refreshing) {
      return
    }
    setRefreshing(true)
    setRefreshNonce((current) => current + 1)
  }

  const derived = useMemo(() => {
    const sortedTasks = [...tasks].sort((left, right) => {
      const leftTime = new Date(left?.updated_at || left?.created_at || 0).getTime()
      const rightTime = new Date(right?.updated_at || right?.created_at || 0).getTime()
      return rightTime - leftTime
    })

    const nodeHealth = [...nodes]
      .map((node) => ({ node, health: getNodeHealth(node) }))
      .sort((left, right) => {
        const score = { critical: 2, warning: 1, healthy: 0 }
        return score[right.health.tone] - score[left.health.tone]
      })

    return {
      runningTasks: sortedTasks.filter((task) => LIVE_TASK_STATUSES.has(normalizeStatus(task?.status))),
      failedTasks: sortedTasks.filter((task) => FAILED_TASK_STATUSES.has(normalizeStatus(task?.status))),
      onlineNodes: nodes.filter((node) => node?.status === 'online'),
      riskyNodes: nodeHealth.filter(({ health }) => health.tone !== 'healthy'),
      recentTasks: sortedTasks.slice(0, 6),
      latestFinishedTask:
        sortedTasks.find((task) => !LIVE_TASK_STATUSES.has(normalizeStatus(task?.status))) || null,
      nodeHealth: nodeHealth.slice(0, 4),
    }
  }, [instances, nodes, tasks])

  const quickActions = [
    {
      title: 'Create Instance',
      description: '템플릿, 스토리지, 네트워크를 선택해서 새 VM을 시작합니다.',
      icon: Plus,
      onClick: () => onNavigate('/create'),
      accent: 'bg-sky-100 text-sky-700',
    },
    {
      title: 'Open Task Board',
      description: '현재 배포와 실패 작업을 한 곳에서 추적합니다.',
      icon: Clock3,
      onClick: () => onNavigate('/tasks'),
      accent: 'bg-amber-100 text-amber-700',
    },
    {
      title: 'Check Monitoring',
      description: '노드 상태와 자원 압박을 빠르게 확인합니다.',
      icon: Activity,
      onClick: () => onNavigate('/monitoring'),
      accent: 'bg-emerald-100 text-emerald-700',
    },
    {
      title: 'Ask Assistant',
      description: '자연어로 현재 인프라를 조회하거나 액션을 제안받습니다.',
      icon: Sparkles,
      onClick: () => onNavigate('/assistant'),
      accent: 'bg-orange-100 text-orange-700',
    },
  ]

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Operations</div>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
              운영 현황과 주요 액션
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              진행 중인 작업, 주의가 필요한 상태, 자주 사용하는 도구를 한곳에서 확인합니다.
            </p>
          </div>
          <div className="text-xs text-slate-500">
            {lastUpdatedAt ? `최근 동기화 ${formatDateTime(lastUpdatedAt)}` : '첫 동기화 대기 중'}
          </div>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {quickActions.map((action) => {
            const Icon = action.icon
            return (
              <button
                key={action.title}
                type="button"
                onClick={action.onClick}
                className="flex items-start gap-3 rounded-2xl border border-slate-200 px-4 py-4 text-left transition hover:border-slate-300 hover:bg-slate-50"
              >
                <div className={`rounded-2xl p-3 ${action.accent}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-slate-900">{action.title}</div>
                  <div className="mt-1 text-sm text-slate-600">{action.description}</div>
                </div>
                <ArrowRight className="mt-1 h-4 w-4 text-slate-400" />
              </button>
            )
          })}
        </div>
      </section>

      {loadIssues.length > 0 && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            일부 데이터를 아직 불러오지 못했습니다. 누락된 영역:
            {' '}
            <span className="font-semibold">{loadIssues.join(', ')}</span>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          icon={Server}
          label="Active Instances"
          value={instances.length}
          hint="현재 조회된 VM 수"
          accent="bg-sky-100 text-sky-700"
        />
        <SummaryCard
          icon={Activity}
          label="Online Nodes"
          value={`${derived.onlineNodes.length}/${nodes.length || 0}`}
          hint="모니터링 응답 기준 온라인 노드"
          accent="bg-emerald-100 text-emerald-700"
        />
        <SummaryCard
          icon={Clock3}
          label="Running Tasks"
          value={derived.runningTasks.length}
          hint="진행 중인 배포 및 작업"
          accent="bg-amber-100 text-amber-700"
        />
        <SummaryCard
          icon={AlertTriangle}
          label="Needs Attention"
          value={derived.failedTasks.length + derived.riskyNodes.length}
          hint="실패 작업과 위험 노드 합계"
          accent="bg-rose-100 text-rose-700"
        />
      </div>

      <div className="space-y-6">
        <div className="grid gap-6 xl:grid-cols-[1.2fr,0.8fr]">
          <section className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">Attention Queue</h3>
                <p className="mt-1 text-sm text-slate-500">먼저 확인해야 할 작업과 노드를 위에서부터 보여줍니다.</p>
              </div>
              <button
                type="button"
                onClick={() => onNavigate('/tasks')}
                className="inline-flex items-center gap-1 text-sm font-semibold text-slate-700 transition hover:text-slate-950"
              >
                Open Task Board
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-5 flex-1 space-y-3">
              {derived.failedTasks.slice(0, 3).map((task) => (
                <button
                  key={task.task_id}
                  type="button"
                  onClick={() => onNavigate('/tasks', { state: { focusTaskId: task.task_id } })}
                  className="w-full rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-left transition hover:border-red-300 hover:bg-red-100/70"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm font-semibold text-red-900">{displayTaskName(task)}</div>
                      <div className="mt-1 text-xs text-red-700">Task ID: {task.task_id}</div>
                    </div>
                    <span className="rounded-full border border-red-200 bg-white px-2.5 py-1 text-xs font-semibold text-red-700">
                      Failed Task
                    </span>
                  </div>
                  <div className="mt-3 text-sm text-red-800">
                    {task.progress_text || '오류 상세를 확인해 주세요.'}
                  </div>
                </button>
              ))}

              {derived.riskyNodes.slice(0, 3).map(({ node, health }) => (
                <button
                  key={node.node || node.name}
                  type="button"
                  onClick={() => onNavigate('/monitoring')}
                  className="w-full rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-left transition hover:border-amber-300 hover:bg-amber-100/70"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm font-semibold text-amber-950">{node.name || node.node}</div>
                      <div className="mt-1 text-xs text-amber-700">{health.reason}</div>
                    </div>
                    <span className="rounded-full border border-amber-200 bg-white px-2.5 py-1 text-xs font-semibold text-amber-700">
                      {health.label}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    <MiniMeter label="CPU" value={health.cpu} toneClass="bg-amber-500" />
                    <MiniMeter label="Memory" value={health.memory} toneClass="bg-amber-500" />
                    <MiniMeter label="Storage" value={health.storage} toneClass="bg-amber-500" />
                  </div>
                </button>
              ))}

              {derived.failedTasks.length === 0 && derived.riskyNodes.length === 0 && !loading && (
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-5">
                  <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
                    <CheckCircle2 className="h-4 w-4" />
                    Immediate issues are clear
                  </div>
                  <p className="mt-2 text-sm text-emerald-700">
                    실패 작업이나 자원 임계 노드가 없습니다. 지금은 신규 배포나 운영 점검에 집중해도 됩니다.
                  </p>
                </div>
              )}

              {loading && (
                <div className="flex items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 px-4 py-12 text-slate-500">
                  <Loader2 className="mr-3 h-5 w-5 animate-spin" />
                  Overview data is loading...
                </div>
              )}
            </div>
          </section>

          <section className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">Recent Activity</h3>
                <p className="mt-1 text-sm text-slate-500">가장 최근 작업을 시간순으로 모아 보여줍니다.</p>
              </div>
              <button
                type="button"
                onClick={handleManualRefresh}
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                {refreshing ? 'Refreshing' : 'Refresh'}
              </button>
            </div>
            <div className="mt-5 flex-1 space-y-3">
              {derived.recentTasks.map((task) => (
                <button
                  key={task.task_id}
                  type="button"
                  onClick={() => onNavigate('/tasks', { state: { focusTaskId: task.task_id } })}
                  className="w-full rounded-2xl border border-slate-200 px-4 py-4 text-left transition hover:border-slate-300 hover:bg-slate-50"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900">{displayTaskName(task)}</div>
                      <div className="mt-1 text-xs text-slate-500">{formatDateTime(task.updated_at || task.created_at)}</div>
                    </div>
                    <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${taskBadgeClass(task.status)}`}>
                      {task.status || 'unknown'}
                    </span>
                  </div>
                  <div className="mt-3 text-sm text-slate-600">
                    {task.progress_text || `Progress ${Number(task.progress || 0)}%`}
                  </div>
                </button>
              ))}

              {!loading && derived.recentTasks.length === 0 && (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-12 text-center text-sm text-slate-500">
                  아직 표시할 작업이 없습니다.
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.2fr,0.8fr]">
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">Infrastructure Snapshot</h3>
                <p className="mt-1 text-sm text-slate-500">노드별 상태를 축약해서 보여주는 운영용 요약판입니다.</p>
              </div>
              <button
                type="button"
                onClick={() => onNavigate('/monitoring')}
                className="inline-flex items-center gap-1 text-sm font-semibold text-slate-700 transition hover:text-slate-950"
              >
                Open Monitoring
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              {derived.nodeHealth.map(({ node, health }) => {
                const storages = getNodeStorages(node)

                return (
                  <div key={node.node || node.name} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">{node.name || node.node}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          Uptime {typeof node.uptime === 'number' ? `${Math.floor(node.uptime / 3600)}h` : '-'}
                        </div>
                      </div>
                      <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${metricToneClass(health.tone)}`}>
                        {health.label}
                      </span>
                    </div>
                    <div className="mt-4 space-y-3">
                      <MiniMeter label="CPU" value={health.cpu} toneClass="bg-sky-500" />
                      <MiniMeter label="Memory" value={health.memory} toneClass="bg-emerald-500" />
                      {storages.length > 0 ? (
                        <div className="space-y-2">
                          {storages.map((storage, index) => (
                            <MiniMeter
                              key={getStorageKey(node, storage, index)}
                              label={getStorageLabel(storage, index)}
                              value={toPercent(storage?.usage_percent)}
                              toneClass="bg-amber-500"
                            />
                          ))}
                        </div>
                      ) : (
                        <MiniMeter label="Storage" value={health.storage} toneClass="bg-amber-500" />
                      )}
                    </div>
                    <div className="mt-4 flex items-center gap-4 text-xs text-slate-500">
                      <span className="inline-flex items-center gap-1">
                        <Cpu className="h-3.5 w-3.5" />
                        CPU
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Activity className="h-3.5 w-3.5" />
                        Memory
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <HardDrive className="h-3.5 w-3.5" />
                        Storage
                      </span>
                    </div>
                  </div>
                )
              })}

              {!loading && derived.nodeHealth.length === 0 && (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-12 text-center text-sm text-slate-500 lg:col-span-2">
                  모니터링 데이터가 아직 없습니다.
                </div>
              )}
            </div>
          </section>
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">CI / Delivery</h3>
                <p className="mt-1 text-sm text-slate-500">
                  현재 배포 엔진 상태와 향후 GitLab runner 연동 지점을 함께 보여줍니다.
                </p>
              </div>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">
                GitLab pending
              </span>
            </div>

            <div className="mt-5 space-y-3">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Runner Telemetry</div>
                    <div className="mt-1 text-sm text-slate-600">
                      GitLab runner / pipeline queue 데이터 소스는 아직 연결되지 않았습니다.
                    </div>
                  </div>
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusToneClass('planned')}`}>
                    Planned
                  </span>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Deployment Engine</div>
                    <div className="mt-1 text-sm text-slate-600">
                      {derived.runningTasks.length > 0
                        ? `${derived.runningTasks.length}개 작업이 현재 실행 중입니다.`
                        : '현재 실행 중인 배포 작업이 없습니다.'}
                    </div>
                  </div>
                  <span
                    className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusToneClass(
                      derived.runningTasks.length > 0 ? 'warning' : 'healthy'
                    )}`}
                  >
                    {derived.runningTasks.length > 0 ? 'Active' : 'Idle'}
                  </span>
                </div>
                {derived.runningTasks.length > 0 && (
                  <div className="mt-3 text-xs text-slate-500">
                    현재 작업: {displayTaskName(derived.runningTasks[0])}
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-slate-200 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Latest Delivery</div>
                    <div className="mt-1 text-sm text-slate-600">
                      {derived.latestFinishedTask
                        ? `${displayTaskName(derived.latestFinishedTask)} 배포 결과`
                        : '아직 기록된 배포 결과가 없습니다.'}
                    </div>
                  </div>
                  {derived.latestFinishedTask && (
                    <span
                      className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${taskBadgeClass(
                        derived.latestFinishedTask.status
                      )}`}
                    >
                      {taskStatusLabel(derived.latestFinishedTask.status)}
                    </span>
                  )}
                </div>
                {derived.latestFinishedTask && (
                  <div className="mt-3 text-xs text-slate-500">
                    {formatDateTime(derived.latestFinishedTask.updated_at || derived.latestFinishedTask.created_at)}
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={() => onNavigate('/tasks')}
                className="flex w-full items-start justify-between gap-4 rounded-2xl border border-slate-200 px-4 py-4 text-left transition hover:border-slate-300 hover:bg-slate-50"
              >
                <div>
                  <div className="text-sm font-semibold text-slate-900">Open Delivery Timeline</div>
                  <div className="mt-1 text-sm text-slate-600">
                    실시간 로그와 최근 배포 결과는 Task Board에서 계속 추적할 수 있습니다.
                  </div>
                </div>
                <ArrowRight className="mt-1 h-4 w-4 text-slate-400" />
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

export default OverviewDashboard
