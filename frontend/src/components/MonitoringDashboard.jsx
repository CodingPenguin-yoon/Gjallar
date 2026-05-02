import { useState, useEffect } from 'react'
import { Activity, Server, Cpu, HardDrive, TrendingUp, RefreshCw, Loader2, AlertCircle, Database } from 'lucide-react'
import { getNodesMonitoring } from '../services/api'
import { buildMonitoringSummary, getResourceTone, toNumber } from '../utils/monitoringSignals'

const naturalCollator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

function naturalCompare(left, right) {
  return naturalCollator.compare(String(left ?? ''), String(right ?? ''))
}

function MonitoringDashboard() {
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchMonitoringData = async () => {
    try {
      setRefreshing(true)
      const response = await getNodesMonitoring()
      setNodes(response.data?.nodes || [])
    } catch (error) {
      console.error('Failed to fetch monitoring data:', error)
      setNodes([])
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchMonitoringData()
    // 30초마다 자동 새로고침
    const interval = setInterval(fetchMonitoringData, 30000)
    return () => clearInterval(interval)
  }, [])

  const formatUptime = (seconds) => {
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    
    if (days > 0) return `${days}d ${hours}h`
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  const monitoringSummary = buildMonitoringSummary(nodes)

  const getUsageColor = (percent) => getResourceTone(percent).barClass

  const getStatusBadge = (status) => {
    const isOnline = status === 'online'
    return (
      <span className={`px-2 py-1 text-xs font-semibold rounded ${
        isOnline ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
      }`}>
        {status}
      </span>
    )
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Activity className="w-5 h-5 text-blue-600" />
            System Monitoring
          </h2>
          <p className="text-sm text-gray-500 mt-1">Real-time resource usage and system status</p>
        </div>
        <button
          onClick={fetchMonitoringData}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>


      {!loading && nodes.length > 0 && (
        <div className="mb-6 grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide">Nodes Online</div>
            <div className="mt-1 text-2xl font-semibold text-gray-900">
              {monitoringSummary.onlineNodes}/{monitoringSummary.totalNodes}
            </div>
          </div>
          <div className="rounded-lg border border-red-200 bg-red-50 p-4">
            <div className="text-xs text-red-600 uppercase tracking-wide">Critical Signals</div>
            <div className="mt-1 text-2xl font-semibold text-red-700">{monitoringSummary.criticalSignals}</div>
          </div>
          <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4">
            <div className="text-xs text-yellow-700 uppercase tracking-wide">Warnings</div>
            <div className="mt-1 text-2xl font-semibold text-yellow-700">{monitoringSummary.warningSignals}</div>
          </div>
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
            <div className="text-xs text-blue-700 uppercase tracking-wide">Refresh</div>
            <div className="mt-1 text-sm font-medium text-blue-800">Every 30 seconds</div>
          </div>
        </div>
      )}

      {!loading && monitoringSummary.signals.length > 0 && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <div className="text-sm font-semibold text-amber-900">Node/Storage Signals</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {monitoringSummary.signals.slice(0, 8).map((signal) => (
              <span key={signal.label} className={`rounded-full px-2 py-1 text-xs font-medium ${signal.level === 'critical' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'}`}>
                {signal.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Content */}
      <div>
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
            <span className="ml-3 text-gray-600">Loading monitoring data...</span>
          </div>
        ) : nodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertCircle className="w-12 h-12 text-gray-400 mb-4" />
            <p className="text-gray-600 font-medium">No monitoring data available</p>
            <p className="text-sm text-gray-500 mt-1">Unable to fetch system monitoring information</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {[...nodes].sort((a, b) => {
              const nameA = a.name || a.node || ''
              const nameB = b.name || b.node || ''
              return naturalCompare(nameA, nameB)
            }).map((node) => (
              <div key={node.node} className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
                {/* Node Header */}
                <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Server className="w-5 h-5 text-blue-600" />
                      <div>
                        <h3 className="font-semibold text-gray-900">{node.name}</h3>
                        <p className="text-xs text-gray-500 mt-0.5">Uptime: {formatUptime(node.uptime)}</p>
                      </div>
                    </div>
                    {getStatusBadge(node.status)}
                  </div>
                </div>

                {/* Node Metrics */}
                <div className="p-6 space-y-6">
                  {/* CPU Usage */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-gray-600" />
                        <span className="text-sm font-medium text-gray-700">CPU Usage</span>
                      </div>
                      <span className="text-sm font-semibold text-gray-900">
                        {toNumber(node.cpu_usage_percent).toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2.5">
                      <div
                        className={`h-full rounded-full transition-all ${getUsageColor(typeof node.cpu_usage_percent === 'number' ? node.cpu_usage_percent : parseFloat(node.cpu_usage_percent || 0))}`}
                        style={{ width: `${Math.min(toNumber(node.cpu_usage_percent), 100)}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {node.cpu_total} cores total
                    </p>
                  </div>

                  {/* Memory Usage */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <HardDrive className="w-4 h-4 text-gray-600" />
                        <span className="text-sm font-medium text-gray-700">Memory Usage</span>
                      </div>
                      <span className="text-sm font-semibold text-gray-900">
                        {toNumber(node.memory_usage_percent).toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2.5">
                      <div
                        className={`h-full rounded-full transition-all ${getUsageColor(typeof node.memory_usage_percent === 'number' ? node.memory_usage_percent : parseFloat(node.memory_usage_percent || 0))}`}
                        style={{ width: `${Math.min(toNumber(node.memory_usage_percent), 100)}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {toNumber(node.memory_used_gb).toFixed(2)} GB / {toNumber(node.memory_total_gb).toFixed(2)} GB
                    </p>
                  </div>

                  {/* Disk Usage - 개별 스토리지 목록 */}
                  {node.storages && node.storages.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-3">
                        <Database className="w-4 h-4 text-gray-600" />
                        <span className="text-sm font-medium text-gray-700">Disk Usage</span>
                      </div>
                      <div className="space-y-2">
                        {[...(node.storages || [])].sort((a, b) => {
                          const nameA = a.name || ''
                          const nameB = b.name || ''
                          return naturalCompare(nameA, nameB)
                        }).map((storage, index) => (
                          <div key={index} className="border border-gray-200 rounded-md p-2.5 bg-gray-50">
                            <div className="flex items-center justify-between mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold text-gray-900">{storage.name}</span>
                                <span className="text-xs text-gray-500">({storage.type})</span>
                              </div>
                              <span className="text-xs font-semibold text-gray-900">
                                {toNumber(storage.usage_percent).toFixed(1)}%
                              </span>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-1.5">
                              <div
                                className={`h-full rounded-full transition-all ${getUsageColor(typeof storage.usage_percent === 'number' ? storage.usage_percent : parseFloat(storage.usage_percent || 0))}`}
                                style={{ width: `${Math.min(toNumber(storage.usage_percent), 100)}%` }}
                              />
                            </div>
                            <p className="text-xs text-gray-500 mt-1">
                              {toNumber(storage.used_gb).toFixed(2)} GB / {toNumber(storage.total_gb).toFixed(2)} GB
                              <span className="ml-2 text-gray-400">
                                ({toNumber(storage.available_gb).toFixed(2)} GB available)
                              </span>
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Load Average */}
                  {node.load_avg && node.load_avg.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <TrendingUp className="w-4 h-4 text-gray-600" />
                        <span className="text-sm font-medium text-gray-700">Load Average</span>
                      </div>
                      <div className="flex gap-4 text-sm">
                        <div>
                          <span className="text-gray-500">1m:</span>
                          <span className="ml-1 font-semibold text-gray-900">
                            {typeof node.load_avg[0] === 'number' ? node.load_avg[0].toFixed(2) : parseFloat(node.load_avg[0] || 0).toFixed(2)}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">5m:</span>
                          <span className="ml-1 font-semibold text-gray-900">
                            {typeof node.load_avg[1] === 'number' ? node.load_avg[1].toFixed(2) : parseFloat(node.load_avg[1] || 0).toFixed(2)}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">15m:</span>
                          <span className="ml-1 font-semibold text-gray-900">
                            {typeof node.load_avg[2] === 'number' ? node.load_avg[2].toFixed(2) : parseFloat(node.load_avg[2] || 0).toFixed(2)}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default MonitoringDashboard
