import axios from 'axios'

// API 기본 URL 설정 (프록시를 통해 /api로 요청)
const API_BASE_URL = '/api'
const parsedTimeout = Number(import.meta.env.VITE_API_TIMEOUT_MS || 120000)
const API_TIMEOUT_MS = Number.isFinite(parsedTimeout) && parsedTimeout > 0 ? parsedTimeout : 120000

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: API_TIMEOUT_MS,
})

// 요청 인터셉터: API 호출 URL 로깅
apiClient.interceptors.request.use(
  (config) => {
    const fullUrl = `${config.baseURL}${config.url}`
    console.log(`[API Request] ${config.method?.toUpperCase()} ${fullUrl}`)
    if (config.params) {
      console.log('[API Params]', config.params)
    }
    if (config.data) {
      console.log('[API Data]', config.data)
    }
    return config
  },
  (error) => {
    console.error('[API Request Error]', error)
    return Promise.reject(error)
  }
)

// 응답 인터셉터: 응답 로깅
apiClient.interceptors.response.use(
  (response) => {
    console.log(`[API Response] ${response.config.method?.toUpperCase()} ${response.config.url}`, response.status, response.data)
    return response
  },
  (error) => {
    console.error(`[API Error] ${error.config?.method?.toUpperCase()} ${error.config?.url}`, error.response?.status, error.response?.data || error.message)
    return Promise.reject(error)
  }
)

// 배포 시작 API
export const deployInfrastructure = async (config) => {
  try {
    // 새로운 마법사 스타일 config 또는 기존 config 모두 지원
    const payload = config.server_id
      ? {
          server_id: config.server_id,
          template_id: config.template_id,
          storage_id: config.storage_id,
          storage_type: config.storage_type,
          network_ids: config.network_ids,
          server_name: config.server_name,
          cpu_cores: config.cpu_cores,
          memory_gb: config.memory_gb,
          disk_size_gb: config.disk_size_gb || 50,
          ansible_packages: config.ansible_packages || [],
          ansible_roles: config.ansible_roles || [],
          vm_ip: config.vm_ip,
          vm_gateway: config.vm_gateway,
          create_as_staging_host: Boolean(config.create_as_staging_host),
        }
      : {
          server_id: config.selectedServerId,
          template_id: config.selectedTemplateId,
          server_name: config.serverName || `instance-${Date.now()}`,
          cpu_cores: config.cpuCores ? parseInt(config.cpuCores) : undefined,
          memory_gb: config.memory ? parseInt(config.memory) : undefined,
          disk_size_gb: parseInt(config.diskSize) || 50,
          storage_id: config.selectedStorageId,
          network_ids: config.selectedNetworkIds || [],
          ansible_packages: config.selectedPackages || [],
          ansible_roles: config.selectedRoles || [],
          create_as_staging_host: Boolean(config.createAsStagingHost),
        }
    const response = await apiClient.post('/deploy', payload)
    return response
  } catch (error) {
    console.error('Deploy API error:', error)
    throw error
  }
}

// 인스턴스 종료 후 삭제 API
export const terminateInstance = async ({
  node,
  vmid,
  shutdown_timeout_seconds = 60,
  force_stop_timeout_seconds = 30,
}) => {
  try {
    const response = await apiClient.post('/instances/terminate', {
      node,
      vmid,
      shutdown_timeout_seconds,
      force_stop_timeout_seconds,
    })
    return response
  } catch (error) {
    console.error('Terminate instance API error:', error)
    throw error
  }
}

export const performInstanceAction = async ({
  node,
  vmid,
  action,
  timeout_seconds = 60,
}) => {
  try {
    const response = await apiClient.post('/instances/action', {
      node,
      vmid,
      action,
      timeout_seconds,
    })
    return response
  } catch (error) {
    console.error('Instance action API error:', error)
    throw error
  }
}

export const updateInstanceResources = async ({
  node,
  vmid,
  cpu_cores,
  memory_gb,
}) => {
  try {
    const response = await apiClient.patch('/instances/resources', {
      node,
      vmid,
      cpu_cores,
      memory_gb,
    })
    return response
  } catch (error) {
    console.error('Update instance resources API error:', error)
    throw error
  }
}

// 상태 확인 API
export const checkStatus = async (taskId) => {
  try {
    const response = await apiClient.get(`/status/${taskId}`)
    return response
  } catch (error) {
    console.error('Status API error:', error)
    throw error
  }
}

// 로그 조회 API
export const getLogs = async (taskId) => {
  try {
    const response = await apiClient.get(`/logs/${taskId}`)
    return response
  } catch (error) {
    console.error('Logs API error:', error)
    throw error
  }
}

export const requestGitLabStagingDeploy = async (projectId) => {
  try {
    const response = await apiClient.post(`/gitlab/projects/${projectId}/deploy/staging`)
    return response
  } catch (error) {
    console.error('GitLab staging deploy request API error:', error)
    throw error
  }
}

// 작업 목록 조회 API (최신순)
// 사용 예:
// - getTasks(200)
// - getTasks({ limit: 300, status: 'running,success', q: 'vm-104', include_archived: true })
export const getTasks = async (limitOrOptions = 100) => {
  try {
    let options = {}
    if (typeof limitOrOptions === 'number') {
      options.limit = limitOrOptions
    } else if (limitOrOptions && typeof limitOrOptions === 'object') {
      options = { ...limitOrOptions }
    }

    const response = await apiClient.get('/tasks', {
      params: {
        limit: options.limit ?? 100,
        status: options.status,
        q: options.q,
        date_from: options.date_from,
        date_to: options.date_to,
        include_archived: options.include_archived ?? false,
      },
    })
    return response
  } catch (error) {
    console.error('Get tasks API error:', error)
    throw error
  }
}

// 작업 이벤트 스트림(SSE)
export const createTaskEventStream = ({
  includeArchived = true,
  lastEventId = null,
} = {}) => {
  const params = new URLSearchParams()
  params.set('include_archived', includeArchived ? 'true' : 'false')
  if (lastEventId !== null && lastEventId !== undefined) {
    params.set('last_event_id', String(lastEventId))
  }
  return new EventSource(`/api/tasks/stream?${params.toString()}`)
}

// 작업 상세 조회 API
export const getTaskDetail = async (taskId) => {
  try {
    const response = await apiClient.get(`/tasks/${taskId}`)
    return response
  } catch (error) {
    console.error('Get task detail API error:', error)
    throw error
  }
}

// 작업 아카이브 토글 API
export const archiveTask = async (taskId, archived = true) => {
  try {
    const response = await apiClient.post(`/tasks/${taskId}/archive`, {
      archived,
    })
    return response
  } catch (error) {
    console.error('Archive task API error:', error)
    throw error
  }
}

// 인스턴스 목록 조회 API
export const getInstances = async () => {
  try {
    const response = await apiClient.get('/instances')
    return response
  } catch (error) {
    console.error('Get instances API error:', error)
    throw error
  }
}

export const getStagingHosts = async () => {
  try {
    const response = await apiClient.get('/staging-hosts')
    return response
  } catch (error) {
    console.error('Get staging hosts API error:', error)
    throw error
  }
}

// 서버/템플릿 목록 조회 API
export const getServers = async () => {
  try {
    const response = await apiClient.get('/servers')
    return response
  } catch (error) {
    console.error('Get servers API error:', error)
    throw error
  }
}

// 템플릿 목록 조회 API
export const getTemplates = async () => {
  try {
    const response = await apiClient.get('/templates')
    return response
  } catch (error) {
    console.error('Get templates API error:', error)
    throw error
  }
}

// 서버의 스토리지 목록 조회 API
export const getServerStorage = async (serverId) => {
  try {
    const response = await apiClient.get(`/servers/${serverId}/storage`)
    return response
  } catch (error) {
    console.error('Get server storage API error:', error)
    throw error
  }
}

// 서버의 네트워크 목록 조회 API
export const getServerNetworks = async (serverId) => {
  try {
    const response = await apiClient.get(`/servers/${serverId}/networks`)
    return response
  } catch (error) {
    console.error('Get server networks API error:', error)
    throw error
  }
}

// VM 목록 조회 API (템플릿 제외)
export const getVMs = async () => {
  try {
    const response = await apiClient.get('/vms')
    return response
  } catch (error) {
    console.error('Get VMs API error:', error)
    throw error
  }
}

// 서버의 VM 목록 조회 API
export const getServerVMs = async (serverId) => {
  try {
    const response = await apiClient.get(`/servers/${serverId}/vms`)
    return response
  } catch (error) {
    console.error('Get server VMs API error:', error)
    throw error
  }
}

// 모니터링 API
export const getNodesMonitoring = async () => {
  try {
    const response = await apiClient.get('/monitoring/nodes')
    return response
  } catch (error) {
    console.error('Get nodes monitoring API error:', error)
    throw error
  }
}

export const getNodeMonitoring = async (nodeId) => {
  try {
    const response = await apiClient.get(`/monitoring/nodes/${nodeId}`)
    return response
  } catch (error) {
    console.error('Get node monitoring API error:', error)
    throw error
  }
}

export const getVMMonitoring = async (nodeId, vmid) => {
  try {
    const response = await apiClient.get(`/monitoring/vms/${nodeId}/${vmid}`)
    return response
  } catch (error) {
    console.error('Get VM monitoring API error:', error)
    throw error
  }
}

// LLM 채팅 API
export const llmChat = async (payload) => {
  try {
    const response = await apiClient.post('/llm/chat', payload)
    return response
  } catch (error) {
    console.error('LLM Chat API error:', error)
    throw error
  }
}

// LLM 액션 실행 API
export const executeLlmAction = async ({ action }) => {
  try {
    const response = await apiClient.post('/llm/execute-action', { action })
    return response
  } catch (error) {
    console.error('Execute LLM Action API error:', error)
    throw error
  }
}

// LLM 세션 이력 조회 API
export const getLlmSessionMessages = async (sessionId) => {
  try {
    const response = await apiClient.get(`/llm/session/${sessionId}/messages`)
    return response
  } catch (error) {
    console.error('Get LLM Session Messages API error:', error)
    throw error
  }
}

// LLM 세션 삭제 API
export const clearLlmSession = async (sessionId) => {
  try {
    const response = await apiClient.delete(`/llm/session/${sessionId}`)
    return response
  } catch (error) {
    console.error('Clear LLM Session API error:', error)
    throw error
  }
}

// IP 풀 설정 조회 API
export const getIpPoolConfig = async () => {
  try {
    const response = await apiClient.get('/network/ip-pool/config')
    return response
  } catch (error) {
    console.error('Get IP Pool Config API error:', error)
    throw error
  }
}

// 사용 가능한 IP 목록 조회 API
export const getAvailableIps = async (limit = 10) => {
  try {
    const response = await apiClient.get(`/network/ip-pool/available?limit=${limit}`)
    return response
  } catch (error) {
    console.error('Get Available IPs API error:', error)
    throw error
  }
}

export const getGitLabProjects = async () => {
  try {
    const response = await apiClient.get('/gitlab/projects')
    return response
  } catch (error) {
    console.error('Get GitLab projects API error:', error)
    throw error
  }
}

export const getGitLabNamespaces = async () => {
  try {
    const response = await apiClient.get('/gitlab/namespaces')
    return response
  } catch (error) {
    console.error('Get GitLab namespaces API error:', error)
    throw error
  }
}

export const createGitLabProject = async (payload) => {
  try {
    const response = await apiClient.post('/gitlab/projects', payload)
    return response
  } catch (error) {
    console.error('Create GitLab project API error:', error)
    throw error
  }
}

export const getGitLabProjectSettings = async (projectId) => {
  try {
    const response = await apiClient.get(`/gitlab/projects/${projectId}/settings`)
    return response
  } catch (error) {
    console.error('Get GitLab project settings API error:', error)
    throw error
  }
}

export const previewGitLabProjectSettings = async (projectId, payload) => {
  try {
    const response = await apiClient.post(`/gitlab/projects/${projectId}/settings/preview`, payload)
    return response
  } catch (error) {
    console.error('Preview GitLab project settings API error:', error)
    throw error
  }
}

export const getGitLabProjectManifest = async (projectId, ref = null) => {
  try {
    const response = await apiClient.get(`/gitlab/projects/${projectId}/manifest`, {
      params: ref ? { ref } : undefined,
    })
    return response
  } catch (error) {
    console.error('Get GitLab project manifest API error:', error)
    throw error
  }
}

export const updateGitLabProjectManifest = async (projectId, payload) => {
  try {
    const response = await apiClient.put(`/gitlab/projects/${projectId}/manifest`, payload)
    return response
  } catch (error) {
    console.error('Update GitLab project manifest API error:', error)
    throw error
  }
}

export const previewGitLabProjectManifest = async (projectId, payload) => {
  try {
    const response = await apiClient.post(`/gitlab/projects/${projectId}/manifest/preview`, payload)
    return response
  } catch (error) {
    console.error('Preview GitLab project manifest API error:', error)
    throw error
  }
}

export const updateGitLabProjectSettings = async (projectId, payload) => {
  try {
    const response = await apiClient.put(`/gitlab/projects/${projectId}/settings`, payload)
    return response
  } catch (error) {
    console.error('Update GitLab project settings API error:', error)
    throw error
  }
}

export const syncGitLabProjects = async () => {
  try {
    const response = await apiClient.post('/gitlab/projects/sync')
    return response
  } catch (error) {
    console.error('Sync GitLab projects API error:', error)
    throw error
  }
}

// 다음 사용 가능한 IP 조회 API
export const getNextAvailableIp = async () => {
  try {
    const response = await apiClient.get('/network/ip-pool/next')
    return response
  } catch (error) {
    console.error('Get Next Available IP API error:', error)
    throw error
  }
}

// 특정 IP 사용 가능 여부 확인 API
export const checkIpAvailability = async (ip) => {
  try {
    const response = await apiClient.get(`/network/ip-pool/check/${ip}`)
    return response
  } catch (error) {
    console.error('Check IP Availability API error:', error)
    throw error
  }
}

export default apiClient
