import { Fragment, useEffect, useState } from 'react'
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Cpu,
  HardDrive,
  Loader2,
  Pencil,
  Play,
  Power,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import {
  getStagingHosts,
  getInstances,
  getServers,
  performInstanceAction,
  terminateInstance,
  updateInstanceResources,
} from '../services/api'

const naturalCollator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

function naturalCompare(left, right) {
  return naturalCollator.compare(String(left ?? ''), String(right ?? ''))
}

function normalizeInstanceStatus(status) {
  return String(status ?? '').trim().toLowerCase()
}

function InstanceList({ onLogsUpdate, onStatusChange }) {
  const [groupedInstances, setGroupedInstances] = useState({})
  const [expandedServers, setExpandedServers] = useState(new Set())
  const [pendingInstanceActions, setPendingInstanceActions] = useState({})
  const [editingInstanceKey, setEditingInstanceKey] = useState(null)
  const [editForm, setEditForm] = useState({ cpuCores: '', memoryGb: '' })
  const [stagingHostsByKey, setStagingHostsByKey] = useState({})
  const [openIpPopoverKey, setOpenIpPopoverKey] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString()
    onLogsUpdate((prev) => [
      ...prev,
      { timestamp, message, type },
    ])
  }

  const setPendingAction = (instanceKey, label) => {
    setPendingInstanceActions((prev) => {
      const next = { ...prev }
      if (label) {
        next[instanceKey] = label
      } else {
        delete next[instanceKey]
      }
      return next
    })
  }

  const fetchInstances = async () => {
    try {
      setRefreshing(true)

      const [instancesResponse, serversResponse, stagingHostsResponse] = await Promise.allSettled([
        getInstances(),
        getServers(),
        getStagingHosts(),
      ])

      if (instancesResponse.status !== 'fulfilled' || serversResponse.status !== 'fulfilled') {
        throw (instancesResponse.status === 'rejected' ? instancesResponse.reason : serversResponse.reason)
      }

      const instancesPayload = instancesResponse.value?.data
      const serversPayload = serversResponse.value?.data
      const instancesList =
        instancesPayload?.vms ||
        instancesPayload?.instances ||
        instancesPayload ||
        []
      const serversList = serversPayload?.servers || serversPayload || []
      const stagingHosts =
        stagingHostsResponse.status === 'fulfilled'
          ? stagingHostsResponse.value.data?.hosts || []
          : []

      const sortedServers = [...serversList].sort((a, b) => {
        const nameA = a.name || a.server_name || a.server_id || a.id || ''
        const nameB = b.name || b.server_name || b.server_id || b.id || ''
        return naturalCompare(nameA, nameB)
      })

      const grouped = {}
      sortedServers.forEach((server) => {
        const serverId = server.server_id || server.id
        grouped[serverId] = {
          server,
          instances: [],
        }
      })

      instancesList.forEach((instance) => {
        const node = instance.node || instance.server_id
        if (node && grouped[node]) {
          grouped[node].instances.push(instance)
          return
        }

        if (!grouped.Unknown) {
          grouped.Unknown = {
            server: { server_id: 'Unknown', name: 'Unknown', status: 'unknown' },
            instances: [],
          }
        }
        grouped.Unknown.instances.push(instance)
      })

      Object.keys(grouped).forEach((serverId) => {
        grouped[serverId].instances.sort((a, b) => {
          const nameA = a.name || a.server_name || `vm-${a.vmid || ''}`
          const nameB = b.name || b.server_name || `vm-${b.vmid || ''}`
          return naturalCompare(nameA, nameB)
        })
      })

      const nextStagingHostsByKey = {}
      stagingHosts.forEach((host) => {
        if (!host?.node || host?.vmid == null) {
          return
        }
        nextStagingHostsByKey[`${host.node}:${host.vmid}`] = host
      })

      setGroupedInstances(grouped)
      setStagingHostsByKey(nextStagingHostsByKey)

      if (expandedServers.size === 0) {
        setExpandedServers(new Set(Object.keys(grouped)))
      }

      addLog(
        `Loaded ${instancesList.length} instances across ${serversList.length} servers`,
        'success'
      )
    } catch (error) {
      console.error('Failed to fetch instances:', error)
      addLog(`Failed to load instances: ${error.message}`, 'error')
      setGroupedInstances({})
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchInstances()
    const interval = setInterval(fetchInstances, 30000)
    return () => clearInterval(interval)
  }, [])

  const getInstanceKey = (instance) => {
    const node = instance?.node || 'unknown-node'
    const vmid = instance?.vmid || instance?.vm_id || instance?.id || 'unknown-vm'
    return `${node}:${vmid}`
  }

  const beginEditing = (instance) => {
    const instanceKey = getInstanceKey(instance)
    if (editingInstanceKey === instanceKey) {
      setEditingInstanceKey(null)
      setEditForm({ cpuCores: '', memoryGb: '' })
      return
    }

    setEditingInstanceKey(instanceKey)
    setEditForm({
      cpuCores: String(instance?.cpu_cores || instance?.cpu || ''),
      memoryGb: String(instance?.memory_gb || instance?.memory || ''),
    })
  }

  const handleDestroy = async (instance) => {
    const serverName = instance?.name || instance?.server_name || `VM ${instance?.vmid || ''}`
    const node = instance?.node
    const vmid = instance?.vmid
    const instanceKey = getInstanceKey(instance)

    if (!node || vmid === undefined || vmid === null) {
      addLog(`Cannot terminate instance "${serverName}": missing node/vmid`, 'error')
      return
    }

    if (!confirm(`"${serverName}" 인스턴스를 종료 후 삭제하시겠습니까?\n(1차 확인)`)) {
      return
    }
    if (!confirm(`마지막 확인입니다.\n"${serverName}" 인스턴스를 정말 종료/삭제할까요?`)) {
      return
    }

    try {
      setPendingAction(instanceKey, 'Terminating...')
      onStatusChange('destroying')
      addLog(`Terminating instance "${serverName}" (${node}/${vmid})...`, 'info')
      const response = await terminateInstance({ node, vmid })
      const resultMessage =
        response.data?.message || `Instance "${serverName}" terminated successfully`
      addLog(resultMessage, 'success')
      onStatusChange('idle')
      await fetchInstances()
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message
      addLog(`Failed to terminate instance: ${errorMessage}`, 'error')
      onStatusChange('error')
    } finally {
      setPendingAction(instanceKey, null)
    }
  }

  const handleLifecycleAction = async (instance, action) => {
    const serverName = instance?.name || instance?.server_name || `VM ${instance?.vmid || ''}`
    const node = instance?.node
    const vmid = instance?.vmid
    const instanceKey = getInstanceKey(instance)
    const labelByAction = {
      start: 'Starting...',
      shutdown: 'Shutting down...',
      stop: 'Stopping...',
      reboot: 'Rebooting...',
    }

    if (!node || vmid === undefined || vmid === null) {
      addLog(`Cannot ${action} instance "${serverName}": missing node/vmid`, 'error')
      return
    }

    try {
      setPendingAction(instanceKey, labelByAction[action] || 'Working...')
      onStatusChange(action)
      addLog(`${action} instance "${serverName}" (${node}/${vmid})...`, 'info')
      const response = await performInstanceAction({ node, vmid, action })
      const resultMessage =
        response.data?.message ||
        (action === 'reboot'
          ? `Instance "${serverName}" reboot request accepted`
          : `Instance "${serverName}" ${action} completed successfully`)
      addLog(resultMessage, action === 'reboot' ? 'info' : 'success')
      onStatusChange('idle')
      await fetchInstances()
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message
      addLog(`Failed to ${action} instance: ${errorMessage}`, 'error')
      onStatusChange('error')
    } finally {
      setPendingAction(instanceKey, null)
    }
  }

  const handleResizeSave = async (instance) => {
    const serverName = instance?.name || instance?.server_name || `VM ${instance?.vmid || ''}`
    const node = instance?.node
    const vmid = instance?.vmid
    const instanceKey = getInstanceKey(instance)
    const cpuCores = Number.parseInt(editForm.cpuCores, 10)
    const memoryGb = Number.parseFloat(editForm.memoryGb)

    if (!node || vmid === undefined || vmid === null) {
      addLog(`Cannot resize instance "${serverName}": missing node/vmid`, 'error')
      return
    }

    if (!Number.isFinite(cpuCores) || cpuCores < 1) {
      addLog('CPU cores must be at least 1.', 'error')
      return
    }

    if (!Number.isFinite(memoryGb) || memoryGb < 1) {
      addLog('Memory must be at least 1 GB.', 'error')
      return
    }

    try {
      setPendingAction(instanceKey, 'Saving...')
      onStatusChange('updating-instance')
      addLog(
        `Updating CPU/memory for "${serverName}" (${node}/${vmid}) to ${cpuCores} cores / ${memoryGb} GB...`,
        'info'
      )
      const response = await updateInstanceResources({
        node,
        vmid,
        cpu_cores: cpuCores,
        memory_gb: memoryGb,
      })
      addLog(response.data?.message || 'Instance resources updated successfully.', 'success')
      setEditingInstanceKey(null)
      setEditForm({ cpuCores: '', memoryGb: '' })
      onStatusChange('idle')
      await fetchInstances()
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message
      addLog(`Failed to update instance resources: ${errorMessage}`, 'error')
      onStatusChange('error')
    } finally {
      setPendingAction(instanceKey, null)
    }
  }

  const getStatusBadge = (status) => {
    const statusConfig = {
      running: { color: 'bg-green-100 text-green-800 border-green-200', label: 'Running' },
      stopped: { color: 'bg-gray-100 text-gray-800 border-gray-200', label: 'Stopped' },
      deploying: { color: 'bg-blue-100 text-blue-800 border-blue-200', label: 'Deploying' },
      failed: { color: 'bg-red-100 text-red-800 border-red-200', label: 'Failed' },
    }
    const config = statusConfig[normalizeInstanceStatus(status)] || statusConfig.stopped
    return (
      <span className={`px-2 py-1 text-xs font-semibold rounded border ${config.color}`}>
        {config.label}
      </span>
    )
  }

  const toggleServer = (serverId) => {
    setExpandedServers((prev) => {
      const next = new Set(prev)
      if (next.has(serverId)) {
        next.delete(serverId)
      } else {
        next.add(serverId)
      }
      return next
    })
  }

  const renderActionButtons = (instance, instanceKey, isPending) => {
    const status = normalizeInstanceStatus(instance?.status)
    const sharedClassName =
      'flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed'

    return (
      <div className="flex flex-wrap justify-end gap-2">
        {status === 'running' && (
          <>
            <button
              onClick={() => handleLifecycleAction(instance, 'shutdown')}
              disabled={isPending}
              className={`${sharedClassName} text-amber-700 hover:bg-amber-50`}
            >
              <Power className="w-3.5 h-3.5" />
              Shutdown
            </button>
            <button
              onClick={() => handleLifecycleAction(instance, 'stop')}
              disabled={isPending}
              className={`${sharedClassName} text-orange-700 hover:bg-orange-50`}
            >
              <Square className="w-3.5 h-3.5" />
              Stop
            </button>
            <button
              onClick={() => handleLifecycleAction(instance, 'reboot')}
              disabled={isPending}
              className={`${sharedClassName} text-blue-700 hover:bg-blue-50`}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reboot
            </button>
          </>
        )}
        {status === 'stopped' && (
          <button
            onClick={() => handleLifecycleAction(instance, 'start')}
            disabled={isPending}
            className={`${sharedClassName} text-green-700 hover:bg-green-50`}
          >
            <Play className="w-3.5 h-3.5" />
            Start
          </button>
        )}
        <button
          onClick={() => beginEditing(instance)}
          disabled={isPending}
          className={`${sharedClassName} text-gray-700 hover:bg-gray-100`}
        >
          <Pencil className="w-3.5 h-3.5" />
          {editingInstanceKey === instanceKey ? 'Close' : 'Resize'}
        </button>
        <button
          onClick={() => handleDestroy(instance)}
          disabled={isPending}
          className={`${sharedClassName} text-red-600 hover:bg-red-50`}
        >
          <Trash2 className="w-3.5 h-3.5" />
          {pendingInstanceActions[instanceKey] === 'Terminating...'
            ? 'Terminating...'
            : 'Terminate'}
        </button>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Server className="w-5 h-5 text-blue-600" />
            Instances
          </h2>
          <p className="text-sm text-gray-500 mt-1">Manage your infrastructure instances</p>
        </div>
        <button
          onClick={fetchInstances}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div>
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
            <span className="ml-3 text-gray-600">Loading instances...</span>
          </div>
        ) : Object.keys(groupedInstances).length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertCircle className="w-12 h-12 text-gray-400 mb-4" />
            <p className="text-gray-600 font-medium">No instances found</p>
            <p className="text-sm text-gray-500 mt-1">Create a new instance to get started</p>
          </div>
        ) : (
          <div className="space-y-4">
            {Object.entries(groupedInstances)
              .sort(([idA], [idB]) => {
                const nameA = groupedInstances[idA]?.server?.name || idA
                const nameB = groupedInstances[idB]?.server?.name || idB
                return naturalCompare(nameA, nameB)
              })
              .map(([serverId, group]) => {
                const isExpanded = expandedServers.has(serverId)
                const server = group.server
                const serverInstances = group.instances
                const serverStatus =
                  server.status === 'online'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-800'

                return (
                  <div key={serverId} className="border border-gray-200 rounded-lg overflow-hidden">
                    <div
                      className="bg-gray-50 px-4 py-3 cursor-pointer hover:bg-gray-100 transition-colors flex items-center justify-between"
                      onClick={() => toggleServer(serverId)}
                    >
                      <div className="flex items-center gap-3">
                        {isExpanded ? (
                          <ChevronDown className="w-5 h-5 text-gray-500" />
                        ) : (
                          <ChevronRight className="w-5 h-5 text-gray-500" />
                        )}
                        <Server className="w-5 h-5 text-blue-600" />
                        <div>
                          <div className="font-semibold text-gray-900">
                            {server.name || server.server_id}
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {serverInstances.length} instance
                            {serverInstances.length !== 1 ? 's' : ''}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className={`px-2 py-1 text-xs font-semibold rounded ${serverStatus}`}>
                          {server.status || 'unknown'}
                        </span>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="overflow-x-auto">
                        {serverInstances.length === 0 ? (
                          <div className="px-4 py-8 text-center text-gray-500 text-sm">
                            No instances on this server
                          </div>
                        ) : (
                          <div className="overflow-x-auto">
                            <table className="w-full table-fixed">
                              <colgroup>
                                <col className="w-[180px]" />
                                <col className="w-[100px]" />
                                <col className="w-[90px]" />
                                <col className="w-[100px]" />
                                <col className="w-[180px]" />
                                <col className="w-[320px]" />
                              </colgroup>
                              <thead>
                                <tr className="border-b border-gray-200 bg-gray-50">
                                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">
                                    Name
                                  </th>
                                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">
                                    Status
                                  </th>
                                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">
                                    <Cpu className="w-4 h-4 inline mr-1" />
                                    CPU
                                  </th>
                                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">
                                    <HardDrive className="w-4 h-4 inline mr-1" />
                                    Memory
                                  </th>
                                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">
                                    Disk
                                  </th>
                                  <th className="text-right py-3 px-4 text-sm font-semibold text-gray-700">
                                    Actions
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {serverInstances.map((instance, index) => {
                                  const instanceName =
                                    instance.name ||
                                    instance.server_name ||
                                    `VM ${instance.vmid || ''}`
                                  const instanceKey = getInstanceKey(instance)
                                  const stagingHost = stagingHostsByKey[instanceKey]
                                  const instanceIpAddresses = Array.isArray(instance.ip_addresses)
                                    ? instance.ip_addresses.filter(Boolean)
                                    : []
                                  const displayIp =
                                    instance.primary_ip ||
                                    instanceIpAddresses[0] ||
                                    stagingHost?.host_ip ||
                                    ''
                                  const extraIpAddresses = displayIp
                                    ? instanceIpAddresses.filter((ip) => ip !== displayIp)
                                    : instanceIpAddresses.slice(1)
                                  const extraIpCount = extraIpAddresses.length
                                  const isPending = Boolean(pendingInstanceActions[instanceKey])
                                  const isEditing = editingInstanceKey === instanceKey
                                  const isStopped =
                                    normalizeInstanceStatus(instance.status) === 'stopped'

                                  return (
                                    <Fragment key={instance.id || instance.vm_id || index}>
                                      <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                                        <td className="py-4 px-4">
                                          <div
                                            className="font-medium text-gray-900 truncate"
                                            title={instanceName}
                                          >
                                            {instanceName}
                                          </div>
                                          {stagingHost || displayIp ? (
                                            <div className="mt-2 space-y-1.5">
                                              {stagingHost ? (
                                                <div>
                                                  <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                                                    Staging Host
                                                  </span>
                                                </div>
                                              ) : null}
                                              {displayIp ? (
                                                <div className="relative inline-flex items-center gap-1">
                                                  <span
                                                    className="inline-flex items-center rounded-md border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-xs text-gray-600"
                                                    title={displayIp}
                                                  >
                                                    {displayIp}
                                                  </span>
                                                  {extraIpCount > 0 ? (
                                                    <>
                                                      <button
                                                        type="button"
                                                        onClick={() =>
                                                          setOpenIpPopoverKey((current) =>
                                                            current === instanceKey ? null : instanceKey
                                                          )
                                                        }
                                                        className="inline-flex items-center rounded-md border border-gray-200 bg-white px-1.5 py-1 text-[11px] font-medium text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                                                        title={extraIpAddresses.join(', ')}
                                                      >
                                                        +{extraIpCount}
                                                      </button>
                                                      {openIpPopoverKey === instanceKey ? (
                                                        <div className="absolute left-0 top-full z-20 mt-1 min-w-[180px] rounded-md border border-gray-200 bg-white p-2 shadow-lg">
                                                          <div className="mb-1 text-[11px] font-medium text-gray-700">
                                                            Additional IPs
                                                          </div>
                                                          <div className="space-y-1">
                                                            {extraIpAddresses.map((ip) => (
                                                              <div
                                                                key={ip}
                                                                className="font-mono text-xs text-gray-600"
                                                              >
                                                                {ip}
                                                              </div>
                                                            ))}
                                                          </div>
                                                        </div>
                                                      ) : null}
                                                    </>
                                                  ) : null}
                                                </div>
                                              ) : null}
                                            </div>
                                          ) : null}
                                          {instance.vmid && (
                                            <div className="text-xs text-gray-500 mt-0.5 truncate">
                                              ID: {instance.vmid}
                                            </div>
                                          )}
                                        </td>
                                        <td className="py-4 px-4">
                                          <div className="flex-shrink-0">
                                            {getStatusBadge(instance.status)}
                                          </div>
                                        </td>
                                        <td className="py-4 px-4 text-sm text-gray-600 whitespace-nowrap">
                                          {instance.cpu_cores || instance.cpu || '-'} cores
                                        </td>
                                        <td className="py-4 px-4 text-sm text-gray-600 whitespace-nowrap">
                                          {instance.memory_gb || instance.memory || '-'} GB
                                        </td>
                                        <td className="py-4 px-4 text-sm text-gray-600">
                                          {instance.disks && instance.disks.length > 0 ? (
                                            <div className="space-y-1">
                                              {instance.disks.map((disk, idx) => (
                                                <div
                                                  key={idx}
                                                  className="text-xs truncate"
                                                  title={`${disk.device}: ${disk.size_gb} GB${
                                                    disk.storage !== 'unknown'
                                                      ? ` (${disk.storage})`
                                                      : ''
                                                  }`}
                                                >
                                                  {disk.device}: {disk.size_gb} GB
                                                  {disk.storage !== 'unknown' && (
                                                    <span className="text-gray-400 ml-1">
                                                      ({disk.storage})
                                                    </span>
                                                  )}
                                                </div>
                                              ))}
                                              {instance.disks.length > 1 && (
                                                <div className="text-xs font-semibold text-gray-700 pt-1 border-t border-gray-200">
                                                  Total:{' '}
                                                  {instance.disk_gb ||
                                                    instance.disks
                                                      .reduce((sum, disk) => sum + disk.size_gb, 0)
                                                      .toFixed(2)}{' '}
                                                  GB
                                                </div>
                                              )}
                                            </div>
                                          ) : instance.disk_gb ? (
                                            `${instance.disk_gb} GB`
                                          ) : (
                                            '-'
                                          )}
                                        </td>
                                        <td className="py-4 px-4">
                                          {isPending ? (
                                            <div className="flex justify-end items-center gap-2 text-sm text-gray-500">
                                              <Loader2 className="w-4 h-4 animate-spin" />
                                              {pendingInstanceActions[instanceKey]}
                                            </div>
                                          ) : (
                                            renderActionButtons(instance, instanceKey, isPending)
                                          )}
                                        </td>
                                      </tr>
                                      {isEditing && (
                                        <tr className="bg-gray-50/70 border-b border-gray-100">
                                          <td colSpan={6} className="px-4 py-4">
                                            <div className="flex flex-col gap-3">
                                              <div className="flex flex-col lg:flex-row lg:items-end gap-3">
                                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 flex-1">
                                                  <div>
                                                    <label className="block text-xs font-medium text-gray-700 mb-1">
                                                      CPU Cores
                                                    </label>
                                                    <input
                                                      type="number"
                                                      min="1"
                                                      value={editForm.cpuCores}
                                                      onChange={(event) =>
                                                        setEditForm((prev) => ({
                                                          ...prev,
                                                          cpuCores: event.target.value,
                                                        }))
                                                      }
                                                      className="w-full px-3 py-2 bg-white border border-gray-300 rounded-md text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                                    />
                                                  </div>
                                                  <div>
                                                    <label className="block text-xs font-medium text-gray-700 mb-1">
                                                      Memory (GB)
                                                    </label>
                                                    <input
                                                      type="number"
                                                      min="0.25"
                                                      step="0.25"
                                                      value={editForm.memoryGb}
                                                      onChange={(event) =>
                                                        setEditForm((prev) => ({
                                                          ...prev,
                                                          memoryGb: event.target.value,
                                                        }))
                                                      }
                                                      className="w-full px-3 py-2 bg-white border border-gray-300 rounded-md text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                                    />
                                                  </div>
                                                </div>
                                                <div className="flex items-center justify-end gap-2">
                                                  <button
                                                    onClick={() => handleResizeSave(instance)}
                                                    disabled={!isStopped || isPending}
                                                    className="flex items-center gap-1 px-3 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-blue-300 disabled:cursor-not-allowed transition-colors"
                                                  >
                                                    <Save className="w-4 h-4" />
                                                    Save
                                                  </button>
                                                  <button
                                                    onClick={() => beginEditing(instance)}
                                                    disabled={isPending}
                                                    className="flex items-center gap-1 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                                  >
                                                    <X className="w-4 h-4" />
                                                    Cancel
                                                  </button>
                                                </div>
                                              </div>
                                              {!isStopped && (
                                                <p className="text-xs text-amber-700">
                                                  CPU/Memory change requires a stopped VM. Use
                                                  Shutdown or Stop first.
                                                </p>
                                              )}
                                            </div>
                                          </td>
                                        </tr>
                                      )}
                                    </Fragment>
                                  )
                                })}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
          </div>
        )}
      </div>
    </div>
  )
}

export default InstanceList
