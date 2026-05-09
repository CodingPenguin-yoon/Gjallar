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
                          <table className="min-w-[56rem] w-full table-fixed divide-y divide-slate-200 text-sm">
                            <colgroup>
                              <col className="w-[28%] min-w-[14rem]" />
                              <col className="w-[12%] min-w-[8rem]" />
                              <col className="w-[24%] min-w-[12rem]" />
                              <col className="w-[8%] min-w-[4.5rem]" />
                              <col className="w-[10%] min-w-[6rem]" />
                              <col className="w-[10%] min-w-[6rem]" />
                              <col className="w-[8%] min-w-[5rem]" />
                            </colgroup>
                            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                              <tr>
                                <th scope="col" className="px-4 py-2 text-left font-medium">Name</th>
                                <th scope="col" className="px-4 py-2 text-left font-medium">Status</th>
                                <th scope="col" className="px-4 py-2 text-left font-medium">IP</th>
                                <th scope="col" className="px-4 py-2 text-right font-medium">CPU</th>
                                <th scope="col" className="px-4 py-2 text-right font-medium">Memory</th>
                                <th scope="col" className="px-4 py-2 text-right font-medium">Disk</th>
                                <th scope="col" className="px-4 py-2 text-center font-medium">Template</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 bg-white">
                              {node.vms.map((vm) => {
                                const vmIpLabel = vm.primaryIp === '-' ? 'No guest IP visible' : vm.primaryIp
                                const cpuLabel = formatNumber(vm.cpuCores)
                                const memoryLabel = `${formatNumber(vm.memoryGb, 1)} GB`
                                const diskLabel = `${formatNumber(vm.diskGb, 1)} GB`
                                const templateLabel = vm.template ? 'Yes' : 'No'

                                return (
                                  <tr key={`${vm.nodeId}:${vm.vmid ?? vm.id}`} className="align-top">
                                    <td className="px-4 py-2">
                                      <div className="truncate font-medium text-slate-950" title={vm.name}>{vm.name}</div>
                                      <div className="mt-0.5 text-xs text-slate-500">VMID {vm.vmid ?? '-'}</div>
                                    </td>
                                    <td className="px-4 py-2 whitespace-nowrap">
                                      <span className={`inline-flex max-w-full rounded-full px-2 py-1 text-xs font-medium ${statusTone(vm.status)}`} title={statusLabel(vm.status)}>
                                        <span className="block truncate">{statusLabel(vm.status)}</span>
                                      </span>
                                    </td>
                                    <td className="px-4 py-2 text-slate-600" title={vmIpLabel}>
                                      <div className="truncate">{vmIpLabel}</div>
                                    </td>
                                    <td className="px-4 py-2 text-right text-slate-600" title={cpuLabel}>
                                      <div className="truncate">{cpuLabel}</div>
                                    </td>
                                    <td className="px-4 py-2 text-right text-slate-600" title={memoryLabel}>
                                      <div className="truncate">{memoryLabel}</div>
                                    </td>
                                    <td className="px-4 py-2 text-right text-slate-600" title={diskLabel}>
                                      <div className="truncate">{diskLabel}</div>
                                    </td>
                                    <td className="px-4 py-2 text-center text-slate-600" title={templateLabel}>
                                      <div className="truncate">{templateLabel}</div>
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
