import { useState } from 'react'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import CreateInstanceWizard from './components/CreateInstanceWizard'
import InstanceList from './components/InstanceList'
import MonitoringDashboard from './components/MonitoringDashboard'
import LlmInfraChat from './components/LlmInfraChat'
import TaskBoard from './components/TaskBoard'
import OverviewDashboard from './components/OverviewDashboard'
import { Server, List, Plus, Activity, Sparkles, Clock3, LayoutDashboard } from 'lucide-react'
import { provisionInstance, checkIpAvailability } from './services/api'
import { validateStaticNetworkConfig } from './utils/ipValidation'

const createInitialProvisioningConfig = () => ({
  selectedServerId: '',
  selectedTemplateId: '',
  cpuCores: '',
  memory: '',
  selectedStorageId: '',
  selectedNetworkIds: [],
  serverName: '',
  selectedPackages: [],
  selectedRoles: [],
  ipMode: 'dhcp',
  vmIp: '',
  vmGateway: '',
  ipChecked: null,
})

const getActiveTab = (pathname) => {
  if (pathname === '/') return 'overview'
  if (pathname.startsWith('/list')) return 'list'
  if (pathname.startsWith('/create')) return 'create'
  if (pathname.startsWith('/tasks')) return 'tasks'
  if (pathname.startsWith('/monitoring')) return 'monitoring'
  if (pathname.startsWith('/assistant')) return 'assistant'
  return 'overview'
}

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const activeTab = getActiveTab(location.pathname)
  const [provisioningConfig, setProvisioningConfig] = useState(createInitialProvisioningConfig)
  const [, setStatus] = useState('idle')
  const [, setLogs] = useState([])
  const [createMessage, setCreateMessage] = useState(null)
  const [provisioningRequest, setProvisioningRequest] = useState(false)

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString()
    setLogs((prev) => [...prev, { timestamp, message, type }])
  }

  const handleProvision = async () => {
    if (provisioningRequest) {
      return
    }

    setCreateMessage(null)

    if (
      !provisioningConfig.selectedServerId ||
      !provisioningConfig.selectedTemplateId ||
      !provisioningConfig.selectedStorageId ||
      !provisioningConfig.selectedNetworkIds?.length
    ) {
      setCreateMessage({
        type: 'error',
        text: '서버, 템플릿, 스토리지, 네트워크를 모두 선택한 뒤 Launch를 실행해 주세요.',
      })
      return
    }

    setProvisioningRequest(true)
    setStatus('provisioning')
    addLog('Starting VM provisioning request...', 'info')

    try {
      if (provisioningConfig.ipMode === 'static') {
        const validationMessage = validateStaticNetworkConfig(provisioningConfig.vmIp, provisioningConfig.vmGateway)
        if (validationMessage) {
          setStatus('error')
          setCreateMessage({
            type: 'error',
            text: validationMessage,
          })
          return
        }

        const ipOnly = provisioningConfig.vmIp.split('/')[0]
        const ipCheckResponse = await checkIpAvailability(ipOnly)

        if (ipCheckResponse.data?.in_use) {
          setStatus('error')
          setCreateMessage({
            type: 'error',
            text: `IP ${ipOnly} 는 이미 사용중입니다. 다른 IP를 선택해 주세요.`,
          })
          return
        }
      }

      const response = await provisionInstance({
        server_id: provisioningConfig.selectedServerId,
        template_id: provisioningConfig.selectedTemplateId || undefined,
        cpu_cores: provisioningConfig.cpuCores ? parseInt(provisioningConfig.cpuCores) : undefined,
        memory_gb: provisioningConfig.memory ? parseInt(provisioningConfig.memory) : undefined,
        storage_id: provisioningConfig.selectedStorageId,
        network_ids: provisioningConfig.selectedNetworkIds,
        server_name: provisioningConfig.serverName || `instance-${Date.now()}`,
        ansible_packages: provisioningConfig.selectedPackages || [],
        ansible_roles: provisioningConfig.selectedRoles || [],
        // Static IP 모드일 때만 IP 전달
        vm_ip: provisioningConfig.ipMode === 'static' ? provisioningConfig.vmIp : undefined,
        vm_gateway: provisioningConfig.ipMode === 'static' ? provisioningConfig.vmGateway : undefined,
      })
      const taskId = response.data?.task_id || response.data?.id

      if (!taskId) {
        throw new Error('Task ID를 받지 못했습니다.')
      }

      addLog(`VM provisioning initiated. Task ID: ${taskId}`, 'success')
      setCreateMessage({
        type: 'success',
        text: 'VM provisioning 작업이 시작되었습니다. Task Board에서 실시간 진행 상태를 확인하세요.',
      })
      // Task Board로 이동한 뒤 다음 생성을 바로 할 수 있도록 폼 상태를 초기화
      setProvisioningConfig(createInitialProvisioningConfig())
      setCreateMessage(null)

      navigate('/tasks', {
        state: {
          focusTaskId: taskId,
        },
      })
    } catch (error) {
      setStatus('error')
      const errorMessage = error.response?.data?.detail || error.message || '알 수 없는 오류가 발생했습니다.'
      addLog(`VM provisioning error: ${errorMessage}`, 'error')
      setCreateMessage({
        type: 'error',
        text: errorMessage,
      })
    } finally {
      setProvisioningRequest(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="container mx-auto px-8 py-5">
          <div className="flex items-center gap-3">
            <Server className="w-8 h-8 text-blue-600" />
            <h1 className="text-2xl font-semibold text-gray-900">Gjallar VM Operations Console</h1>
          </div>
        </div>
      </header>

      {/* Tabs Navigation */}
      <div className="bg-white border-b border-gray-200 shadow-sm">
        <div className="container mx-auto px-8">
          <div className="flex overflow-x-auto">
            <button
              onClick={() => navigate('/')}
              className={`flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'overview'
                  ? 'text-slate-900 border-slate-900 bg-slate-50'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <LayoutDashboard className="w-5 h-5" />
              Overview
            </button>
            <button
              onClick={() => navigate('/list')}
              className={`flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'list'
                  ? 'text-blue-600 border-blue-600 bg-blue-50'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <List className="w-5 h-5" />
              Instance List
            </button>
            <button
              onClick={() => navigate('/create')}
              className={`flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'create'
                  ? 'text-blue-600 border-blue-600 bg-blue-50'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <Plus className="w-5 h-5" />
              Create Instance
            </button>
            <button
              onClick={() => navigate('/tasks')}
              className={`flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'tasks'
                  ? 'text-blue-600 border-blue-600 bg-blue-50'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <Clock3 className="w-5 h-5" />
              Task Board
            </button>
            <button
              onClick={() => navigate('/monitoring')}
              className={`flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'monitoring'
                  ? 'text-blue-600 border-blue-600 bg-blue-50'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <Activity className="w-5 h-5" />
              Monitoring
            </button>
            <button
              onClick={() => navigate('/assistant')}
              className={`flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'assistant'
                  ? 'text-orange-600 border-orange-600 bg-orange-50'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <Sparkles className="w-5 h-5" />
              LLM Assistant
            </button>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="container mx-auto px-8 py-8">
        <Routes>
          {/* Overview Route */}
          <Route
            path="/"
            element={<OverviewDashboard onNavigate={navigate} />}
          />

          {/* Instance List Route */}
          <Route
            path="/list"
            element={
              <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
                <InstanceList onLogsUpdate={setLogs} onStatusChange={setStatus} />
              </div>
            }
          />

          {/* Task Board Route */}
          <Route
            path="/tasks"
            element={
              <TaskBoard focusTaskId={location.state?.focusTaskId} />
            }
          />

          {/* Monitoring Dashboard Route */}
          <Route
            path="/monitoring"
            element={
              <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
                <MonitoringDashboard />
              </div>
            }
          />

          {/* LLM Assistant Route */}
          <Route
            path="/assistant"
            element={
              <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
                <LlmInfraChat />
              </div>
            }
          />

          {/* Create Instance Route */}
          <Route
            path="/create"
            element={
              <div className="max-w-5xl mx-auto space-y-6">
                <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
                  <div className="p-6">
                    <CreateInstanceWizard
                      config={provisioningConfig}
                      onConfigChange={setProvisioningConfig}
                      onProvision={handleProvision}
                      isProvisioning={provisioningRequest}
                    />
                  </div>
                </div>
                {createMessage && (
                  <div
                    className={`rounded-lg border px-4 py-3 text-sm ${
                      createMessage.type === 'success'
                        ? 'bg-green-50 border-green-200 text-green-700'
                        : 'bg-red-50 border-red-200 text-red-700'
                    }`}
                  >
                    {createMessage.text}
                  </div>
                )}
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  )
}

export default App
