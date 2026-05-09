export const API_V1_BASE_URL = '/api/v1'

export const API_V1_ENDPOINTS = Object.freeze({
  clusterSummary: '/cluster/summary',
  nodes: '/nodes',
  vms: '/vms',
  vm: (vmid) => `/vms/${encodePathPart(vmid)}`,
  profiles: '/profiles',
  templates: '/templates',
  storage: '/storage',
  networks: '/networks',
  jobs: '/jobs',
  job: (jobId) => `/jobs/${encodePathPart(jobId)}`,
  jobArtifacts: (jobId) => `/jobs/${encodePathPart(jobId)}/artifacts`,
  risks: '/risks',
  createVmDrafts: '/vm-create/drafts',
  vmCreatePreflight: (draftId) => `/vm-create/${encodePathPart(draftId)}/preflight`,
  vmCreatePlan: (draftId) => `/vm-create/${encodePathPart(draftId)}/plan`,
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
  const options = { method, headers: { Accept: 'application/json' } }
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  const response = await fetchImpl(buildUrl(baseUrl, path), options)
  const envelope = await response.json()
  if (!response.ok) {
    const message = envelope?.error?.message || `API v1 request failed with status ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.envelope = envelope
    throw error
  }
  return unwrapApiV1Envelope(envelope)
}

export function createApiV1Client({ baseUrl = API_V1_BASE_URL, fetchImpl = defaultFetchImpl() } = {}) {
  const clientConfig = { baseUrl: normalizeBaseUrl(baseUrl), fetchImpl }
  const get = (path) => requestJson({ ...clientConfig, path })
  const post = (path, body = {}) => requestJson({ ...clientConfig, path, method: 'POST', body })

  return Object.freeze({
    clusterSummary: () => get(API_V1_ENDPOINTS.clusterSummary),
    listNodes: () => get(API_V1_ENDPOINTS.nodes),
    listVms: () => get(API_V1_ENDPOINTS.vms),
    getVm: (vmid) => get(API_V1_ENDPOINTS.vm(vmid)),
    listProfiles: () => get(API_V1_ENDPOINTS.profiles),
    listTemplates: () => get(API_V1_ENDPOINTS.templates),
    listStorage: () => get(API_V1_ENDPOINTS.storage),
    listNetworks: () => get(API_V1_ENDPOINTS.networks),
    listJobs: () => get(API_V1_ENDPOINTS.jobs),
    getJob: (jobId) => get(API_V1_ENDPOINTS.job(jobId)),
    listJobArtifacts: (jobId) => get(API_V1_ENDPOINTS.jobArtifacts(jobId)),
    listRisks: () => get(API_V1_ENDPOINTS.risks),
    createVmDraft: (payload = {}) => post(API_V1_ENDPOINTS.createVmDrafts, payload),
    preflightVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreatePreflight(draftId), payload),
    planVmDraft: (draftId, payload = {}) => post(API_V1_ENDPOINTS.vmCreatePlan(draftId), payload),
  })
}

export const apiV1Client = createApiV1Client()
