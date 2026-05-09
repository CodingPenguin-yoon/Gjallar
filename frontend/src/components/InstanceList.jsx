import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Server,
} from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { loadInfraExplorerModel } from '../utils/infraExplorerScreen'

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

function InstanceList({ onLogsUpdate = () => {}, onStatusChange = () => {} }) {
  const [model, setModel] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [expandedGroups, setExpandedGroups] = useState({})

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString()
    onLogsUpdate((prev) => [...prev, { timestamp, message, type }])
  }

  const fetchInfra = async () => {
    setRefreshing(true)
    setErrorMessage('')
    try {
      const nextModel = await loadInfraExplorerModel(apiV1Client)
      setModel(nextModel)
      setExpandedGroups(Object.fromEntries((nextModel.nodes || []).map((node) => [node.id, true])))
      onStatusChange('idle')
      addLog(`Loaded ${nextModel.summary.totalVms} VMs across ${nextModel.summary.totalNodes} nodes`, 'success')
    } catch (error) {
      const message = error?.message || 'Failed to load Infra Explorer data'
      setErrorMessage(message)
      setModel(null)
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

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-blue-50 p-3 text-blue-700">
            <Server className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-2xl font-semibold text-slate-950">Instances</h2>
            <p className="mt-1 text-sm text-slate-600">Manage/read-only infrastructure instances</p>
          </div>
        </div>
        <button
          type="button"
          onClick={fetchInfra}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {errorMessage && (
        <div className="border-b border-red-100 bg-red-50 px-6 py-4">
          <div className="flex items-start gap-3 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <div>{errorMessage}</div>
          </div>
        </div>
      )}

      <div className="px-6 py-5">
        {model?.summary ? (
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-medium uppercase text-slate-500">VMs</div>
              <div className="mt-1 text-xl font-semibold text-slate-950">{model.summary.runningVms} / {model.summary.totalVms}</div>
              <div className="text-xs text-slate-500">running / total</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-medium uppercase text-slate-500">Nodes</div>
              <div className="mt-1 text-xl font-semibold text-slate-950">{model.summary.totalNodes}</div>
              <div className="text-xs text-slate-500">observed nodes</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-medium uppercase text-slate-500">IP visibility</div>
              <div className="mt-1 text-xl font-semibold text-slate-950">{model.summary.visibleIpCount}</div>
              <div className="text-xs text-slate-500">VMs with IP evidence</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-medium uppercase text-slate-500">Guest agent</div>
              <div className="mt-1 text-xl font-semibold text-slate-950">{model.summary.guestAgentCount}</div>
              <div className="text-xs text-slate-500">with network evidence</div>
            </div>
          </div>
        ) : null}

        {nodes.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            No instances available.
          </div>
        ) : (
          <div className="space-y-4">
            {nodes.map((node) => {
              const isExpanded = expandedGroups[node.id] ?? true
              const nodeLabel = statusLabel(node.status)

              return (
                <section key={node.id} className="overflow-hidden rounded-xl border border-slate-200">
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
                        <div className="overflow-x-auto">
                          <table className="min-w-[72rem] w-full table-fixed divide-y divide-slate-200 text-sm">
                            <colgroup>
                              <col className="w-[18%] min-w-[12rem]" />
                              <col className="w-[8%] min-w-[6rem]" />
                              <col className="w-[17%] min-w-[12rem]" />
                              <col className="w-[6%] min-w-[4rem]" />
                              <col className="w-[7%] min-w-[5rem]" />
                              <col className="w-[31%] min-w-[24rem]" />
                              <col className="w-[13%] min-w-[9rem]" />
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
                                      <div className="truncate font-medium text-slate-950" title={vm.name}>{vm.name}</div>
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
                                      <SignalStack vm={vm} />
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
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

export default InstanceList
