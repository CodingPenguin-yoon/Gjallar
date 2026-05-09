import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Cpu,
  Eye,
  HardDrive,
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

function MetricCard({ label, value, hint, icon: Icon }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
          <div className="mt-2 text-2xl font-semibold text-slate-950">{value}</div>
          <div className="mt-1 text-xs text-slate-500">{hint}</div>
        </div>
        <div className="rounded-lg bg-blue-50 p-2 text-blue-700">
          <Icon className="h-4 w-4" />
        </div>
      </div>
    </div>
  )
}

function VmRow({ vm, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(vm)}
      className={`w-full border-t border-slate-100 px-4 py-3 text-left transition ${selected ? 'bg-blue-50' : 'bg-white hover:bg-slate-50'}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-950">{vm.name}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">VMID {vm.vmid ?? '-'}</span>
          </div>
          <div className="mt-1 text-xs text-slate-500">{vm.primaryIp === '-' ? 'No guest IP visible' : vm.primaryIp}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span className={`rounded-full px-2 py-1 ${statusTone(vm.status)}`}>{vm.status || 'unknown'}</span>
          <span className="rounded-full bg-slate-100 px-2 py-1">CPU {formatNumber(vm.cpuCores)}</span>
          <span className="rounded-full bg-slate-100 px-2 py-1">RAM {formatNumber(vm.memoryGb, 1)} GB</span>
          <span className="rounded-full bg-slate-100 px-2 py-1">Disk {formatNumber(vm.diskGb, 1)} GB</span>
        </div>
      </div>
    </button>
  )
}

function VmDetail({ vm }) {
  if (!vm) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
        Select a VM to inspect read only details.
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">{vm.name}</h3>
          <p className="text-sm text-slate-500">Node {vm.nodeId} · VMID {vm.vmid ?? '-'}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone(vm.status)}`}>{vm.status || 'unknown'}</span>
      </div>
      <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-lg bg-slate-50 p-3">
          <dt className="text-slate-500">Primary IP</dt>
          <dd className="mt-1 font-medium text-slate-950">{vm.primaryIp}</dd>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <dt className="text-slate-500">Template</dt>
          <dd className="mt-1 font-medium text-slate-950">{vm.template ? 'yes' : 'no'}</dd>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <dt className="text-slate-500">CPU</dt>
          <dd className="mt-1 font-medium text-slate-950">{formatNumber(vm.cpuCores)} cores</dd>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <dt className="text-slate-500">Memory</dt>
          <dd className="mt-1 font-medium text-slate-950">{formatNumber(vm.memoryGb, 1)} GB</dd>
        </div>
      </dl>
      <div className="mt-5 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800">
        This Infra Explorer slice is read only. Action controls are intentionally unavailable.
      </div>
    </div>
  )
}

function InstanceList({ onLogsUpdate = () => {}, onStatusChange = () => {} }) {
  const [model, setModel] = useState(null)
  const [selectedVmId, setSelectedVmId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

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

  const selectedVm = useMemo(() => {
    const allVms = model?.nodes?.flatMap((node) => node.vms) || []
    return allVms.find((vm) => `${vm.nodeId}:${vm.vmid ?? vm.id}` === selectedVmId) || allVms[0] || null
  }, [model, selectedVmId])

  const selectVm = (vm) => {
    setSelectedVmId(`${vm.nodeId}:${vm.vmid ?? vm.id}`)
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-slate-200 bg-white">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-blue-600" />
        <span className="text-sm text-slate-600">Loading Infra Explorer...</span>
      </div>
    )
  }

  const summary = model?.summary || { totalNodes: 0, totalVms: 0, runningVms: 0, visibleIpCount: 0 }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-blue-600">Infra Explorer</p>
          <h2 className="mt-1 text-2xl font-semibold text-slate-950">Nodes and VMs</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Read only view backed by the PRD `/api/v1` inventory contract.
          </p>
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
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <AlertTriangle className="mt-0.5 h-4 w-4" />
          <div>{errorMessage}</div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard label="Nodes" value={summary.totalNodes} hint="Observed cluster nodes" icon={Server} />
        <MetricCard label="VMs" value={summary.totalVms} hint="Visible virtual machines" icon={Eye} />
        <MetricCard label="Running" value={summary.runningVms} hint="Currently running" icon={Cpu} />
        <MetricCard label="IPs" value={summary.visibleIpCount} hint="Guest IPs visible" icon={HardDrive} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
        <div className="space-y-4">
          {(model?.nodes || []).map((node) => (
            <section key={node.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3">
                <div>
                  <h3 className="font-semibold text-slate-950">{node.name}</h3>
                  <p className="text-xs text-slate-500">{node.vms.length} VMs</p>
                </div>
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${statusTone(node.status)}`}>{node.status || 'unknown'}</span>
              </div>
              {node.vms.length === 0 ? (
                <div className="px-4 py-6 text-sm text-slate-500">No VMs observed on this node.</div>
              ) : (
                node.vms.map((vm) => (
                  <VmRow
                    key={`${vm.nodeId}:${vm.vmid ?? vm.id}`}
                    vm={vm}
                    selected={selectedVm === vm}
                    onSelect={selectVm}
                  />
                ))
              )}
            </section>
          ))}
        </div>
        <VmDetail vm={selectedVm} />
      </div>
    </div>
  )
}

export default InstanceList
