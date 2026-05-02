import { useState, useEffect } from 'react'
import { Activity, Server, Cpu, HardDrive, TrendingUp, RefreshCw, Loader2, AlertCircle, Database } from 'lucide-react'
import { getNodesMonitoring } from '../services/api'

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

  const getUsageColor = (percent) => {
    if (percent >= 90) return 'bg-red-500'
    if (percent >= 70) return 'bg-yellow-500'
    return 'bg-green-500'
  }

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
                        {(typeof node.cpu_usage_percent === 'number' ? node.cpu_usage_percent : parseFloat(node.cpu_usage_percent || 0)).toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2.5">
                      <div
                        className={`h-full rounded-full transition-all ${getUsageColor(typeof node.cpu_usage_percent === 'number' ? node.cpu_usage_percent : parseFloat(node.cpu_usage_percent || 0))}`}
                        style={{ width: `${Math.min(typeof node.cpu_usage_percent === 'number' ? node.cpu_usage_percent : parseFloat(node.cpu_usage_percent || 0), 100)}%` }}
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
                        {(typeof node.memory_usage_percent === 'number' ? node.memory_usage_percent : parseFloat(node.memory_usage_percent || 0)).toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2.5">
                      <div
                        className={`h-full rounded-full transition-all ${getUsageColor(typeof node.memory_usage_percent === 'number' ? node.memory_usage_percent : parseFloat(node.memory_usage_percent || 0))}`}
                        style={{ width: `${Math.min(typeof node.memory_usage_percent === 'number' ? node.memory_usage_percent : parseFloat(node.memory_usage_percent || 0), 100)}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {((typeof node.memory_used_gb === 'number' ? node.memory_used_gb : parseFloat(node.memory_used_gb || 0))).toFixed(2)} GB / {((typeof node.memory_total_gb === 'number' ? node.memory_total_gb : parseFloat(node.memory_total_gb || 0))).toFixed(2)} GB
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
                                {(typeof storage.usage_percent === 'number' ? storage.usage_percent : parseFloat(storage.usage_percent || 0)).toFixed(1)}%
                              </span>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-1.5">
                              <div
                                className={`h-full rounded-full transition-all ${getUsageColor(typeof storage.usage_percent === 'number' ? storage.usage_percent : parseFloat(storage.usage_percent || 0))}`}
                                style={{ width: `${Math.min(typeof storage.usage_percent === 'number' ? storage.usage_percent : parseFloat(storage.usage_percent || 0), 100)}%` }}
                              />
                            </div>
                            <p className="text-xs text-gray-500 mt-1">
                              {((typeof storage.used_gb === 'number' ? storage.used_gb : parseFloat(storage.used_gb || 0))).toFixed(2)} GB / {((typeof storage.total_gb === 'number' ? storage.total_gb : parseFloat(storage.total_gb || 0))).toFixed(2)} GB
                              <span className="ml-2 text-gray-400">
                                ({((typeof storage.available_gb === 'number' ? storage.available_gb : parseFloat(storage.available_gb || 0))).toFixed(2)} GB available)
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
