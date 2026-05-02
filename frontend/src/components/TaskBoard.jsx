import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  Archive,
  CheckCircle2,
  Clock3,
  History,
  Info,
  Loader2,
  RefreshCw,
  Search,
  Server,
  TerminalSquare,
  XCircle,
} from 'lucide-react'
import {
  archiveTask,
  createTaskEventStream,
  getTaskDetail,
  getTasks,
} from '../services/api'

const LIVE_STATUS = new Set(['pending', 'running', 'deploying', 'in_progress', 'processing'])
const DONE_STATUS = new Set(['success', 'completed', 'failed', 'error'])
const LOG_PHASE_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'tf_init', label: 'TF Init' },
  { id: 'tf_plan', label: 'TF Plan' },
  { id: 'tf_apply', label: 'TF Apply' },
  { id: 'ansible', label: 'Ansible' },
  { id: 'error', label: 'Error' },
]

function normalizeStatus(status) {
  return String(status || '').toLowerCase()
}

function isLiveStatus(status) {
  return LIVE_STATUS.has(normalizeStatus(status))
}

function isDoneStatus(status) {
  return DONE_STATUS.has(normalizeStatus(status))
}

function stripAnsiCodes(line) {
  const text = String(line || '')
  return text
    .replace(/(?:\u001b\[|\u009b)[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\[[0-9;]*m/g, '')
}

function normalizeRepeatKey(line) {
  return stripAnsiCodes(line)
    .replace(/^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\]\s*/, '')
    .replace(/\[[0-9]+m[0-9]+s elapsed\]/gi, '[elapsed]')
    .replace(/\[[0-9]+s elapsed\]/gi, '[elapsed]')
    .replace(/\s+/g, ' ')
    .trim()
}

function detectExplicitLogPhase(lineLower) {
  if (lineLower.includes('terraform init') || lineLower.includes('[1/4]')) {
    return 'tf_init'
  }
  if (lineLower.includes('terraform plan') || lineLower.includes('[2/4]')) {
    return 'tf_plan'
  }
  if (lineLower.includes('terraform apply') || lineLower.includes('[3/4]')) {
    return 'tf_apply'
  }
  if (lineLower.includes('ansible playbook') || lineLower.includes('ansible-playbook') || lineLower.includes('[4/4]')) {
    return 'ansible'
  }
  return null
}

function classifyLogPhase(line, currentPhase = 'other') {
  const lineLower = stripAnsiCodes(line).toLowerCase()
  const explicitPhase = detectExplicitLogPhase(lineLower)
  if (explicitPhase) {
    return { phase: explicitPhase, nextPhase: explicitPhase }
  }

  if (lineLower.includes('error') || lineLower.includes('failed') || lineLower.includes('exception')) {
    return { phase: 'error', nextPhase: currentPhase }
  }

  if (
    lineLower.includes('still creating') ||
    lineLower.includes('proxmox_virtual_environment_vm') ||
    lineLower.includes('disk move') ||
    lineLower.includes('transferred ')
  ) {
    return { phase: 'tf_apply', nextPhase: 'tf_apply' }
  }

  if (currentPhase && currentPhase !== 'other') {
    return { phase: currentPhase, nextPhase: currentPhase }
  }

  return { phase: 'other', nextPhase: currentPhase }
}

function buildPhaseTaggedLogs(logs) {
  let currentPhase = 'other'
  return (logs || []).map((raw, index) => {
    const { phase, nextPhase } = classifyLogPhase(raw, currentPhase)
    currentPhase = nextPhase
    return {
      index,
      text: stripAnsiCodes(raw),
      phase,
      repeatKey: normalizeRepeatKey(raw),
    }
  })
}

function collapseConsecutiveLogs(entries) {
  const collapsed = []
  for (const entry of entries) {
    const last = collapsed[collapsed.length - 1]
    if (last && last.repeatKey === entry.repeatKey && last.phase === entry.phase) {
      last.repeat += 1
      last.text = entry.text
      continue
    }
    collapsed.push({ ...entry, repeat: 1 })
  }
  return collapsed
}

function formatDateTime(dateText) {
  if (!dateText) return '-'
  const date = new Date(dateText)
  if (Number.isNaN(date.getTime())) return dateText
  return date.toLocaleString()
}

function toProgress(value) {
  const parsed = Number(value)
  if (Number.isNaN(parsed)) return 0
  return Math.max(0, Math.min(100, parsed))
}

function displayName(task) {
  const metadata = task?.metadata || {}
  return metadata.server_name || `instance-${task.task_id?.slice(0, 8) || 'unknown'}`
}

function statusBadge(status) {
  const normalized = normalizeStatus(status)

  if (normalized === 'success' || normalized === 'completed') {
    return {
      icon: CheckCircle2,
      label: 'Success',
      className: 'bg-green-50 text-green-700 border-green-200',
    }
  }

  if (normalized === 'failed' || normalized === 'error') {
    return {
      icon: XCircle,
      label: 'Failed',
      className: 'bg-red-50 text-red-700 border-red-200',
    }
  }

  if (normalized === 'pending') {
    return {
      icon: Clock3,
      label: 'Pending',
      className: 'bg-amber-50 text-amber-700 border-amber-200',
    }
  }

  return {
    icon: Loader2,
    label: status || 'Running',
    className: 'bg-blue-50 text-blue-700 border-blue-200',
  }
}

function normalizeTaskSummary(task) {
  if (!task) return null
  return {
    task_id: task.task_id,
    status: task.status,
    created_at: task.created_at,
    updated_at: task.updated_at,
    metadata: task.metadata || {},
    progress: Number(task.progress || 0),
    progress_text: task.progress_text || '',
    progress_source: task.progress_source || '',
    archived: !!task.archived,
    archived_at: task.archived_at || null,
    total_logs: Number(task.total_logs || 0),
    last_log: task.last_log || null,
  }
}

function sortTasksByCreatedAt(tasks) {
  return [...tasks].sort((a, b) => {
    const aTime = new Date(a.created_at || 0).getTime()
    const bTime = new Date(b.created_at || 0).getTime()
    return bTime - aTime
  })
}

function upsertTask(tasks, task) {
  if (!task || !task.task_id) return tasks
  const next = [...tasks]
  const index = next.findIndex((item) => item.task_id === task.task_id)
  if (index === -1) {
    next.push(task)
  } else {
    next[index] = { ...next[index], ...task }
  }
  return sortTasksByCreatedAt(next)
}

function TaskCard({ task, selected, onSelect }) {
  const badge = statusBadge(task.status)
  const BadgeIcon = badge.icon
  const progress = toProgress(task.progress)
  const isRunning = isLiveStatus(task.status)

  return (
    <button
      type="button"
      onClick={() => onSelect(task.task_id)}
      className={`w-full p-4 rounded-lg border text-left transition-all ${
        selected
          ? 'border-blue-500 bg-blue-50/60 shadow-sm'
          : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-900 truncate">{displayName(task)}</div>
          <div className="text-xs text-gray-500 mt-1 truncate">Task ID: {task.task_id}</div>
        </div>
        <div className="flex items-center gap-2">
          {task.archived && (
            <span className="inline-flex items-center px-2 py-1 rounded-full border border-gray-300 text-[10px] font-semibold text-gray-600 bg-gray-100">
              ARCHIVED
            </span>
          )}
          <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full border text-xs font-semibold ${badge.className}`}>
            <BadgeIcon className={`w-3.5 h-3.5 ${isLiveStatus(task.status) ? 'animate-spin' : ''}`} />
            {badge.label}
          </span>
        </div>
      </div>
      <div className="mt-3 text-xs text-gray-600 space-y-1">
        <div>Created: {formatDateTime(task.created_at)}</div>
        <div>Updated: {formatDateTime(task.updated_at)}</div>
        <div className="flex items-center justify-between">
          <span>Progress</span>
          <span className="font-semibold text-gray-800">{progress.toFixed(2)}%</span>
        </div>
        <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all ${isRunning ? 'bg-blue-500' : 'bg-green-500'}`}
            style={{ width: `${progress}%` }}
          />
        </div>
        {task.progress_text && (
          <div className="text-[11px] text-gray-500 line-clamp-1">{task.progress_text}</div>
        )}
      </div>
      {task.last_log && (
        <div className="mt-3 p-2 rounded bg-gray-900 text-[11px] text-gray-300 line-clamp-2 font-mono">
          {stripAnsiCodes(task.last_log)}
        </div>
      )}
    </button>
  )
}

function TaskDetailPanel({ taskDetail, onArchiveToggle, archivePending }) {
  const [logFilter, setLogFilter] = useState('all')
  const [followLatest, setFollowLatest] = useState(true)
  const logContainerRef = useRef(null)
  const prevTaskIdRef = useRef(taskDetail?.task_id || '')
  const taskId = taskDetail?.task_id || ''
  const taskLogs = taskDetail?.logs || []
  const metadata = taskDetail?.metadata || {}
  const metadataEntries = useMemo(() => Object.entries(metadata), [metadata])
  const badge = statusBadge(taskDetail?.status)
  const BadgeIcon = badge.icon
  const progress = toProgress(taskDetail?.progress)
  const progressSource = taskDetail?.progress_source || '-'
  const canArchive = isDoneStatus(taskDetail?.status) || taskDetail?.archived
  const phaseTaggedLogs = useMemo(
    () => buildPhaseTaggedLogs(taskLogs),
    [taskLogs],
  )
  const filteredLogs = useMemo(
    () => (logFilter === 'all' ? phaseTaggedLogs : phaseTaggedLogs.filter((entry) => entry.phase === logFilter)),
    [phaseTaggedLogs, logFilter],
  )
  const collapsedLogs = useMemo(
    () => collapseConsecutiveLogs(filteredLogs),
    [filteredLogs],
  )
  const phaseCountMap = useMemo(() => {
    const map = { all: phaseTaggedLogs.length }
    for (const entry of phaseTaggedLogs) {
      map[entry.phase] = (map[entry.phase] || 0) + 1
    }
    return map
  }, [phaseTaggedLogs])

  useEffect(() => {
    if (!taskId) {
      prevTaskIdRef.current = ''
      setLogFilter('all')
      setFollowLatest(true)
      return
    }

    if (prevTaskIdRef.current !== taskId) {
      prevTaskIdRef.current = taskId
      setLogFilter('all')
      setFollowLatest(true)
    }
  }, [taskId])

  useEffect(() => {
    if (!taskId) {
      return
    }

    if (!followLatest) {
      return
    }
    const container = logContainerRef.current
    if (!container) {
      return
    }
    container.scrollTop = container.scrollHeight
  }, [collapsedLogs, followLatest, taskId])

  const handleLogScroll = useCallback(() => {
    const container = logContainerRef.current
    if (!container) {
      return
    }
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight
    if (distanceToBottom > 24 && followLatest) {
      setFollowLatest(false)
    }
  }, [followLatest])

  const resumeFollowLatest = useCallback(() => {
    setFollowLatest(true)
    const container = logContainerRef.current
    if (container) {
      container.scrollTop = container.scrollHeight
    }
  }, [])

  if (!taskDetail) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center gap-2 text-gray-600">
          <Info className="w-4 h-4" />
          <span className="text-sm">Select a task to view details.</span>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-200">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-base font-semibold text-gray-900 truncate">{displayName(taskDetail)}</h3>
          <div className="flex items-center gap-2">
            {taskDetail.archived && (
              <span className="inline-flex items-center px-2 py-1 rounded-full border border-gray-300 text-[10px] font-semibold text-gray-600 bg-gray-100">
                ARCHIVED
              </span>
            )}
            <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full border text-xs font-semibold ${badge.className}`}>
              <BadgeIcon className={`w-3.5 h-3.5 ${isLiveStatus(taskDetail.status) ? 'animate-spin' : ''}`} />
              {badge.label}
            </span>
            {canArchive && (
              <button
                type="button"
                onClick={() => onArchiveToggle(taskDetail.task_id, !taskDetail.archived)}
                disabled={archivePending}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
              >
                <Archive className="w-3.5 h-3.5" />
                {taskDetail.archived ? 'Unarchive' : 'Archive'}
              </button>
            )}
          </div>
        </div>
        <div className="text-xs text-gray-500 mt-1">Task ID: {taskDetail.task_id}</div>
      </div>

      <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="space-y-3">
          <div className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Server className="w-4 h-4 text-blue-600" />
            Task Info
          </div>
          <div className="text-sm text-gray-700 space-y-2">
            <div>Created: {formatDateTime(taskDetail.created_at)}</div>
            <div>Updated: {formatDateTime(taskDetail.updated_at)}</div>
            <div>Total Logs: {taskDetail.total_logs || 0}</div>
            <div>Progress Source: {progressSource}</div>
            <div>Progress: {progress.toFixed(2)}%</div>
            <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  isLiveStatus(taskDetail.status) ? 'bg-blue-500' : 'bg-green-500'
                }`}
                style={{ width: `${progress}%` }}
              />
            </div>
            {taskDetail.progress_text && (
              <div className="text-xs text-gray-500">{taskDetail.progress_text}</div>
            )}
          </div>
          <div className="pt-2 border-t border-gray-200">
            <div className="text-sm font-semibold text-gray-800 mb-2">Metadata</div>
            {metadataEntries.length === 0 ? (
              <div className="text-sm text-gray-500">No metadata</div>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {metadataEntries.map(([key, value]) => (
                  <div key={key} className="grid grid-cols-[140px_1fr] gap-2 text-sm">
                    <div className="text-gray-500 truncate">{key}</div>
                    <div className="text-gray-800 break-all">
                      {Array.isArray(value) ? value.join(', ') : String(value)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <TerminalSquare className="w-4 h-4 text-blue-600" />
              Logs
            </div>
            <button
              type="button"
              onClick={resumeFollowLatest}
              className={`px-2 py-1 rounded-md text-xs font-medium border ${
                followLatest
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
              }`}
            >
              {followLatest ? 'Following Latest' : 'Follow Latest'}
            </button>
          </div>
          <div className="flex flex-wrap gap-2 mb-3">
            {LOG_PHASE_FILTERS.map((filter) => (
              <button
                key={filter.id}
                type="button"
                onClick={() => setLogFilter(filter.id)}
                className={`px-2.5 py-1 rounded-full border text-[11px] font-medium ${
                  logFilter === filter.id
                    ? 'border-blue-400 bg-blue-50 text-blue-700'
                    : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                {filter.label} ({phaseCountMap[filter.id] || 0})
              </button>
            ))}
          </div>
          <div
            ref={logContainerRef}
            onScroll={handleLogScroll}
            className="bg-gray-900 rounded-md p-3 h-80 overflow-y-auto font-mono text-xs border border-gray-700"
          >
            {collapsedLogs.length ? (
              <div className="space-y-1.5">
                {collapsedLogs.map((entry) => (
                  <div key={`${taskDetail.task_id}-${entry.index}`} className="text-gray-200 break-all flex items-start justify-between gap-3">
                    <span>{entry.text}</span>
                    {entry.repeat > 1 && (
                      <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] bg-gray-700 text-gray-200">
                        x{entry.repeat}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-gray-500">
                {taskDetail.logs?.length ? 'No logs for selected phase' : 'No logs'}
              </div>
            )}
          </div>
          {!followLatest && (
            <div className="mt-2 text-[11px] text-amber-600">
              최신 로그 추적이 일시정지되었습니다. `Follow Latest`를 누르면 최신으로 이동합니다.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TaskBoard({ focusTaskId }) {
  const [tasks, setTasks] = useState([])
  const [selectedTaskId, setSelectedTaskId] = useState(focusTaskId || null)
  const [selectedTaskDetail, setSelectedTaskDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [activeTab, setActiveTab] = useState('live')
  const [refreshing, setRefreshing] = useState(false)
  const [archivePendingTaskId, setArchivePendingTaskId] = useState('')

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)

  const lastEventSeqRef = useRef(0)
  const eventSourceRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const unmountedRef = useRef(false)

  useEffect(() => {
    if (focusTaskId) {
      setSelectedTaskId(focusTaskId)
    }
  }, [focusTaskId])

  const fetchTaskList = useCallback(
    async (silent = false) => {
      if (!silent) {
        setLoading(true)
      }
      try {
        const response = await getTasks({
          limit: 500,
          include_archived: true,
        })
        const nextTasks = sortTasksByCreatedAt(
          (response.data?.tasks || []).map((task) => normalizeTaskSummary(task)).filter(Boolean),
        )
        setTasks(nextTasks)
        setErrorMessage('')

        setSelectedTaskId((prev) => {
          if (prev && nextTasks.some((task) => task.task_id === prev)) {
            return prev
          }
          if (focusTaskId && nextTasks.some((task) => task.task_id === focusTaskId)) {
            return focusTaskId
          }
          return nextTasks[0]?.task_id || null
        })
      } catch (error) {
        const message = error.response?.data?.detail || error.message || 'Failed to load tasks'
        setErrorMessage(message)
      } finally {
        if (!silent) {
          setLoading(false)
        }
      }
    },
    [focusTaskId],
  )

  const fetchTask = useCallback(async (taskId) => {
    if (!taskId) {
      setSelectedTaskDetail(null)
      return
    }

    try {
      const response = await getTaskDetail(taskId)
      const detail = response.data || null
      setSelectedTaskDetail(detail)
      if (detail) {
        const summary = normalizeTaskSummary(detail)
        if (summary) {
          setTasks((prev) => upsertTask(prev, summary))
        }
      }
    } catch (error) {
      const message = error.response?.data?.detail || error.message || 'Failed to load task detail'
      setErrorMessage(message)
    }
  }, [])

  const handleTaskEvent = useCallback((eventData) => {
    if (!eventData || typeof eventData !== 'object') return

    const seq = Number(eventData.seq || 0)
    if (seq > 0) {
      lastEventSeqRef.current = Math.max(lastEventSeqRef.current, seq)
    }

    const taskId = eventData.task_id
    if (!taskId) return

    if (eventData.type === 'task_removed') {
      setTasks((prev) => prev.filter((task) => task.task_id !== taskId))
      setSelectedTaskId((prev) => (prev === taskId ? null : prev))
      setSelectedTaskDetail((prev) => (prev?.task_id === taskId ? null : prev))
      return
    }

    const nextSummary = normalizeTaskSummary(eventData.task)
    if (!nextSummary) {
      return
    }

    setTasks((prev) => upsertTask(prev, nextSummary))
    setSelectedTaskDetail((prev) => {
      if (!prev || prev.task_id !== taskId) {
        return prev
      }

      const merged = {
        ...prev,
        ...nextSummary,
      }
      const existingLogs = Array.isArray(prev.logs) ? [...prev.logs] : []
      const incrementalLog = typeof eventData.log_line === 'string' ? eventData.log_line : ''
      const summaryLastLog = nextSummary.last_log || ''
      const candidateLog = incrementalLog || summaryLastLog
      if (candidateLog && (!existingLogs.length || existingLogs[existingLogs.length - 1] !== candidateLog)) {
        existingLogs.push(candidateLog)
      }
      const eventTotalLogs = Number(eventData.total_logs || 0)
      merged.logs = existingLogs
      merged.total_logs = Math.max(
        Number(prev.total_logs || 0),
        Number(nextSummary.total_logs || 0),
        Number.isNaN(eventTotalLogs) ? 0 : eventTotalLogs,
        existingLogs.length,
      )
      if (candidateLog) {
        merged.last_log = candidateLog
      }
      return merged
    })
  }, [])

  const connectTaskStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }

    const stream = createTaskEventStream({
      includeArchived: true,
      lastEventId: lastEventSeqRef.current || null,
    })
    eventSourceRef.current = stream

    const onTaskEvent = (event) => {
      try {
        const payload = JSON.parse(event.data)
        handleTaskEvent(payload)
      } catch (error) {
        console.error('Failed to parse task stream event:', error)
      }
    }

    stream.addEventListener('task', onTaskEvent)
    stream.onmessage = onTaskEvent
    stream.onerror = () => {
      stream.close()
      if (unmountedRef.current) {
        return
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      reconnectTimerRef.current = setTimeout(() => {
        connectTaskStream()
      }, 1500)
    }
  }, [handleTaskEvent])

  useEffect(() => {
    unmountedRef.current = false
    fetchTaskList(false)
    connectTaskStream()

    return () => {
      unmountedRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [fetchTaskList, connectTaskStream])

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTaskDetail(null)
      return
    }
    fetchTask(selectedTaskId)
  }, [selectedTaskId, fetchTask])

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (!includeArchived && task.archived) {
        return false
      }

      if (statusFilter !== 'all') {
        if (statusFilter === 'live' && !isLiveStatus(task.status)) {
          return false
        }
        if (statusFilter === 'done' && !isDoneStatus(task.status)) {
          return false
        }
        if (statusFilter !== 'live' && statusFilter !== 'done' && normalizeStatus(task.status) !== statusFilter) {
          return false
        }
      }

      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase()
        const name = displayName(task).toLowerCase()
        const id = String(task.task_id || '').toLowerCase()
        if (!name.includes(q) && !id.includes(q)) {
          return false
        }
      }

      const createdAt = new Date(task.created_at || '')
      if (dateFrom && !Number.isNaN(createdAt.getTime())) {
        const start = new Date(`${dateFrom}T00:00:00`)
        if (createdAt < start) {
          return false
        }
      }
      if (dateTo && !Number.isNaN(createdAt.getTime())) {
        const end = new Date(`${dateTo}T23:59:59.999`)
        if (createdAt > end) {
          return false
        }
      }

      return true
    })
  }, [tasks, includeArchived, statusFilter, searchQuery, dateFrom, dateTo])

  const runningTasks = useMemo(
    () => filteredTasks.filter((task) => isLiveStatus(task.status)),
    [filteredTasks],
  )

  const completedTasks = useMemo(
    () => filteredTasks.filter((task) => isDoneStatus(task.status)),
    [filteredTasks],
  )

  const historyTasks = useMemo(() => filteredTasks, [filteredTasks])

  const handleRefresh = async () => {
    setRefreshing(true)
    await Promise.all([
      fetchTaskList(true),
      selectedTaskId ? fetchTask(selectedTaskId) : Promise.resolve(),
    ])
    setRefreshing(false)
  }

  const handleArchiveToggle = async (taskId, archived) => {
    if (!taskId) return

    try {
      setArchivePendingTaskId(taskId)
      const response = await archiveTask(taskId, archived)
      const detail = response.data
      const summary = normalizeTaskSummary(detail)
      if (summary) {
        setTasks((prev) => upsertTask(prev, summary))
      }
      if (selectedTaskId === taskId) {
        setSelectedTaskDetail(detail)
      }
    } catch (error) {
      const message = error.response?.data?.detail || error.message || 'Archive update failed'
      setErrorMessage(message)
    } finally {
      setArchivePendingTaskId('')
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Activity className="w-5 h-5 text-blue-600" />
              Task Board
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              실시간 생성 상태, 완료 내역, 히스토리 검색/아카이브를 확인합니다.
            </p>
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        <div className="mt-4 flex gap-2 border-b border-gray-200">
          <button
            type="button"
            onClick={() => setActiveTab('live')}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'live'
                ? 'text-blue-600 border-blue-600'
                : 'text-gray-600 border-transparent hover:text-gray-900'
            }`}
          >
            <span className="inline-flex items-center gap-1.5">
              <Activity className="w-4 h-4" />
              Real-time
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('history')}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'history'
                ? 'text-blue-600 border-blue-600'
                : 'text-gray-600 border-transparent hover:text-gray-900'
            }`}
          >
            <span className="inline-flex items-center gap-1.5">
              <History className="w-4 h-4" />
              History
            </span>
          </button>
        </div>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
          <div className="xl:col-span-2">
            <label className="text-xs text-gray-500 block mb-1">Search</label>
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="server name or task id"
                className="w-full rounded-md border border-gray-300 pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All</option>
              <option value="live">Live</option>
              <option value="done">Done</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Date From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Date To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <label className="mt-3 inline-flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Show archived tasks
        </label>
      </div>

      {errorMessage && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm">
          {errorMessage}
        </div>
      )}

      {loading ? (
        <div className="bg-white rounded-lg border border-gray-200 p-12 flex items-center justify-center">
          <Loader2 className="w-6 h-6 text-blue-600 animate-spin" />
          <span className="ml-3 text-gray-600">Loading tasks...</span>
        </div>
      ) : activeTab === 'live' ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
              <div className="px-5 py-4 border-b border-gray-200">
                <h3 className="font-semibold text-gray-900">진행중 인스턴스</h3>
                <p className="text-xs text-gray-500 mt-1">{runningTasks.length} task(s)</p>
              </div>
              <div className="p-4 space-y-3 max-h-[640px] overflow-y-auto">
                {runningTasks.length === 0 ? (
                  <div className="text-sm text-gray-500">현재 진행중인 작업이 없습니다.</div>
                ) : (
                  runningTasks.map((task) => (
                    <TaskCard
                      key={task.task_id}
                      task={task}
                      selected={selectedTaskId === task.task_id}
                      onSelect={setSelectedTaskId}
                    />
                  ))
                )}
              </div>
            </div>

            <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
              <div className="px-5 py-4 border-b border-gray-200">
                <h3 className="font-semibold text-gray-900">완료된 인스턴스</h3>
                <p className="text-xs text-gray-500 mt-1">{completedTasks.length} task(s)</p>
              </div>
              <div className="p-4 space-y-3 max-h-[640px] overflow-y-auto">
                {completedTasks.length === 0 ? (
                  <div className="text-sm text-gray-500">완료된 작업이 없습니다.</div>
                ) : (
                  completedTasks.map((task) => (
                    <TaskCard
                      key={task.task_id}
                      task={task}
                      selected={selectedTaskId === task.task_id}
                      onSelect={setSelectedTaskId}
                    />
                  ))
                )}
              </div>
            </div>
          </div>

          <TaskDetailPanel
            taskDetail={selectedTaskDetail}
            onArchiveToggle={handleArchiveToggle}
            archivePending={archivePendingTaskId === selectedTaskDetail?.task_id}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-200">
              <h3 className="font-semibold text-gray-900">생성 히스토리</h3>
              <p className="text-xs text-gray-500 mt-1">{historyTasks.length} task(s)</p>
            </div>
            <div className="p-4 space-y-3 max-h-[760px] overflow-y-auto">
              {historyTasks.length === 0 ? (
                <div className="text-sm text-gray-500">히스토리가 없습니다.</div>
              ) : (
                historyTasks.map((task) => (
                  <TaskCard
                    key={task.task_id}
                    task={task}
                    selected={selectedTaskId === task.task_id}
                    onSelect={setSelectedTaskId}
                  />
                ))
              )}
            </div>
          </div>

          <div className="xl:col-span-2">
            <TaskDetailPanel
              taskDetail={selectedTaskDetail}
              onArchiveToggle={handleArchiveToggle}
              archivePending={archivePendingTaskId === selectedTaskDetail?.task_id}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default TaskBoard
