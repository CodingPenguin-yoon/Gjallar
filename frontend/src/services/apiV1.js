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
  clusterSummary: '/cluster/summary',
  nodes: '/nodes',
  vms: '/vms',
  vm: (vmid) => `/vms/${encodePathPart(vmid)}`,
  vmStart: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/actions/start`,
  postCreateReadinessEvidence: (nodeId, vmid) => `/nodes/${encodePathPart(nodeId)}/vms/${encodePathPart(vmid)}/post-create-readiness-evidence`,
  profiles: '/profiles',
  templates: '/templates',
  storage: '/storage',
  networks: '/networks',
  jobs: '/jobs',
  job: (jobId) => `/jobs/${encodePathPart(jobId)}`,
  jobArtifacts: (jobId) => `/jobs/${encodePathPart(jobId)}/artifacts`,
  risks: '/risks',
  drsSummary: '/drs/summary',
  drsRecommendations: '/drs/recommendations',
  drsRecommendation: (recommendationId) => `/drs/recommendations/${encodePathPart(recommendationId)}`,
  drsRecommendationCheck: (recommendationId) => `/drs/recommendations/${encodePathPart(recommendationId)}/check`,
  drsRecommendationApprovalPackets: (recommendationId) => `/drs/recommendations/${encodePathPart(recommendationId)}/approval-packets`,
  drsPolicies: '/drs/policies',
  drsPolicy: (vmIdentityId) => `/drs/policies/${encodePathPart(vmIdentityId)}`,
  drsMigrationJobReconcilePreview: (jobId) => `/drs/migration-jobs/${encodePathPart(jobId)}/reconcile-preview`,
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

export function unwrapApiV1Envelope(envelope) {
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
  return envelope.data
}

async function requestJson({ baseUrl, fetchImpl, path, method = 'GET', body }) {
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
  return unwrapApiV1Envelope(envelope)
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
  const post = (path, body = {}) => requestJson({ ...clientConfig, path, method: 'POST', body })
  const put = (path, body = {}) => requestJson({ ...clientConfig, path, method: 'PUT', body })
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
    clusterSummary: () => get(API_V1_ENDPOINTS.clusterSummary),
    listNodes: () => get(API_V1_ENDPOINTS.nodes),
    listVms: () => get(API_V1_ENDPOINTS.vms),
    getVm: (vmid) => get(API_V1_ENDPOINTS.vm(vmid)),
    startVm: (nodeId, vmid, payload = {}) => post(API_V1_ENDPOINTS.vmStart(nodeId, vmid), payload),
    recordPostCreateReadinessEvidence: (nodeId, vmid, payload = {}) => post(API_V1_ENDPOINTS.postCreateReadinessEvidence(nodeId, vmid), payload),
    listProfiles: () => get(API_V1_ENDPOINTS.profiles),
    listTemplates: () => get(API_V1_ENDPOINTS.templates),
    listStorage: () => get(API_V1_ENDPOINTS.storage),
    listNetworks: () => get(API_V1_ENDPOINTS.networks),
    listJobs: () => get(API_V1_ENDPOINTS.jobs),
    getJob: (jobId) => get(API_V1_ENDPOINTS.job(jobId)),
    listJobArtifacts: (jobId) => get(API_V1_ENDPOINTS.jobArtifacts(jobId)),
    listRisks: () => get(API_V1_ENDPOINTS.risks),
    getDrsSummary: () => get(API_V1_ENDPOINTS.drsSummary),
    listDrsRecommendations: () => get(API_V1_ENDPOINTS.drsRecommendations),
    getDrsRecommendation: (recommendationId) => get(API_V1_ENDPOINTS.drsRecommendation(recommendationId)),
    checkDrsRecommendation: (recommendationId, payload = {}) => post(API_V1_ENDPOINTS.drsRecommendationCheck(recommendationId), payload),
    createDrsApprovalPacket: (recommendationId, payload = {}) => post(API_V1_ENDPOINTS.drsRecommendationApprovalPackets(recommendationId), payload),
    drsPolicies: () => get(API_V1_ENDPOINTS.drsPolicies),
    drsPolicy: (vmIdentityId) => get(API_V1_ENDPOINTS.drsPolicy(vmIdentityId)),
    updateDrsPolicy: (vmIdentityId, payload = {}) => put(API_V1_ENDPOINTS.drsPolicy(vmIdentityId), payload),
    reconcilePreviewDrsMigrationJob: (jobId, payload = {}) => post(API_V1_ENDPOINTS.drsMigrationJobReconcilePreview(jobId), payload),
    createVmDraft: (payload = {}) => post(API_V1_ENDPOINTS.createVmDrafts, payload),
    preflightVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreatePreflight(draftId), payload),
    planVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreatePlan(draftId), payload),
    approveVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreateApprove(draftId), payload),
    previewVmDraftProxmox: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreateProxmoxPreview(draftId), payload),
    createVmDraftProxmox: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreateProxmoxCreate(draftId), payload),
  })
}

export const apiV1Client = createApiV1Client()
