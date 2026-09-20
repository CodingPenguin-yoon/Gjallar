export const API_V1_BASE_URL = '/api/v1'

export const API_V1_ENDPOINTS = Object.freeze({
  authLogin: '/auth/login',
  authLogout: '/auth/logout',
  authMe: '/auth/me',
  authChangePassword: '/auth/change-password',
  adminUsers: '/admin/users',
  adminUserRole: (username) => `/admin/users/${encodePathPart(username)}/role`,
  adminUserDisable: (username) => `/admin/users/${encodePathPart(username)}/disable`,
  adminUserResetPassword: (username) => `/admin/users/${encodePathPart(username)}/reset-password`,
  adminSessions: '/admin/sessions',
  adminSessionRevoke: (sessionId) => `/admin/sessions/${encodePathPart(sessionId)}/revoke`,
  proxmoxConnection: '/setup/proxmox/connection',
  proxmoxRegistrations: '/setup/proxmox/registrations',
  proxmoxRegistration: (id) => `/setup/proxmox/registrations/${encodePathPart(id)}`,
  proxmoxRegistrationAction: (id, action) => `/setup/proxmox/registrations/${encodePathPart(id)}/${encodePathPart(action)}`,
  clusterSummary: '/cluster/summary',
  nodes: '/nodes',
  hostNetworkReview: (node, bridge) => `/nodes/${encodePathPart(node)}/host-network/${encodePathPart(bridge)}/review`,
  hostNetworkConfigure: (node, bridge) => `/nodes/${encodePathPart(node)}/host-network/${encodePathPart(bridge)}/actions/configure`,
  hostStorageReview: (node, storage) => `/nodes/${encodePathPart(node)}/host-storage/${encodePathPart(storage)}/review`,
  hostStorageConfigure: (node, storage) => `/nodes/${encodePathPart(node)}/host-storage/${encodePathPart(storage)}/actions/configure`,
  vms: '/vms',
  vm: (vmid) => `/vms/${encodePathPart(vmid)}`,
  vmStart: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/start`,
  vmShutdown: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/shutdown`,
  cloudImages: '/templates/cloud-images',
  imageCleanup: (nodeId, vmid, parentOperationId, resource) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/image-cleanup?${new URLSearchParams({parent_operation_id: parentOperationId, resource})}`,
  imageCleanupAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/image-cleanup`,
  imageBuild: (nodeId, vmid, configuration) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/image-build?${new URLSearchParams(configuration)}`,
  imageBuildAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/image-build`,
  vmBackups: (node, vmid, storage) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/backups?${new URLSearchParams({storage})}`,
  vmBackupReview: (node, vmid, storage) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/backup-review?${new URLSearchParams({storage})}`,
  vmMigrateReview: (node, vmid, destination) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/migrate?${new URLSearchParams({destination_node: destination})}`,
  vmMigrateAction: (node, vmid) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/actions/migrate`,
  vmRestoreReview: (node, vmid, query) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/restore-review?${new URLSearchParams(query)}`,
  vmRestoreAction: (node, vmid) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/actions/restore`,
  vmRestoreReport: (operationId) => `/operations/${encodePathPart(operationId)}/restore-report`,
  vmBackupAction: (node, vmid) => `/nodes/${encodePathPart(node)}/vms/${encodePathPart(vmid)}/actions/backup`,
  vmTemplate: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/template-conversion`,
  vmTemplateAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/template`,
  vmConsole: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/console`,
  vmConsoleSocket: (nodeId, vmid) => `/api/v1/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/console/socket`,
  vmDeletion: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/deletion`,
  vmDeleteAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/delete`,
  vmClone: (nodeId, vmid, newVmid, storageId) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/clone?${new URLSearchParams({new_vmid: newVmid, storage_id: storageId})}`,
  vmCloneAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/clone`,
  vmNetwork: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/network`,
  vmNetworkAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/network`,
  vmCompute: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/compute`,
  vmComputeAction: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/compute`,
  vmDisk: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/disks/scsi0`,
  vmDiskResize: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/disk-resize`,
  postCreateReadinessEvidence: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/post-create-readiness-evidence`,
  profiles: '/profiles',
  templates: '/templates',
  storage: '/storage',
  networks: '/networks',
  jobs: '/jobs',
  job: (jobId) => `/jobs/${encodePathPart(jobId)}`,
  jobArtifacts: (jobId) => `/jobs/${encodePathPart(jobId)}/artifacts`,
  risks: '/risks',
  insights: '/insights',
  nodeMaintenance: (node, query) => `/maintenance/nodes/${encodePathPart(node)}?${new URLSearchParams(query)}`,
  operationAlerts: (limit) => `/monitoring/operation-alerts?${new URLSearchParams({limit})}`,
  metrics: (kind, node, resource, timeframe) => {
    const base = `/monitoring/nodes/${encodePathPart(node)}`
    const suffix = kind === 'node' ? '' : kind === 'vm' ? `/vms/${encodePathPart(resource)}` : kind === 'storage' ? `/storage/${encodePathPart(resource)}` : null
    if (suffix === null) throw new Error('지원하지 않는 지표 대상입니다.')
    return `${base}${suffix}?${new URLSearchParams({timeframe})}`
  },
  operations: '/operations',
  operation: (operationId) => `/operations/${encodePathPart(operationId)}`,
  templateTest: (operationId) => `/operations/${encodePathPart(operationId)}/template-test`,
  operationRecoveryObservation: (operationId) => `/operations/${encodePathPart(operationId)}/recovery/observe`,
  guidedQmVmUnlock: '/operations/guided-qm/vm-unlock',
  operationAttestation: (operationId) => `/operations/${encodePathPart(operationId)}/operator-attestation`,
  operationVerification: (operationId) => `/operations/${encodePathPart(operationId)}/verification`,
  suggestedVmId: '/vm-create/suggested-vmid',
  createVmDrafts: '/vm-create/drafts',
  vmCreatePreflight: (draftId) => `/vm-create/${encodePathPart(draftId)}/preflight`,
  vmCreatePlan: (draftId) => `/vm-create/${encodePathPart(draftId)}/plan`,
  vmCreateApprove: (draftId) => `/vm-create/${encodePathPart(draftId)}/approve`,
  vmCreateProxmoxPreview: (draftId) => `/vm-create/${encodePathPart(draftId)}/proxmox-preview`,
  vmCreateProxmoxCreate: (draftId) => `/vm-create/${encodePathPart(draftId)}/proxmox-create`,
})

function encodePathPart(value) {
  return encodeURIComponent(String(value))
}

function normalizeBaseUrl(baseUrl = API_V1_BASE_URL) {
  const normalized = String(baseUrl || API_V1_BASE_URL).replace(/\/+$/, '')
  return normalized || API_V1_BASE_URL
}

function buildUrl(baseUrl, path) {
  return `${normalizeBaseUrl(baseUrl)}${path}`
}

function withQuery(path, params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

function defaultFetchImpl() {
  if (typeof globalThis.fetch !== 'function') {
    throw new Error('No fetch implementation is available for the /api/v1 client')
  }
  return globalThis.fetch.bind(globalThis)
}

function firstCommandError(detail) {
  const results = [
    ...(Array.isArray(detail?.proxmox_create?.task?.polls) ? detail.proxmox_create.task.polls : []),
  ]
  const text = results.map((item) => item?.stderr || item?.stdout || '').find(Boolean) || ''
  return String(text).replace(/\u001b\[[0-9;]*m/g, '').trim()
}

function validateApiV1Envelope(envelope) {
  if (!envelope || typeof envelope !== 'object' || typeof envelope.ok !== 'boolean') {
    throw new Error('Malformed /api/v1 response envelope: missing ok boolean')
  }
  if (!envelope.ok) {
    const error = envelope.error && typeof envelope.error === 'object' ? envelope.error : {}
    const message = error.message || error.code || 'API v1 request failed'
    const wrapped = new Error(message)
    wrapped.code = error.code || 'api_v1_error'
    wrapped.details = error.details
    throw wrapped
  }
  return envelope
}

export function unwrapApiV1Envelope(envelope) {
  return validateApiV1Envelope(envelope).data
}

export function unwrapApiV1EnvelopeWithMeta(envelope) {
  const validated = validateApiV1Envelope(envelope)
  const meta = validated.meta && typeof validated.meta === 'object' && !Array.isArray(validated.meta)
    ? validated.meta
    : {}
  return { data: validated.data, meta }
}

async function requestJson({ baseUrl, fetchImpl, path, method = 'GET', body, includeMeta = false }) {
  const options = { method, credentials: 'include', headers: { Accept: 'application/json' } }
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  const response = await fetchImpl(buildUrl(baseUrl, path), options)
  const { envelope, rawText } = await readResponsePayload(response)
  if (!response.ok) {
    const detail = envelope?.detail && typeof envelope.detail === 'object' ? envelope.detail : null
    const errorBody = envelope?.error && typeof envelope.error === 'object' ? envelope.error : null
    const commandError = firstCommandError(detail)
    const rawMessage = rawText ? rawText.slice(0, 700) : ''
    const baseMessage = detail?.message || errorBody?.message || detail?.code || errorBody?.code || `API v1 request failed with status ${response.status}`
    const message = commandError ? `${baseMessage}: ${commandError.slice(0, 700)}` : baseMessage
    const nextMessage = rawMessage && !commandError ? `${message}: ${rawMessage}` : message
    const error = new Error(nextMessage)
    error.status = response.status
    error.authRequired = response.status === 401
    error.forbidden = response.status === 403
    error.code = detail?.code || errorBody?.code
    error.details = detail || errorBody || envelope || rawText
    error.envelope = envelope
    throw error
  }
  return includeMeta ? unwrapApiV1EnvelopeWithMeta(envelope) : unwrapApiV1Envelope(envelope)
}

async function readResponsePayload(response) {
  if (typeof response.text === 'function') {
    const rawText = await response.text()
    if (!rawText) return { envelope: null, rawText: '' }
    try {
      return { envelope: JSON.parse(rawText), rawText: '' }
    } catch {
      return { envelope: null, rawText }
    }
  }
  return { envelope: await response.json(), rawText: '' }
}

export function createApiV1Client({ baseUrl = API_V1_BASE_URL, fetchImpl = defaultFetchImpl() } = {}) {
  const clientConfig = { baseUrl: normalizeBaseUrl(baseUrl), fetchImpl }
  const get = (path) => requestJson({ ...clientConfig, path })
  const getWithMeta = (path) => requestJson({ ...clientConfig, path, includeMeta: true })
  const post = (path, body = {}) => requestJson({ ...clientConfig, path, method: 'POST', body })
  const patch = (path, body = {}) => requestJson({ ...clientConfig, path, method: 'PATCH', body })

  return Object.freeze({
    login: (username, password) => post(API_V1_ENDPOINTS.authLogin, { username, password }),
    logout: () => post(API_V1_ENDPOINTS.authLogout, {}),
    me: () => get(API_V1_ENDPOINTS.authMe),
    changePassword: (currentPassword, newPassword) => post(API_V1_ENDPOINTS.authChangePassword, { current_password: currentPassword, new_password: newPassword }),
    listAdminUsers: () => get(API_V1_ENDPOINTS.adminUsers),
    createAdminUser: (payload = {}) => post(API_V1_ENDPOINTS.adminUsers, payload),
    setAdminUserRole: (username, role) => patch(API_V1_ENDPOINTS.adminUserRole(username), { role }),
    disableAdminUser: (username) => post(API_V1_ENDPOINTS.adminUserDisable(username), {}),
    resetAdminUserPassword: (username, password) => post(API_V1_ENDPOINTS.adminUserResetPassword(username), { password }),
    listAdminSessions: () => get(API_V1_ENDPOINTS.adminSessions),
    revokeAdminSession: (sessionId) => post(API_V1_ENDPOINTS.adminSessionRevoke(sessionId), {}),
    proxmoxConnection: () => get(API_V1_ENDPOINTS.proxmoxConnection),
    prepareProxmoxRegistration: (payload) => post(API_V1_ENDPOINTS.proxmoxRegistrations, payload),
    listProxmoxRegistrations: () => get(API_V1_ENDPOINTS.proxmoxRegistrations),
    getProxmoxRegistration: (id) => get(API_V1_ENDPOINTS.proxmoxRegistration(id)),
    actProxmoxRegistration: (id, action, payload) => post(API_V1_ENDPOINTS.proxmoxRegistrationAction(id, action), payload),
    clusterSummary: () => get(API_V1_ENDPOINTS.clusterSummary),
    clusterSummaryWithMeta: () => getWithMeta(API_V1_ENDPOINTS.clusterSummary),
    listNodes: () => get(API_V1_ENDPOINTS.nodes),
    reviewHostNetwork: (node, bridge, payload) => post(API_V1_ENDPOINTS.hostNetworkReview(node, bridge), payload),
    configureHostNetwork: (node, bridge, payload) => post(API_V1_ENDPOINTS.hostNetworkConfigure(node, bridge), payload),
    reviewHostStorage: (node, storage, payload) => post(API_V1_ENDPOINTS.hostStorageReview(node, storage), payload),
    configureHostStorage: (node, storage, payload) => post(API_V1_ENDPOINTS.hostStorageConfigure(node, storage), payload),
    listNodesWithMeta: () => getWithMeta(API_V1_ENDPOINTS.nodes),
    listVms: () => get(API_V1_ENDPOINTS.vms),
    listVmsWithMeta: () => getWithMeta(API_V1_ENDPOINTS.vms),
    getVm: (vmid) => get(API_V1_ENDPOINTS.vm(vmid)),
    getVmWithMeta: (vmid) => getWithMeta(API_V1_ENDPOINTS.vm(vmid)),
    startVm: (nodeId, vmid, payload = {}) => post(API_V1_ENDPOINTS.vmStart(nodeId, vmid), payload),
    shutdownVm: (nodeId, vmid, payload = {}) => post(API_V1_ENDPOINTS.vmShutdown(nodeId, vmid), payload),
    getVmClone: (nodeId, vmid, newVmid, storageId) => get(API_V1_ENDPOINTS.vmClone(nodeId, vmid, newVmid, storageId)),
    getVmConsole: (nodeId, vmid) => get(API_V1_ENDPOINTS.vmConsole(nodeId, vmid)),
    getVmDeletion: (nodeId, vmid) => get(API_V1_ENDPOINTS.vmDeletion(nodeId, vmid)),
    reviewImageCleanup: (nodeId, vmid, parentOperationId, resource) => get(API_V1_ENDPOINTS.imageCleanup(nodeId, vmid, parentOperationId, resource)),
    cleanupImageResource: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.imageCleanupAction(nodeId, vmid), payload),
    listCloudImages: () => get(API_V1_ENDPOINTS.cloudImages),
    reviewImageBuild: (nodeId, vmid, configuration) => get(API_V1_ENDPOINTS.imageBuild(nodeId, vmid, configuration)),
    buildImageTemplate: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.imageBuildAction(nodeId, vmid), payload),
    listVmBackups: (node, vmid, storage) => get(API_V1_ENDPOINTS.vmBackups(node, vmid, storage)),
    reviewVmBackup: (node, vmid, storage) => get(API_V1_ENDPOINTS.vmBackupReview(node, vmid, storage)),
    reviewVmMigration: (node, vmid, destination) => get(API_V1_ENDPOINTS.vmMigrateReview(node, vmid, destination)),
    migrateVm: (node, vmid, payload) => post(API_V1_ENDPOINTS.vmMigrateAction(node, vmid), payload),
    reviewVmRestore: (node, vmid, query) => get(API_V1_ENDPOINTS.vmRestoreReview(node, vmid, query)),
    restoreVmBackup: (node, vmid, payload) => post(API_V1_ENDPOINTS.vmRestoreAction(node, vmid), payload),
    getRestoreReport: operationId => get(API_V1_ENDPOINTS.vmRestoreReport(operationId)),
    createVmBackup: (node, vmid, payload) => post(API_V1_ENDPOINTS.vmBackupAction(node, vmid), payload),
    getVmTemplateConversion: (nodeId, vmid) => get(API_V1_ENDPOINTS.vmTemplate(nodeId, vmid)),
    convertVmToTemplate: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.vmTemplateAction(nodeId, vmid), payload),
    deleteVm: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.vmDeleteAction(nodeId, vmid), payload),
    cloneVm: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.vmCloneAction(nodeId, vmid), payload),
    getVmNetwork: (nodeId, vmid) => get(API_V1_ENDPOINTS.vmNetwork(nodeId, vmid)),
    setVmNetwork: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.vmNetworkAction(nodeId, vmid), payload),
    getVmCompute: (nodeId, vmid) => get(API_V1_ENDPOINTS.vmCompute(nodeId, vmid)),
    setVmCompute: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.vmComputeAction(nodeId, vmid), payload),
    getVmDisk: (nodeId, vmid) => get(API_V1_ENDPOINTS.vmDisk(nodeId, vmid)),
    resizeVmDisk: (nodeId, vmid, payload) => post(API_V1_ENDPOINTS.vmDiskResize(nodeId, vmid), payload),
    recordPostCreateReadinessEvidence: (nodeId, vmid, payload = {}) => post(API_V1_ENDPOINTS.postCreateReadinessEvidence(nodeId, vmid), payload),
    suggestVmId: () => get(API_V1_ENDPOINTS.suggestedVmId),
    listProfiles: () => get(API_V1_ENDPOINTS.profiles),
    listTemplates: () => get(API_V1_ENDPOINTS.templates),
    listStorage: () => get(API_V1_ENDPOINTS.storage),
    listStorageWithMeta: () => getWithMeta(API_V1_ENDPOINTS.storage),
    listNetworks: () => get(API_V1_ENDPOINTS.networks),
    listNetworksWithMeta: () => getWithMeta(API_V1_ENDPOINTS.networks),
    listJobs: () => get(API_V1_ENDPOINTS.jobs),
    getJob: (jobId) => get(API_V1_ENDPOINTS.job(jobId)),
    listJobArtifacts: (jobId) => get(API_V1_ENDPOINTS.jobArtifacts(jobId)),
    listRisks: () => get(API_V1_ENDPOINTS.risks),
    getInsights: () => get(API_V1_ENDPOINTS.insights),
    listOperations: (filters = {}) => get(withQuery(API_V1_ENDPOINTS.operations, filters)),
    getOperation: (operationId) => get(API_V1_ENDPOINTS.operation(operationId)),
    getTemplateTest: (operationId) => get(API_V1_ENDPOINTS.templateTest(operationId)),
    getNodeMaintenance: (node, query) => get(API_V1_ENDPOINTS.nodeMaintenance(node, query)),
    getOperationAlerts: (limit = 20) => get(API_V1_ENDPOINTS.operationAlerts(limit)),
    getMetrics: (kind, node, resource, timeframe = 'hour') => get(API_V1_ENDPOINTS.metrics(kind, node, resource, timeframe)),
    observeOperationRecovery: (operationId, payload = {}) => post(API_V1_ENDPOINTS.operationRecoveryObservation(operationId), payload),
    planGuidedQmVmUnlock: (payload = {}) => post(API_V1_ENDPOINTS.guidedQmVmUnlock, payload),
    attestOperation: (operationId, payload = {}) => post(API_V1_ENDPOINTS.operationAttestation(operationId), payload),
    verifyOperation: (operationId, payload = {}) => post(API_V1_ENDPOINTS.operationVerification(operationId), payload),
    createVmDraft: (payload = {}) => post(API_V1_ENDPOINTS.createVmDrafts, payload),
    preflightVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreatePreflight(draftId), payload),
    planVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreatePlan(draftId), payload),
    approveVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreateApprove(draftId), payload),
    previewVmDraftProxmox: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreateProxmoxPreview(draftId), payload),
    createVmDraftProxmox: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreateProxmoxCreate(draftId), payload),
  })
}

export const apiV1Client = createApiV1Client()
