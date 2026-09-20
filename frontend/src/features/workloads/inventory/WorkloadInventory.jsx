import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  Play,
  Power,
  Plus,
  RefreshCw,
  Server,
  Terminal,
} from 'lucide-react'
import { apiV1Client } from '../../../shared/api/apiV1'
import { authFailureMessage } from '../../../shared/auth/permissions'
import { insightFindingPath, normalizeVmid, vmDetailPath } from '../../../shared/navigation/targetPaths'
import { formatOperationTime, operationStatusTone } from '../../../entities/operation/model'
import {
  loadInfraExplorerModel,
  operationIdFromActionError,
  operationResultDestination,
} from './model'

function formatNumber(value, digits = 0) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return parsed.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function formatGb(value, digits = 1) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return '-'
  return `${formatNumber(parsed, digits)} GB`
}

function statusTone(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'online' || normalized === 'running') return 'bg-emerald-100 text-emerald-700'
  if (normalized === 'stopped' || normalized === 'offline') return 'bg-slate-100 text-slate-700'
  return 'bg-amber-100 text-amber-700'
}

function statusLabel(status) {
  const normalized = String(status || '').trim()
  if (!normalized) return 'Unknown'
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function formatObservedAt(value) {
  if (!value) return 'observed time unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function workloadOperationLabel(type) {
  const labels = {
    vm_create: 'Create VM',
    vm_start: 'VM Start',
    vm_shutdown: 'VM Shutdown',
    guided_qm_vm_unlock: 'Guided qm unlock',
  }
  return labels[type] || String(type || 'Operation').replaceAll('_', ' ')
}

function findingTone(severity) {
  if (severity === 'critical') return 'border-red-200 bg-red-50 text-red-700'
  if (severity === 'warning') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function insightsContextLabel(model) {
  const truncation = model.context.insightsTruncated
    ? `; truncated: ${model.context.truncatedInsightCategories.join(', ')}`
    : ''
  if (model.context.insightsStatus === 'loading') {
    return 'loading — inventory is already available'
  }
  if (model.context.insightsStatus === 'available') {
    return `${model.summary.relatedFindingCount} findings linked to listed workloads in the current response${truncation}`
  }
  if (model.context.insightsStatus === 'partial') {
    const limitations = [
      model.context.unavailableInsightCategories.length > 0
        ? `unavailable: ${model.context.unavailableInsightCategories.join(', ')}`
        : '',
      model.context.uncertainInsightCategories.length > 0
        ? `unknown/stale: ${model.context.uncertainInsightCategories.join(', ')}`
        : '',
    ].filter(Boolean).join('; ')
    return `partial — ${model.summary.relatedFindingCount} findings linked to listed workloads; ${limitations}${truncation}`
  }
  return 'unavailable — inventory remains usable'
}

function operationsContextLabel(model) {
  if (model.context.operationsStatus === 'loading') return 'loading — inventory is already available'
  if (model.context.operationsStatus === 'available') {
    return `${model.summary.workloadsWithRecentOperations} workloads linked within the latest ${model.context.operationWindow}`
  }
  return 'unavailable — inventory remains usable'
}

function canStartVm(vm = {}) {
  return Array.isArray(vm.allowedActions) && vm.allowedActions.includes('start')
}

function canShutdownVm(vm = {}) {
  return Array.isArray(vm.allowedActions) && vm.allowedActions.includes('shutdown')
}

function makeVmStartIdempotencyKey(vm = {}) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `infra-explorer:start:${vm.nodeId}:${vm.vmid ?? vm.id}:${random}`
}

function makeVmShutdownIdempotencyKey(vm = {}) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `infra-explorer:shutdown:${vm.nodeId}:${vm.vmid ?? vm.id}:${random}`
}

function diskBadges(disk = {}) {
  const badges = []
  if (disk.boot) badges.push('boot')
  if (disk.format && disk.format !== '-') badges.push(disk.format)
  if (disk.discard === 'on') badges.push('discard')
  if (String(disk.iothread) === '1') badges.push('iothread')
  if (String(disk.ssd) === '1') badges.push('ssd')
  if (String(disk.backup) === '0') badges.push('no backup')
  if (String(disk.readonly) === '1') badges.push('read-only')
  return badges
}

function DiskStack({ vm }) {
  const disks = Array.isArray(vm.disks) ? vm.disks : []
  if (disks.length === 0) {
    return <div className="truncate text-right">{formatGb(vm.diskGb)}</div>
  }

  return (
    <div className="space-y-1 text-left">
      {disks.map((disk, index) => {
        const device = disk.device || `disk-${index + 1}`
        const storage = disk.storageId && disk.storageId !== 'unknown' ? disk.storageId : ''
        const volume = disk.volume || disk.volumeId || ''
        const volumeLabel = storage && volume ? `${storage}: ${volume}` : storage || volume
        const badges = diskBadges(disk)

        return (
          <div key={`${device}-${index}`} className="min-w-0 rounded-md bg-slate-50 px-2 py-1 ring-1 ring-slate-100">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <span className="truncate font-medium text-slate-700" title={device}>{device}</span>
              <span className="shrink-0 font-mono text-xs text-slate-600">{formatGb(disk.sizeGb)}</span>
            </div>
            {volumeLabel ? (
              <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500" title={volumeLabel}>
                {volumeLabel}
              </div>
            ) : null}
            {badges.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {badges.map((badge) => (
                  <span key={`${device}-${badge}`} className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                    {badge}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
      {disks.length > 1 ? (
        <div className="border-t border-slate-200 pt-1 text-right text-xs font-semibold text-slate-700">
          Total {formatGb(vm.diskGb)}
        </div>
      ) : null}
    </div>
  )
}

function IpStack({ vm }) {
  const [expanded, setExpanded] = useState(false)
  const primaryIp = vm.primaryIp && vm.primaryIp !== '-' ? vm.primaryIp : ''
  const hiddenIps = Array.isArray(vm.hiddenIpAddresses) ? vm.hiddenIpAddresses : []
  const hiddenIpCount = hiddenIps.length || Number(vm.hiddenIpCount || 0)

  const extraIpButton = hiddenIpCount > 0 ? (
    <button
      type="button"
      onClick={() => setExpanded((current) => !current)}
      aria-expanded={expanded}
      aria-label={`${expanded ? 'Hide' : 'Show'} ${hiddenIpCount} additional IP addresses`}
      className="shrink-0 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 hover:border-slate-300 hover:bg-white"
    >
      +{hiddenIpCount}
    </button>
  ) : null

  const extraIpList = expanded && hiddenIps.length > 0 ? (
    <div className="mt-1 flex flex-wrap gap-1">
      {hiddenIps.map((ip) => (
        <span key={ip} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
          {ip}
        </span>
      ))}
    </div>
  ) : null

  if (!primaryIp) {
    return (
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-slate-500">
            {hiddenIpCount > 0 ? 'No vmbr IP visible' : 'No guest IP visible'}
          </span>
          {extraIpButton}
        </div>
        {extraIpList}
      </div>
    )
  }

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="truncate font-mono text-xs text-slate-700" title={primaryIp}>{primaryIp}</span>
        {extraIpButton}
      </div>
      {extraIpList}
    </div>
  )
}

function SignalStack({ vm }) {
  const signals = []
  if (vm.guestAgent?.available) {
    signals.push({ label: 'Guest agent', tone: 'bg-emerald-50 text-emerald-700 border-emerald-200' })
  } else if (vm.status === 'running') {
    signals.push({ label: 'No guest agent IP', tone: 'bg-amber-50 text-amber-700 border-amber-200' })
  }
  if (vm.storageId && vm.storageId !== 'unknown') {
    signals.push({ label: vm.storageId, tone: 'bg-slate-50 text-slate-600 border-slate-200' })
  }

  if (signals.length === 0) {
    return <span className="text-xs text-slate-400">-</span>
  }

  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      {signals.map((signal) => (
        <span key={signal.label} className={`inline-flex max-w-full rounded border px-1.5 py-0.5 text-[11px] font-medium ${signal.tone}`}>
          <span className="truncate">{signal.label}</span>
        </span>
      ))}
    </div>
  )
}

function WorkloadContextStack({ vm, navigate }) {
  const findings = Array.isArray(vm.relatedFindings) ? vm.relatedFindings : []
  const primaryFinding = findings[0]
  const recentOperation = vm.recentOperation

  return (
    <div className="flex min-w-0 flex-col items-start gap-1.5">
      <SignalStack vm={vm} />
      {primaryFinding ? (
        <button
          type="button"
          onClick={() => navigate(insightFindingPath(primaryFinding))}
          title={`${primaryFinding.message} · ${primaryFinding.source} · ${primaryFinding.freshness} · ${formatObservedAt(primaryFinding.observedAt)}`}
          className={`inline-flex max-w-full rounded border px-1.5 py-0.5 text-left text-[11px] font-medium ${findingTone(primaryFinding.severity)}`}
        >
          <span className="truncate">{findings.length} finding{findings.length === 1 ? '' : 's'} · {primaryFinding.code}</span>
        </button>
      ) : null}
      {recentOperation ? (
        <button
          type="button"
          onClick={() => navigate(`/operations/${encodeURIComponent(recentOperation.id)}`)}
          title={`${workloadOperationLabel(recentOperation.type)} · ${recentOperation.status} · updated ${formatOperationTime(recentOperation.updatedAt || recentOperation.createdAt)}`}
          className={`inline-flex max-w-full flex-col items-start rounded border px-1.5 py-0.5 text-left text-[11px] font-medium ${operationStatusTone(recentOperation.status)}`}
        >
          <span className="truncate">{workloadOperationLabel(recentOperation.type)} · {recentOperation.status}</span>
          <span className="max-w-full truncate text-[10px] font-normal opacity-80">updated {formatOperationTime(recentOperation.updatedAt || recentOperation.createdAt)}</span>
        </button>
      ) : null}
    </div>
  )
}

function VmActionButtons({ vm, canMutateVms, openStartDialog, openShutdownDialog, navigate }) {
  if (!canMutateVms) return null

  return (
    <div className="flex items-center gap-1.5">
      {canStartVm(vm) ? (
        <button
          type="button"
          onClick={() => openStartDialog(vm)}
          aria-label={`Start ${vm.name}`}
          title={`Start ${vm.name}`}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2"
        >
          <Play className="h-4 w-4" />
        </button>
      ) : null}
      {canShutdownVm(vm) ? (
        <button
          type="button"
          onClick={() => openShutdownDialog(vm)}
          aria-label={`Gracefully shut down ${vm.name}`}
          title={`Gracefully shut down ${vm.name}`}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2"
        >
          <Power className="h-4 w-4" />
        </button>
      ) : null}
      <button
        type="button"
        onClick={() => navigate(`/operations/guided-qm/vm-unlock?node_id=${encodeURIComponent(vm.nodeId)}&vmid=${encodeURIComponent(vm.vmid)}`)}
        aria-label={`Plan qm unlock for ${vm.name}`}
        title={`Plan qm unlock for ${vm.name}`}
        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:border-blue-300 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
      >
        <Terminal className="h-4 w-4" />
      </button>
    </div>
  )
}

function WorkloadInventory({
  onLogsUpdate = () => {},
  onStatusChange = () => {},
  currentUser = null,
  canMutateVms = true,
}) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedVmid = normalizeVmid(searchParams.get('vmid'))
  const requestedAction = String(searchParams.get('action') || '').trim().toLowerCase()
  const handledActionRequest = useRef('')
  const [model, setModel] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [expandedGroups, setExpandedGroups] = useState({})
  const [pendingStartVm, setPendingStartVm] = useState(null)
  const [startAcknowledged, setStartAcknowledged] = useState(false)
  const [startSubmitting, setStartSubmitting] = useState(false)
  const [startError, setStartError] = useState('')
  const [pendingShutdownVm, setPendingShutdownVm] = useState(null)
  const [shutdownAcknowledged, setShutdownAcknowledged] = useState(false)
  const [shutdownSubmitting, setShutdownSubmitting] = useState(false)
  const [shutdownError, setShutdownError] = useState('')
  const [actionNotice, setActionNotice] = useState(null)

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString()
    onLogsUpdate((prev) => [...prev, { timestamp, message, type }])
  }

  const fetchInfra = async () => {
    let inventoryPresented = false
    setRefreshing(true)
    setErrorMessage('')
    try {
      const presentInventory = (nextModel) => {
        inventoryPresented = true
        setModel(nextModel)
        setExpandedGroups(Object.fromEntries((nextModel.nodes || []).map((node) => [node.id, true])))
        onStatusChange('idle')
        setLoading(false)
        addLog(`Loaded ${nextModel.summary.totalVms} VMs across ${nextModel.summary.totalNodes} nodes; related context is loading`, 'success')
      }
      const nextModel = await loadInfraExplorerModel(apiV1Client, { onInventoryLoaded: presentInventory })
      setModel(nextModel)
      setExpandedGroups(Object.fromEntries((nextModel.nodes || []).map((node) => [node.id, true])))
      onStatusChange('idle')
      if (!inventoryPresented) {
        addLog(`Loaded ${nextModel.summary.totalVms} VMs across ${nextModel.summary.totalNodes} nodes`, 'success')
      }
    } catch (error) {
      const message = error?.message || 'Failed to load Infra Explorer data'
      setErrorMessage(message)
      onStatusChange('error')
      addLog(`Infra Explorer load failed: ${message}`, 'error')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchInfra()
  }, [])

  useEffect(() => {
    if (!model || !requestedVmid || !['start', 'shutdown'].includes(requestedAction)) return
    const requestKey = `${requestedVmid}:${requestedAction}`
    if (handledActionRequest.current === requestKey) return
    handledActionRequest.current = requestKey

    const requestedVm = model.nodes
      .flatMap((node) => node.vms)
      .find((vm) => normalizeVmid(vm.vmid) === requestedVmid)
    if (!requestedVm) {
      setActionNotice({ message: `VMID ${requestedVmid}를 현재 Workloads 관찰 결과에서 찾지 못했습니다.`, operationId: '' })
      return
    }
    if (!canMutateVms) {
      setActionNotice({ message: `${requestedVm.name} 작업에는 operator 또는 admin 권한과 live 연결이 필요합니다.`, operationId: '' })
      return
    }
    if (requestedAction === 'start' && canStartVm(requestedVm)) {
      setPendingStartVm({ ...requestedVm, startIdempotencyKey: makeVmStartIdempotencyKey(requestedVm) })
      setStartAcknowledged(false)
      setStartError('')
      setActionNotice(null)
      return
    }
    if (requestedAction === 'shutdown' && canShutdownVm(requestedVm)) {
      setPendingShutdownVm({ ...requestedVm, shutdownIdempotencyKey: makeVmShutdownIdempotencyKey(requestedVm) })
      setShutdownAcknowledged(false)
      setShutdownError('')
      setActionNotice(null)
      return
    }
    setActionNotice({
      message: `${requestedVm.name}의 현재 상태 ${requestedVm.status}에서는 ${requestedAction} 작업을 시작할 수 없습니다.`,
      operationId: '',
    })
  }, [canMutateVms, model, requestedAction, requestedVmid])

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-slate-200 bg-white">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-blue-600" />
        <span className="text-sm text-slate-600">Loading Infra Explorer...</span>
      </div>
    )
  }

  const nodes = model?.nodes || []

  const toggleGroup = (nodeId) => {
    setExpandedGroups((current) => ({
      ...current,
      [nodeId]: !current[nodeId],
    }))
  }

  const openStartDialog = (vm) => {
    if (!canMutateVms) {
      setStartError('operator 또는 admin 권한이 필요합니다.')
      return
    }
    setPendingStartVm({ ...vm, startIdempotencyKey: makeVmStartIdempotencyKey(vm) })
    setStartAcknowledged(false)
    setStartError('')
    setActionNotice(null)
  }

  const closeStartDialog = () => {
    if (startSubmitting) return
    setPendingStartVm(null)
    setStartAcknowledged(false)
    setStartError('')
  }

  const confirmStartVm = async () => {
    if (!pendingStartVm || !startAcknowledged || startSubmitting) return
    setStartSubmitting(true)
    setStartError('')
    try {
      const result = await apiV1Client.startVm(pendingStartVm.nodeId, pendingStartVm.vmid, {
        vm_start_acknowledged: true,
        idempotency_key: pendingStartVm.startIdempotencyKey,
        expected_name: pendingStartVm.name,
        expected_status: pendingStartVm.status,
      })
      addLog(`VM start submitted for ${pendingStartVm.name}`, 'success')
      setPendingStartVm(null)
      setStartAcknowledged(false)
      if (result?.job_id) {
        const destination = await operationResultDestination(apiV1Client, result.job_id)
        if (destination.compatibilityFallback) {
          addLog(`Common Operation detail is unavailable for ${result.job_id}; opened the compatibility Job view.`, 'warning')
        }
        if (destination.lookupError) {
          const lookupMessage = authFailureMessage(destination.lookupError, 'Operation detail lookup failed')
          setActionNotice({
            message: `VM start was submitted, but its common Operation detail could not be loaded: ${lookupMessage}`,
            operationId: result.job_id,
          })
          addLog(`VM start submitted but Operation lookup failed for ${result.job_id}: ${lookupMessage}`, 'warning')
          void fetchInfra()
        } else {
          navigate(destination.path)
        }
      } else {
        await fetchInfra()
      }
    } catch (error) {
      const message = authFailureMessage(error, 'Failed to start VM')
      const operationId = operationIdFromActionError(error)
      if (operationId) {
        const destination = await operationResultDestination(apiV1Client, operationId)
        if (!destination.lookupError) {
          addLog(`VM start did not return success; opened recorded outcome ${operationId}.`, 'warning')
          navigate(destination.path)
          return
        }
        const lookupMessage = authFailureMessage(destination.lookupError, 'Operation detail lookup failed')
        setStartError(`${message}. Recorded Operation ${operationId} could not be loaded: ${lookupMessage}`)
        setActionNotice({
          message: `VM start outcome was recorded, but Operation ${operationId} could not be loaded: ${lookupMessage}`,
          operationId,
        })
        addLog(`VM start failed and Operation lookup failed for ${operationId}: ${lookupMessage}`, 'error')
        return
      }
      setStartError(message)
      addLog(`VM start failed for ${pendingStartVm.name}: ${message}`, 'error')
    } finally {
      setStartSubmitting(false)
    }
  }

  const openShutdownDialog = (vm) => {
    if (!canMutateVms) {
      setShutdownError('operator 또는 admin 권한이 필요합니다.')
      return
    }
    setPendingShutdownVm({ ...vm, shutdownIdempotencyKey: makeVmShutdownIdempotencyKey(vm) })
    setShutdownAcknowledged(false)
    setShutdownError('')
    setActionNotice(null)
  }

  const closeShutdownDialog = () => {
    if (shutdownSubmitting) return
    setPendingShutdownVm(null)
    setShutdownAcknowledged(false)
    setShutdownError('')
  }

  const confirmShutdownVm = async () => {
    if (!pendingShutdownVm || !shutdownAcknowledged || shutdownSubmitting) return
    setShutdownSubmitting(true)
    setShutdownError('')
    try {
      const result = await apiV1Client.shutdownVm(pendingShutdownVm.nodeId, pendingShutdownVm.vmid, {
        vm_shutdown_acknowledged: true,
        idempotency_key: pendingShutdownVm.shutdownIdempotencyKey,
        expected_name: pendingShutdownVm.name,
        expected_status: pendingShutdownVm.status,
      })
      addLog(`VM shutdown submitted for ${pendingShutdownVm.name}`, 'success')
      setPendingShutdownVm(null)
      setShutdownAcknowledged(false)
      if (result?.job_id) {
        const destination = await operationResultDestination(apiV1Client, result.job_id)
        if (destination.compatibilityFallback) {
          addLog(`Common Operation detail is unavailable for ${result.job_id}; opened the compatibility Job view.`, 'warning')
        }
        if (destination.lookupError) {
          const lookupMessage = authFailureMessage(destination.lookupError, 'Operation detail lookup failed')
          setActionNotice({
            message: `VM shutdown was submitted, but its common Operation detail could not be loaded: ${lookupMessage}`,
            operationId: result.job_id,
          })
          addLog(`VM shutdown submitted but Operation lookup failed for ${result.job_id}: ${lookupMessage}`, 'warning')
          void fetchInfra()
        } else {
          navigate(destination.path)
        }
      } else {
        await fetchInfra()
      }
    } catch (error) {
      const message = authFailureMessage(error, 'Failed to shut down VM')
      const operationId = operationIdFromActionError(error)
      if (operationId) {
        const destination = await operationResultDestination(apiV1Client, operationId)
        if (!destination.lookupError) {
          addLog(`VM shutdown did not return success; opened recorded outcome ${operationId}.`, 'warning')
          navigate(destination.path)
          return
        }
        const lookupMessage = authFailureMessage(destination.lookupError, 'Operation detail lookup failed')
        setShutdownError(`${message}. Recorded Operation ${operationId} could not be loaded: ${lookupMessage}`)
        setActionNotice({
          message: `VM shutdown outcome was recorded, but Operation ${operationId} could not be loaded: ${lookupMessage}`,
          operationId,
        })
        addLog(`VM shutdown failed and Operation lookup failed for ${operationId}: ${lookupMessage}`, 'error')
        return
      }
      setShutdownError(message)
      addLog(`VM shutdown failed for ${pendingShutdownVm.name}: ${message}`, 'error')
    } finally {
      setShutdownSubmitting(false)
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Server className="h-4 w-4" />
            VM INVENTORY
          </div>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">가상머신</h2>
          <p className="mt-1 text-sm text-slate-600">VM 상태와 자원을 확인하고, 대상을 선택해 필요한 작업을 시작하세요.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => navigate('/instances/create')}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
          >
            <Plus className="h-4 w-4" />
            VM 생성
          </button>
          <button
            type="button"
            onClick={fetchInfra}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            새로고침
          </button>
        </div>
      </div>

      {model && <details className="rounded-xl border border-slate-200 bg-white p-4" open={model.context.insightsStatus !== 'available' || model.context.insightsTruncated || model.context.operationsStatus !== 'available' || model.observations.some(item => item.freshness !== 'fresh')}>
        <summary className="cursor-pointer text-sm font-medium text-slate-600">관찰 근거 · {model.observations.length ? formatObservedAt(model.observations[0].observedAt) : '시각 확인 불가'} · 자세히 보기</summary>
        <div className="mt-3 space-y-3">
      {model?.observations?.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {model.observations.map((observation) => (
            <div key={observation.scope} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600 shadow-sm">
              <div className="font-semibold uppercase tracking-wide text-slate-500">{observation.scope} observation</div>
              <div className="mt-1 font-medium text-slate-800">{observation.source} · {observation.freshness}</div>
              <div className="mt-0.5">{formatObservedAt(observation.observedAt)}</div>
            </div>
          ))}
        </div>
      ) : null}

      {model?.context ? (
        <div className={`rounded-lg border px-4 py-3 text-sm shadow-sm ${model.context.insightsStatus === 'available' && !model.context.insightsTruncated && model.context.operationsStatus === 'available' ? 'border-slate-200 bg-white text-slate-600' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
          <div className="flex flex-wrap gap-x-5 gap-y-1">
            <span>Insights: {insightsContextLabel(model)}</span>
            <span>Operations: {operationsContextLabel(model)}</span>
          </div>
        </div>
      ) : null}

        </div>
      </details>}

      {errorMessage && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 shadow-sm">
          <div className="flex items-start gap-3 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <div className="flex-1">
              <div>{model ? `Refresh failed. Previous observation remains visible. ${errorMessage}` : errorMessage}</div>
              {!model ? (
                <button type="button" onClick={fetchInfra} className="mt-2 rounded-md border border-red-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-red-800 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500">
                  Retry inventory
                </button>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {actionNotice ? (
        <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 shadow-sm">
          <div className="flex items-start gap-3 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <div>
              <div>{actionNotice.message}</div>
              {actionNotice.operationId ? (
                <button
                  type="button"
                  onClick={() => navigate(`/operations/${encodeURIComponent(actionNotice.operationId)}`)}
                  className="mt-2 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100"
                >
                  Retry Operation detail · {actionNotice.operationId}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {!canMutateVms ? (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800 shadow-sm">
          VM lifecycle actions require operator or admin role and a complete live Proxmox observation. Current role: {currentUser?.role || 'unknown'}.
        </div>
      ) : null}

      {pendingShutdownVm ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 shadow-sm">
          <div className="max-w-3xl rounded-lg border border-amber-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-slate-950">Graceful Shutdown</h3>
                <div className="mt-2 grid gap-2 text-sm text-slate-600 sm:grid-cols-2">
                  <div className="min-w-0">
                    <div className="text-xs font-medium uppercase text-slate-500">Name</div>
                    <div className="truncate font-medium text-slate-900" title={pendingShutdownVm.name}>{pendingShutdownVm.name}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase text-slate-500">Node</div>
                    <div className="font-mono text-slate-900">{pendingShutdownVm.nodeId}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase text-slate-500">VMID</div>
                    <div className="font-mono text-slate-900">{pendingShutdownVm.vmid ?? '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase text-slate-500">Current status</div>
                    <div className="text-slate-900">{statusLabel(pendingShutdownVm.status)}</div>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={closeShutdownDialog}
                disabled={shutdownSubmitting}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
            </div>
            {shutdownError ? (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {shutdownError}
              </div>
            ) : null}
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              This requests a guest-aware shutdown. Gjallar will not force-stop or reboot the VM if shutdown is ambiguous.
            </div>
            <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={shutdownAcknowledged}
                onChange={(event) => setShutdownAcknowledged(event.target.checked)}
                disabled={shutdownSubmitting}
                data-testid="vm-shutdown-acknowledgement"
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-amber-600 focus:ring-amber-500"
              />
              <span>I acknowledge this will gracefully shut down the running VM on Proxmox.</span>
            </label>
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                data-testid="confirm-vm-shutdown"
                onClick={confirmShutdownVm}
                disabled={!shutdownAcknowledged || shutdownSubmitting}
                className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {shutdownSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
                Graceful Shutdown
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {pendingStartVm ? (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 shadow-sm">
          <div className="max-w-3xl rounded-lg border border-blue-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-slate-950">Start VM</h3>
                <div className="mt-2 grid gap-2 text-sm text-slate-600 sm:grid-cols-2">
                  <div className="min-w-0">
                    <div className="text-xs font-medium uppercase text-slate-500">Name</div>
                    <div className="truncate font-medium text-slate-900" title={pendingStartVm.name}>{pendingStartVm.name}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase text-slate-500">Node</div>
                    <div className="font-mono text-slate-900">{pendingStartVm.nodeId}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase text-slate-500">VMID</div>
                    <div className="font-mono text-slate-900">{pendingStartVm.vmid ?? '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase text-slate-500">Current status</div>
                    <div className="text-slate-900">{statusLabel(pendingStartVm.status)}</div>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={closeStartDialog}
                disabled={startSubmitting}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
            </div>
            {startError ? (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {startError}
              </div>
            ) : null}
            <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={startAcknowledged}
                onChange={(event) => setStartAcknowledged(event.target.checked)}
                disabled={startSubmitting}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              <span>I acknowledge this will start the stopped VM on Proxmox.</span>
            </label>
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                data-testid="confirm-vm-start"
                onClick={confirmStartVm}
                disabled={!startAcknowledged || startSubmitting}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {startSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Start VM
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="space-y-3">
        {model?.summary ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="gj-stat">
              <div className="text-xs font-medium uppercase text-slate-500">VMs</div>
              <div className="mt-2 text-xl font-semibold text-slate-950">{model.summary.runningVms} / {model.summary.totalVms}</div>
              <div className="mt-1 text-xs text-slate-500">running / total</div>
            </div>
            <div className="gj-stat">
              <div className="text-xs font-medium uppercase text-slate-500">Nodes</div>
              <div className="mt-2 text-xl font-semibold text-slate-950">{model.summary.totalNodes}</div>
              <div className="mt-1 text-xs text-slate-500">observed nodes</div>
            </div>
            <div className="gj-stat">
              <div className="text-xs font-medium uppercase text-slate-500">IP visibility</div>
              <div className="mt-2 text-xl font-semibold text-slate-950">{model.summary.visibleIpCount}</div>
              <div className="mt-1 text-xs text-slate-500">VMs with IP evidence</div>
            </div>
            <div className="gj-stat">
              <div className="text-xs font-medium uppercase text-slate-500">Guest agent</div>
              <div className="mt-2 text-xl font-semibold text-slate-950">{model.summary.guestAgentCount}</div>
              <div className="mt-1 text-xs text-slate-500">with network evidence</div>
            </div>
          </div>
        ) : null}

        {!model && errorMessage ? null : nodes.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            No instances available.
          </div>
        ) : (
          <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            {nodes.map((node) => {
              const isExpanded = expandedGroups[node.id] ?? true
              const nodeLabel = statusLabel(node.status)

              return (
                <section key={node.id} className="overflow-hidden rounded-lg border border-slate-200">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3">
                    <button
                      type="button"
                      onClick={() => toggleGroup(node.id)}
                      aria-expanded={isExpanded}
                      aria-controls={`instance-group-${node.id}`}
                      aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${node.name}`}
                      className="inline-flex min-w-0 items-center gap-3 text-left text-slate-900"
                    >
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4 flex-none text-slate-500" />
                      ) : (
                        <ChevronRight className="h-4 w-4 flex-none text-slate-500" />
                      )}
                      <div className="min-w-0">
                        <div className="truncate font-semibold">{node.name}</div>
                        <div className="mt-0.5 text-xs text-slate-500">{node.vms.length} instances</div>
                      </div>
                    </button>
                    <span className={`rounded-full px-2 py-1 text-xs font-medium ${statusTone(node.status)}`}>
                      {nodeLabel}
                    </span>
                  </div>

                  {isExpanded && (
                    <div id={`instance-group-${node.id}`}>
                      {node.vms.length === 0 ? (
                        <div className="px-4 py-4 text-sm text-slate-500">No instances observed on this server.</div>
                      ) : (
                        <>
                          <div className="divide-y divide-slate-100 lg:hidden">
                            {node.vms.map((vm) => (
                              <article key={`mobile-${vm.nodeId}:${vm.vmid ?? vm.id}`} className="space-y-3 p-4">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <Link to={vmDetailPath(vm.vmid) || '/instances'} className="block truncate font-semibold text-blue-800 hover:text-blue-950 hover:underline" title={`Open exact VM ${vm.name}`}>{vm.name}</Link>
                                    <div className="mt-0.5 text-xs text-slate-500">VMID {vm.vmid ?? '-'}</div>
                                  </div>
                                  <span className={`inline-flex shrink-0 rounded-full px-2 py-1 text-xs font-medium ${statusTone(vm.status)}`}>
                                    {statusLabel(vm.status)}
                                  </span>
                                </div>
                                <div className="grid grid-cols-3 gap-3 rounded-lg bg-slate-50 p-3 text-sm">
                                  <div className="min-w-0">
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">IP</div>
                                    <div className="mt-1"><IpStack vm={vm} /></div>
                                  </div>
                                  <div>
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">CPU</div>
                                    <div className="mt-1 font-medium text-slate-800">{formatNumber(vm.cpuCores)}</div>
                                  </div>
                                  <div>
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Memory</div>
                                    <div className="mt-1 font-medium text-slate-800">{formatGb(vm.memoryGb)}</div>
                                  </div>
                                </div>
                                <div className="flex flex-wrap items-end justify-between gap-3">
                                  <WorkloadContextStack vm={vm} navigate={navigate} />
                                  <VmActionButtons
                                    vm={vm}
                                    canMutateVms={canMutateVms}
                                    openStartDialog={openStartDialog}
                                    openShutdownDialog={openShutdownDialog}
                                    navigate={navigate}
                                  />
                                </div>
                                <details className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                                  <summary className="cursor-pointer font-medium text-slate-700">Disk details · {formatGb(vm.diskGb)}</summary>
                                  <div className="mt-2"><DiskStack vm={vm} /></div>
                                </details>
                              </article>
                            ))}
                          </div>
                          <div className="hidden overflow-x-auto lg:block">
                          <table className="min-w-[73rem] w-full table-fixed divide-y divide-slate-200 text-sm">
                            <colgroup>
                              <col className="w-[14%] min-w-[12rem]" />
                              <col className="w-[10%] min-w-[6rem]" />
                              <col className="w-[14%] min-w-[10rem]" />
                              <col className="w-[5%] min-w-[4rem]" />
                              <col className="w-[9%] min-w-[5rem]" />
                              <col className="w-[22%] min-w-[21rem]" />
                              <col className="w-[12%] min-w-[8rem]" />
                              <col className="w-[14%] min-w-[7rem]" />
                            </colgroup>
                            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                              <tr>
                                <th scope="col" className="px-4 py-2 text-left font-medium">Name</th>
                                <th scope="col" className="px-4 py-2 text-left font-medium">Status</th>
                                <th scope="col" className="px-4 py-2 text-left font-medium">IP</th>
                                <th scope="col" className="px-4 py-2 text-right font-medium">CPU</th>
                                <th scope="col" className="px-4 py-2 text-right font-medium">Memory</th>
                                <th scope="col" className="px-4 py-2 text-left font-medium">Disk</th>
                                <th scope="col" className="px-4 py-2 text-left font-medium">Signals</th>
                                <th scope="col" className="px-4 py-2 text-center font-medium">Actions</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 bg-white">
                              {node.vms.map((vm) => {
                                const vmIpLabel = vm.primaryIp === '-'
                                  ? `${vm.hiddenIpCount > 0 ? 'No vmbr IP visible' : 'No guest IP visible'}${vm.hiddenIpCount > 0 ? ` +${vm.hiddenIpCount}` : ''}`
                                  : `${vm.primaryIp}${vm.hiddenIpCount > 0 ? ` +${vm.hiddenIpCount}` : ''}`
                                const cpuLabel = formatNumber(vm.cpuCores)
                                const memoryLabel = formatGb(vm.memoryGb)
                                const diskLabel = vm.disks.length > 0
                                  ? vm.disks.map((disk) => `${disk.device} ${formatGb(disk.sizeGb)} ${disk.storageId}`).join(', ')
                                  : formatGb(vm.diskGb)

                                return (
                                  <tr key={`${vm.nodeId}:${vm.vmid ?? vm.id}`} className="align-top">
                                    <td className="px-4 py-2">
                                      <Link to={vmDetailPath(vm.vmid) || '/instances'} className="block text-blue-800 hover:text-blue-950 hover:underline" aria-label={`Open exact VM ${vm.name}`}>
                                        <div className="truncate font-medium text-slate-950" title={vm.name}>{vm.name}</div>
                                      </Link>
                                      <div className="mt-0.5 text-xs text-slate-500">VMID {vm.vmid ?? '-'}</div>
                                      {vm.tags.length > 0 ? (
                                        <div className="mt-1 flex flex-wrap gap-1">
                                          {vm.tags.slice(0, 4).map((tag) => (
                                            <span key={tag} className="rounded border border-blue-100 bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700">
                                              {tag}
                                            </span>
                                          ))}
                                          {vm.tags.length > 4 ? (
                                            <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600">
                                              +{vm.tags.length - 4}
                                            </span>
                                          ) : null}
                                        </div>
                                      ) : null}
                                    </td>
                                    <td className="px-4 py-2 whitespace-nowrap">
                                      <span className={`inline-flex max-w-full rounded-full px-2 py-1 text-xs font-medium ${statusTone(vm.status)}`} title={statusLabel(vm.status)}>
                                        <span className="block truncate">{statusLabel(vm.status)}</span>
                                      </span>
                                    </td>
                                    <td className="px-4 py-2 text-slate-600" title={vmIpLabel}>
                                      <IpStack vm={vm} />
                                    </td>
                                    <td className="px-4 py-2 text-right text-slate-600" title={cpuLabel}>
                                      <div className="truncate">{cpuLabel}</div>
                                    </td>
                                    <td className="px-4 py-2 text-right text-slate-600" title={memoryLabel}>
                                      <div className="truncate">{memoryLabel}</div>
                                    </td>
                                    <td className="px-4 py-2 text-slate-600" title={diskLabel}>
                                      <DiskStack vm={vm} />
                                    </td>
                                    <td className="px-4 py-2 text-slate-600">
                                      <WorkloadContextStack vm={vm} navigate={navigate} />
                                    </td>
                                    <td className="px-4 py-2 text-center">
                                      <div className="flex items-center justify-center gap-1.5">
                                        {canMutateVms && canStartVm(vm) ? (
                                          <button
                                            type="button"
                                            onClick={() => openStartDialog(vm)}
                                            aria-label={`Start ${vm.name}`}
                                            title={`Start ${vm.name}`}
                                            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2"
                                          >
                                            <Play className="h-4 w-4" />
                                          </button>
                                        ) : null}
                                        {canMutateVms && canShutdownVm(vm) ? (
                                          <button
                                            type="button"
                                            onClick={() => openShutdownDialog(vm)}
                                            aria-label={`Gracefully shut down ${vm.name}`}
                                            title={`Gracefully shut down ${vm.name}`}
                                            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2"
                                          >
                                            <Power className="h-4 w-4" />
                                          </button>
                                        ) : null}
                                        {canMutateVms ? (
                                          <button
                                            type="button"
                                            onClick={() => navigate(`/operations/guided-qm/vm-unlock?node_id=${encodeURIComponent(vm.nodeId)}&vmid=${encodeURIComponent(vm.vmid)}`)}
                                            aria-label={`Plan qm unlock for ${vm.name}`}
                                            title={`Plan qm unlock for ${vm.name}`}
                                            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:border-blue-300 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                                          >
                                            <Terminal className="h-4 w-4" />
                                          </button>
                                        ) : null}
                                      </div>
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </section>
              )
            })}
          </div>
        )}
      </div>

    </section>
  )
}

export default WorkloadInventory
