import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import YAML from 'yaml'
import {
  Activity,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Clock3,
  Copy,
  ExternalLink,
  FolderGit2,
  GitBranch,
  LayoutList,
  Radar,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'

import {
  createGitLabProject,
  getGitLabProjectManifest,
  getGitLabProjectSettings,
  getGitLabProjects,
  previewGitLabProjectManifest,
  previewGitLabProjectSettings,
  requestGitLabStagingDeploy,
  syncGitLabProjects,
  updateGitLabProjectManifest,
  updateGitLabProjectSettings,
} from '../services/api'

const rolloutSteps = [
  {
    title: '1. 프로젝트 감지',
    description: 'GitLab 프로젝트를 inventory로 읽어와 배포 대상 후보를 고정합니다.',
    icon: Radar,
  },
  {
    title: '2. 설정 확인',
    description: '프로젝트별 환경, host pool, app port, DB 요구사항을 계약 형태로 저장합니다.',
    icon: FolderGit2,
  },
  {
    title: '3. Deploy Staging',
    description:
      '준비가 끝난 프로젝트만 수동 버튼으로 staging 앱 배포를 시작합니다. 선택된 pool 안에서 포트가 비어 있는 host를 골라 docker-compose 배포와 healthcheck를 수행합니다.',
    icon: GitBranch,
  },
]

const navigationCards = [
  {
    title: 'Task Board',
    description: '현재 배포 작업과 로그 흐름을 확인합니다.',
    path: '/tasks',
    label: 'Task Board 열기',
    icon: Clock3,
  },
  {
    title: 'Instance List',
    description: '이미 배포된 인스턴스 상태와 운영 액션을 확인합니다.',
    path: '/list',
    label: 'Instance List 열기',
    icon: LayoutList,
  },
  {
    title: 'Monitoring',
    description: '노드와 VM 리소스 사용률을 빠르게 점검합니다.',
    path: '/monitoring',
    label: 'Monitoring 열기',
    icon: Activity,
  },
]

const initialCreateForm = {
  name: '',
  path: '',
  description: '',
  visibility: 'private',
  initialize_with_readme: true,
  default_branch: '',
}

const visibilityBadgeClassNames = {
  private: 'border-gray-300 bg-gray-100 text-gray-700',
  internal: 'border-blue-200 bg-blue-50 text-blue-700',
  public: 'border-emerald-200 bg-emerald-50 text-emerald-700',
}

const configurationStatusBadgeClassNames = {
  discovered: 'border-gray-300 bg-gray-100 text-gray-700',
  configured: 'border-blue-200 bg-blue-50 text-blue-700',
  ready_for_bootstrap: 'border-emerald-200 bg-emerald-50 text-emerald-700',
}

const configurationStatusLabels = {
  discovered: 'No contract',
  configured: 'Contract saved',
  ready_for_bootstrap: 'Ready to deploy',
}

const manifestStatusBadgeClassNames = {
  valid: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  missing: 'border-amber-200 bg-amber-50 text-amber-800',
  invalid: 'border-rose-200 bg-rose-50 text-rose-700',
  unchecked: 'border-gray-300 bg-gray-100 text-gray-700',
}

const manifestStatusLabels = {
  valid: 'Valid manifest',
  missing: 'Manifest missing',
  invalid: 'Manifest invalid',
  unchecked: 'Manifest unchecked',
}

const initialSettingsForm = {
  deployment_environment: 'staging',
  deployment_pool_key: '',
  requested_app_port: '',
  database_required: false,
  database_engine: 'postgres',
  database_mode: 'shared-cluster',
  migration_command: '',
  deploy_branch: 'main',
  bootstrap_strategy: 'merge_request',
  notes: '',
}

const initialManifestForm = {
  branch: '',
  content: '',
  commitMessage: '',
}

const initialManifestGuidedForm = {
  name: '',
  runtime: '',
  composeFile: '',
  healthcheckType: 'http',
  healthcheckPath: '/health',
  healthcheckPort: '',
  healthcheckCommand: '',
}

const defaultDeploymentEnvironmentLabels = {
  staging: 'Staging',
  production: 'Production',
}

const bootstrapStrategyLabels = {
  merge_request: 'Merge Request',
  direct_commit: 'Direct commit',
  manual: 'Manual',
}

function normalizeHealthcheckPath(value) {
  const trimmed = String(value || '').trim()
  if (!trimmed) {
    return ''
  }
  return trimmed.startsWith('/') ? trimmed : `/${trimmed}`
}

function normalizeHealthcheckType(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (['http', 'tcp', 'command', 'none'].includes(normalized)) {
    return normalized
  }
  return 'http'
}

function normalizeOptionalPositiveInteger(value) {
  const trimmed = String(value || '').trim()
  if (!trimmed) {
    return null
  }
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null
  }
  return Math.trunc(parsed)
}

function deepCloneManifestObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  return JSON.parse(JSON.stringify(value))
}

function parseManifestYamlObject(content) {
  try {
    const parsed = YAML.parse(String(content || ''))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {}
    }
    return parsed
  } catch (error) {
    return {}
  }
}

function buildProjectManifestName(pathWithNamespace) {
  const normalized = String(pathWithNamespace || '').trim()
  if (!normalized) {
    return 'app'
  }
  const segments = normalized.split('/').filter(Boolean)
  return segments[segments.length - 1] || normalized
}

function buildManifestGuidedFormFromObject({
  manifestObject,
  pathWithNamespace,
}) {
  const deploy = manifestObject?.deploy && typeof manifestObject.deploy === 'object'
    ? manifestObject.deploy
    : {}
  const rawHealthcheck = deploy.healthcheck && typeof deploy.healthcheck === 'object'
    ? deploy.healthcheck
    : null
  const healthcheckType = rawHealthcheck
    ? normalizeHealthcheckType(rawHealthcheck.type)
    : deploy.healthcheck_path
      ? 'http'
      : 'http'
  const healthcheckPort = rawHealthcheck ? normalizeOptionalPositiveInteger(rawHealthcheck.port) : null
  const healthcheckPath =
    healthcheckType === 'http'
      ? String(rawHealthcheck?.path || deploy.healthcheck_path || '/health').trim()
      : '/health'
  const healthcheckCommand =
    healthcheckType === 'command' ? String(rawHealthcheck?.command || '').trim() : ''

  return {
    name: String(manifestObject?.name || buildProjectManifestName(pathWithNamespace)).trim(),
    runtime: String(manifestObject?.runtime || '').trim(),
    composeFile: String(deploy.compose_file || '').trim(),
    healthcheckType,
    healthcheckPath,
    healthcheckPort: healthcheckPort != null ? String(healthcheckPort) : '',
    healthcheckCommand,
  }
}

function buildManifestContentFromGuidedForm({
  baseObject,
  guidedForm,
  settingsForm,
  pathWithNamespace,
}) {
  const nextObject = deepCloneManifestObject(baseObject)
  const normalizedName = String(guidedForm.name || '').trim() || buildProjectManifestName(pathWithNamespace)
  const normalizedRuntime = String(guidedForm.runtime || '').trim() || 'unknown'
  const normalizedComposeFile = String(guidedForm.composeFile || '').trim()
  const normalizedHealthcheckType = normalizeHealthcheckType(guidedForm.healthcheckType)
  const normalizedHealthcheckPath = normalizeHealthcheckPath(guidedForm.healthcheckPath)
  const normalizedHealthcheckPort = normalizeOptionalPositiveInteger(guidedForm.healthcheckPort)
  const normalizedHealthcheckCommand = String(guidedForm.healthcheckCommand || '').trim()
  const requestedAppPort = String(settingsForm.requested_app_port || '').trim()
  const parsedRequestedAppPort = requestedAppPort ? Number(requestedAppPort) : null

  nextObject.name = normalizedName
  nextObject.runtime = normalizedRuntime
  nextObject.deploy =
    nextObject.deploy && typeof nextObject.deploy === 'object' && !Array.isArray(nextObject.deploy)
      ? nextObject.deploy
      : {}
  nextObject.deploy.strategy = 'docker-compose'
  nextObject.deploy.compose_file = normalizedComposeFile
  delete nextObject.deploy.healthcheck_path
  nextObject.deploy.healthcheck = {
    type: normalizedHealthcheckType,
  }
  if (normalizedHealthcheckType === 'http') {
    nextObject.deploy.healthcheck.path = normalizedHealthcheckPath
    if (normalizedHealthcheckPort != null) {
      nextObject.deploy.healthcheck.port = normalizedHealthcheckPort
    } else {
      delete nextObject.deploy.healthcheck.port
    }
    delete nextObject.deploy.healthcheck.command
  } else if (normalizedHealthcheckType === 'tcp') {
    if (normalizedHealthcheckPort != null) {
      nextObject.deploy.healthcheck.port = normalizedHealthcheckPort
    } else {
      delete nextObject.deploy.healthcheck.port
    }
    delete nextObject.deploy.healthcheck.path
    delete nextObject.deploy.healthcheck.command
  } else if (normalizedHealthcheckType === 'command') {
    nextObject.deploy.healthcheck.command = normalizedHealthcheckCommand
    delete nextObject.deploy.healthcheck.path
    delete nextObject.deploy.healthcheck.port
  } else {
    delete nextObject.deploy.healthcheck.path
    delete nextObject.deploy.healthcheck.port
    delete nextObject.deploy.healthcheck.command
  }
  if (Number.isFinite(parsedRequestedAppPort) && parsedRequestedAppPort > 0) {
    nextObject.deploy.app_port = parsedRequestedAppPort
  } else {
    delete nextObject.deploy.app_port
  }

  nextObject.database =
    nextObject.database && typeof nextObject.database === 'object' && !Array.isArray(nextObject.database)
      ? nextObject.database
      : {}
  nextObject.database.required = Boolean(settingsForm.database_required)
  if (settingsForm.database_required) {
    nextObject.database.engine = settingsForm.database_engine || 'postgres'
  } else {
    delete nextObject.database.engine
  }

  nextObject.environments =
    nextObject.environments &&
    typeof nextObject.environments === 'object' &&
    !Array.isArray(nextObject.environments)
      ? nextObject.environments
      : {}
  nextObject.environments.staging =
    nextObject.environments.staging &&
    typeof nextObject.environments.staging === 'object' &&
    !Array.isArray(nextObject.environments.staging)
      ? nextObject.environments.staging
      : {}
  nextObject.environments.staging.enabled = true

  if (settingsForm.deployment_environment === 'production') {
    nextObject.environments.production =
      nextObject.environments.production &&
      typeof nextObject.environments.production === 'object' &&
      !Array.isArray(nextObject.environments.production)
        ? nextObject.environments.production
        : {}
    nextObject.environments.production.enabled = true
  }

  return YAML.stringify(nextObject, {
    lineWidth: 0,
    indent: 2,
  })
}

function getDeploymentEnvironmentLabel(options, selectedKey) {
  const normalized = Array.isArray(options)
    ? options.filter((option) => option && String(option.key || '').trim())
    : []
  const option = normalized.find((item) => item.key === selectedKey)
  return option?.label || defaultDeploymentEnvironmentLabels[selectedKey] || selectedKey || 'Staging'
}

function GitLabWorkspace() {
  const [activeView, setActiveView] = useState('overview')
  const [inventory, setInventory] = useState({
    configured: false,
    can_sync: false,
    default_namespace_path: 'heimdall',
    configuration_error: null,
    projects: [],
    last_sync: null,
  })
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState('')
  const [inventoryNotice, setInventoryNotice] = useState('')
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState(initialCreateForm)
  const [editingSettingsProjectId, setEditingSettingsProjectId] = useState(null)
  const [editingManifestProjectId, setEditingManifestProjectId] = useState(null)
  const [settingsForm, setSettingsForm] = useState(initialSettingsForm)
  const [manifestForm, setManifestForm] = useState(initialManifestForm)
  const [manifestGuidedForm, setManifestGuidedForm] = useState(initialManifestGuidedForm)
  const [manifestSourceObject, setManifestSourceObject] = useState({})
  const [manifestDocument, setManifestDocument] = useState(null)
  const [manifestValidationPreview, setManifestValidationPreview] = useState(null)
  const [settingsEnvironmentOptions, setSettingsEnvironmentOptions] = useState([])
  const [settingsPoolOptions, setSettingsPoolOptions] = useState([])
  const [settingsContractPreview, setSettingsContractPreview] = useState(null)
  const [manifestLoadingProjectId, setManifestLoadingProjectId] = useState(null)
  const [manifestPreviewLoading, setManifestPreviewLoading] = useState(false)
  const [manifestSavingProjectId, setManifestSavingProjectId] = useState(null)
  const [settingsLoadingProjectId, setSettingsLoadingProjectId] = useState(null)
  const [settingsSavingProjectId, setSettingsSavingProjectId] = useState(null)
  const [settingsPreviewLoading, setSettingsPreviewLoading] = useState(false)
  const [settingsError, setSettingsError] = useState('')
  const [manifestError, setManifestError] = useState('')
  const [expandedCloneProjectId, setExpandedCloneProjectId] = useState(null)
  const [copyFeedback, setCopyFeedback] = useState({ projectId: null, field: null, status: '' })
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [deployRequestingProjectId, setDeployRequestingProjectId] = useState(null)
  const [deployFeedback, setDeployFeedback] = useState({
    projectId: null,
    type: '',
    message: '',
    taskId: '',
  })

  const loadInventory = async () => {
    setLoading(true)
    setError('')
    try {
      const projectsResponse = await getGitLabProjects()
      setInventory(projectsResponse.data)
    } catch (apiError) {
      setError(apiError.response?.data?.detail || 'GitLab inventory를 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    setError('')
    try {
      await syncGitLabProjects()
      await loadInventory()
    } catch (apiError) {
      setError(apiError.response?.data?.detail || 'GitLab 수동 동기화에 실패했습니다.')
    } finally {
      setSyncing(false)
    }
  }

  const handleCreateFormChange = (event) => {
    const { name, value, type, checked } = event.target
    setCreateForm((current) => {
      const next = {
        ...current,
        [name]: type === 'checkbox' ? checked : value,
      }
      if (name === 'initialize_with_readme' && !checked) {
        next.default_branch = ''
      }
      return next
    })
  }

  const handleCreateProject = async (event) => {
    event.preventDefault()
    setCreating(true)
    setCreateError('')
    setInventoryNotice('')

    try {
      const payload = {
        name: createForm.name.trim(),
        visibility: createForm.visibility,
        initialize_with_readme: createForm.initialize_with_readme,
      }

      if (createForm.path.trim()) {
        payload.path = createForm.path.trim()
      }
      if (createForm.description.trim()) {
        payload.description = createForm.description.trim()
      }
      if (createForm.default_branch.trim()) {
        payload.default_branch = createForm.default_branch.trim()
      }

      const response = await createGitLabProject(payload)
      await loadInventory()
      setCreateForm(initialCreateForm)
      setShowCreateForm(false)
      const manifestSeedMessage = String(response.data.manifest_seed_message || '').trim()
      setInventoryNotice(
        [
          `프로젝트가 생성되었습니다: ${response.data.project.path_with_namespace}`,
          manifestSeedMessage,
        ]
          .filter(Boolean)
          .join(' '),
      )
    } catch (apiError) {
      setCreateError(apiError.response?.data?.detail || 'GitLab 프로젝트 생성에 실패했습니다.')
    } finally {
      setCreating(false)
    }
  }

  const handleCloneToggle = (projectId) => {
    setExpandedCloneProjectId((current) => (current === projectId ? null : projectId))
  }

  const syncManifestContentFromGuidedForm = ({
    nextGuidedForm,
    baseObjectOverride = null,
    pathWithNamespaceOverride = null,
  }) => {
    const normalizedGuidedForm = nextGuidedForm || manifestGuidedForm
    const nextBaseObject =
      baseObjectOverride ||
      parseManifestYamlObject(manifestForm.content) ||
      manifestSourceObject ||
      {}
    const nextContent = buildManifestContentFromGuidedForm({
      baseObject: nextBaseObject,
      guidedForm: normalizedGuidedForm,
      settingsForm,
      pathWithNamespace:
        pathWithNamespaceOverride || manifestDocument?.path_with_namespace || '',
    })

    setManifestSourceObject(deepCloneManifestObject(nextBaseObject))
    setManifestValidationPreview(null)
    setManifestForm((current) => ({
      ...current,
      content: nextContent,
    }))
  }

  const resetManifestEditor = () => {
    setEditingManifestProjectId(null)
    setManifestError('')
    setManifestForm(initialManifestForm)
    setManifestGuidedForm(initialManifestGuidedForm)
    setManifestSourceObject({})
    setManifestDocument(null)
    setManifestValidationPreview(null)
  }

  const resetSettingsEditor = () => {
    setEditingSettingsProjectId(null)
    setSettingsError('')
    setSettingsForm(initialSettingsForm)
    setSettingsEnvironmentOptions([])
    setSettingsPoolOptions([])
    setSettingsContractPreview(null)
  }

  const handleManifestToggle = async (projectId, ref = null) => {
    if (editingManifestProjectId === projectId && ref === null) {
      resetManifestEditor()
      return
    }

    setManifestLoadingProjectId(projectId)
    setManifestError('')

    try {
      const response = await getGitLabProjectManifest(projectId, ref)
      const document = response.data
      const nextBranch = document.manifest_ref || document.deploy_branch || document.default_branch || 'main'
      const initialContent = document.raw_content || document.draft_content || ''
      const nextSourceObject = parseManifestYamlObject(initialContent)
      const nextGuidedForm = buildManifestGuidedFormFromObject({
        manifestObject: nextSourceObject,
        pathWithNamespace: document.path_with_namespace,
      })
      setManifestDocument(document)
      setManifestSourceObject(nextSourceObject)
      setManifestGuidedForm(nextGuidedForm)
      setManifestValidationPreview(null)
      setManifestForm({
        branch: nextBranch,
        content: initialContent,
        commitMessage: document.manifest_exists
          ? 'Update .heimdall/project.yaml via Heimdall'
          : 'Add .heimdall/project.yaml via Heimdall',
      })
      setEditingManifestProjectId(projectId)
    } catch (apiError) {
      setManifestError(apiError.response?.data?.detail || '프로젝트 manifest를 불러오지 못했습니다.')
      setEditingManifestProjectId(projectId)
      setManifestForm(initialManifestForm)
      setManifestGuidedForm(initialManifestGuidedForm)
      setManifestSourceObject({})
      setManifestDocument(null)
      setManifestValidationPreview(null)
    } finally {
      setManifestLoadingProjectId(null)
    }
  }

  const handleSettingsToggle = async (projectId) => {
    if (editingSettingsProjectId === projectId) {
      resetSettingsEditor()
      if (editingManifestProjectId === projectId) {
        resetManifestEditor()
      }
      return
    }

    setSettingsLoadingProjectId(projectId)
    setSettingsError('')

    try {
      const response = await getGitLabProjectSettings(projectId)
      setSettingsForm({
        deployment_environment: response.data.deployment_environment || 'staging',
        deployment_pool_key: response.data.deployment_pool_key || '',
        requested_app_port: response.data.requested_app_port?.toString() || '',
        database_required: Boolean(response.data.database_required),
        database_engine: response.data.database_engine || 'postgres',
        database_mode: response.data.database_mode || 'shared-cluster',
        migration_command: response.data.migration_command || '',
        deploy_branch: response.data.deploy_branch || 'main',
        bootstrap_strategy: response.data.bootstrap_strategy || 'merge_request',
        notes: response.data.notes || '',
      })
      setSettingsEnvironmentOptions(response.data.deployment_environment_options || [])
      setSettingsPoolOptions(response.data.deployment_pool_options || [])
      setSettingsContractPreview(response.data)
      setEditingSettingsProjectId(projectId)
      void handleManifestToggle(projectId, response.data.deploy_branch || 'main')
    } catch (apiError) {
      setSettingsError(apiError.response?.data?.detail || '프로젝트 설정을 불러오지 못했습니다.')
      setEditingSettingsProjectId(projectId)
      setSettingsForm(initialSettingsForm)
      setSettingsEnvironmentOptions([])
      setSettingsPoolOptions([])
      setSettingsContractPreview(null)
    } finally {
      setSettingsLoadingProjectId(null)
    }
  }

  const handleManifestFormChange = (event) => {
    const { name, value } = event.target
    if (name === 'branch') {
      setManifestValidationPreview(null)
    }
    setManifestForm((current) => ({
      ...current,
      [name]: value,
    }))
  }

  const handleManifestGuidedFormChange = (event) => {
    const { name, value } = event.target
    const nextGuidedForm = {
      ...manifestGuidedForm,
      [name]: value,
    }
    const nextBaseObject = parseManifestYamlObject(manifestForm.content)
    setManifestGuidedForm(nextGuidedForm)
    syncManifestContentFromGuidedForm({
      nextGuidedForm,
      baseObjectOverride: nextBaseObject,
    })
  }

  const handleManifestUseDraft = () => {
    if (!manifestDocument?.draft_content) {
      return
    }
    const nextSourceObject = parseManifestYamlObject(manifestDocument.draft_content)
    const nextGuidedForm = buildManifestGuidedFormFromObject({
      manifestObject: nextSourceObject,
      pathWithNamespace: manifestDocument.path_with_namespace,
    })
    setManifestGuidedForm(nextGuidedForm)
    syncManifestContentFromGuidedForm({
      nextGuidedForm,
      baseObjectOverride: nextSourceObject,
      pathWithNamespaceOverride: manifestDocument.path_with_namespace,
    })
  }

  const handleManifestResetToRepo = () => {
    if (!manifestDocument?.raw_content) {
      return
    }
    const nextSourceObject = parseManifestYamlObject(manifestDocument.raw_content)
    const nextGuidedForm = buildManifestGuidedFormFromObject({
      manifestObject: nextSourceObject,
      pathWithNamespace: manifestDocument.path_with_namespace,
    })
    setManifestGuidedForm(nextGuidedForm)
    syncManifestContentFromGuidedForm({
      nextGuidedForm,
      baseObjectOverride: nextSourceObject,
      pathWithNamespaceOverride: manifestDocument.path_with_namespace,
    })
  }

  const handleManifestReload = async (projectId) => {
    const targetBranch =
      manifestForm.branch.trim() ||
      manifestDocument?.manifest_ref ||
      manifestDocument?.deploy_branch ||
      manifestDocument?.default_branch ||
      'main'
    await handleManifestToggle(projectId, targetBranch)
  }

  const handleValidateManifest = async (projectId) => {
    setManifestPreviewLoading(true)
    setManifestError('')
    try {
      const response = await previewGitLabProjectManifest(projectId, {
        content: manifestForm.content,
      })
      setManifestValidationPreview(response.data)
    } catch (apiError) {
      setManifestError(apiError.response?.data?.detail || '현재 manifest 내용을 검사하지 못했습니다.')
    } finally {
      setManifestPreviewLoading(false)
    }
  }

  const handleSettingsFormChange = (event) => {
    const { name, checked, value, type } = event.target

    setSettingsForm((current) => {
      const next = {
        ...current,
        [name]: type === 'checkbox' ? checked : value,
      }

      if (name === 'deployment_environment') {
        next.deployment_pool_key = ''
      }

      if (name === 'database_required' && !checked) {
        next.database_engine = 'postgres'
        next.database_mode = 'shared-cluster'
        next.migration_command = ''
      }

      return next
    })
  }

  const handleSaveManifest = async (projectId) => {
    setManifestSavingProjectId(projectId)
    setManifestError('')
    setInventoryNotice('')

    try {
      const response = await updateGitLabProjectManifest(projectId, {
        branch: manifestForm.branch.trim(),
        content: manifestForm.content,
        commit_message: manifestForm.commitMessage.trim(),
      })
      const savedContent = response.data.raw_content || manifestForm.content
      const nextSourceObject = parseManifestYamlObject(savedContent)
      const nextGuidedForm = buildManifestGuidedFormFromObject({
        manifestObject: nextSourceObject,
        pathWithNamespace: response.data.path_with_namespace,
      })
      setManifestDocument(response.data)
      setManifestSourceObject(nextSourceObject)
      setManifestGuidedForm(nextGuidedForm)
      setManifestValidationPreview({
        manifest_status: response.data.manifest_status,
        manifest_summary: response.data.manifest_summary,
        manifest_deploy_summary: response.data.manifest_deploy_summary,
        requested_app_port: response.data.requested_app_port,
        effective_app_port: response.data.effective_app_port,
        app_port_source: response.data.app_port_source,
      })
      setManifestForm((current) => ({
        ...current,
        branch: response.data.manifest_ref || current.branch,
        content: savedContent,
        commitMessage: response.data.manifest_exists
          ? 'Update .heimdall/project.yaml via Heimdall'
          : current.commitMessage,
      }))
      await loadInventory()
      setInventoryNotice(response.data.message || '.heimdall/project.yaml 저장이 완료되었습니다.')
    } catch (apiError) {
      setManifestError(apiError.response?.data?.detail || '프로젝트 manifest 저장에 실패했습니다.')
    } finally {
      setManifestSavingProjectId(null)
    }
  }

  const handleSaveSettings = async (projectId) => {
    setSettingsSavingProjectId(projectId)
    setSettingsError('')
    setInventoryNotice('')

    try {
      const response = await updateGitLabProjectSettings(projectId, {
        deployment_environment: settingsForm.deployment_environment,
        deployment_pool_key: settingsForm.deployment_pool_key.trim() || null,
        requested_app_port: settingsForm.requested_app_port.trim()
          ? Number(settingsForm.requested_app_port.trim())
          : null,
        database_required: settingsForm.database_required,
        database_engine: settingsForm.database_engine,
        database_mode: settingsForm.database_mode,
        migration_command: settingsForm.migration_command.trim(),
        deploy_branch: settingsForm.deploy_branch.trim(),
        bootstrap_strategy: settingsForm.bootstrap_strategy,
        notes: settingsForm.notes,
      })
      setSettingsForm({
        deployment_environment: response.data.deployment_environment || 'staging',
        deployment_pool_key: response.data.deployment_pool_key || '',
        requested_app_port: response.data.requested_app_port?.toString() || '',
        database_required: Boolean(response.data.database_required),
        database_engine: response.data.database_engine || 'postgres',
        database_mode: response.data.database_mode || 'shared-cluster',
        migration_command: response.data.migration_command || '',
        deploy_branch: response.data.deploy_branch || 'main',
        bootstrap_strategy: response.data.bootstrap_strategy || 'merge_request',
        notes: response.data.notes || '',
      })
      setSettingsEnvironmentOptions(response.data.deployment_environment_options || [])
      setSettingsPoolOptions(response.data.deployment_pool_options || [])
      setSettingsContractPreview(response.data)
      setEditingSettingsProjectId(projectId)
      await loadInventory()
      setInventoryNotice('프로젝트 설정이 저장되었습니다.')
    } catch (apiError) {
      setSettingsError(apiError.response?.data?.detail || '프로젝트 설정 저장에 실패했습니다.')
    } finally {
      setSettingsSavingProjectId(null)
    }
  }

  const handleCopyCloneUrl = async (projectId, field, value) => {
    if (!value) {
      setCopyFeedback({ projectId, field, status: 'unavailable' })
      return
    }

    try {
      if (!navigator?.clipboard?.writeText) {
        throw new Error('clipboard unavailable')
      }
      await navigator.clipboard.writeText(value)
      setCopyFeedback({ projectId, field, status: 'copied' })
    } catch (copyError) {
      setCopyFeedback({ projectId, field, status: 'failed' })
    }
  }

  const handleRequestStagingDeploy = async (project) => {
    setDeployRequestingProjectId(project.gitlab_project_id)
    setDeployFeedback({ projectId: null, type: '', message: '', taskId: '' })
    setInventoryNotice('')

    try {
      const response = await requestGitLabStagingDeploy(project.gitlab_project_id)
      const { already_exists: alreadyExists, message, task_id: taskId } = response.data
      setDeployFeedback({
        projectId: project.gitlab_project_id,
        type: alreadyExists ? 'info' : 'success',
        message,
        taskId,
      })
      await loadInventory()
    } catch (apiError) {
      setDeployFeedback({
        projectId: project.gitlab_project_id,
        type: 'error',
        message: apiError.response?.data?.detail || 'Staging deploy 요청 기록에 실패했습니다.',
        taskId: '',
      })
    } finally {
      setDeployRequestingProjectId(null)
    }
  }

  useEffect(() => {
    loadInventory()
  }, [])

  useEffect(() => {
    if (!editingSettingsProjectId) {
      return undefined
    }

    let cancelled = false
    const timeoutId = window.setTimeout(async () => {
      setSettingsPreviewLoading(true)
      try {
        const response = await previewGitLabProjectSettings(editingSettingsProjectId, {
          deployment_environment: settingsForm.deployment_environment,
          deployment_pool_key: settingsForm.deployment_pool_key.trim() || null,
          requested_app_port: settingsForm.requested_app_port.trim()
            ? Number(settingsForm.requested_app_port.trim())
            : null,
        })
        if (cancelled) {
          return
        }
        setSettingsError('')
        setSettingsContractPreview(response.data)
        setSettingsEnvironmentOptions(response.data.deployment_environment_options || [])
        setSettingsPoolOptions(response.data.deployment_pool_options || [])
        if (!settingsForm.deployment_pool_key && response.data.deployment_pool_key) {
          setSettingsForm((current) =>
            current.deployment_pool_key
              ? current
              : {
                  ...current,
                  deployment_pool_key: response.data.deployment_pool_key,
                },
          )
        }
      } catch (apiError) {
        if (!cancelled) {
          setSettingsError(apiError.response?.data?.detail || '환경 계약 preview를 불러오지 못했습니다.')
        }
      } finally {
        if (!cancelled) {
          setSettingsPreviewLoading(false)
        }
      }
    }, 250)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [
    editingSettingsProjectId,
    settingsForm.deployment_environment,
    settingsForm.deployment_pool_key,
    settingsForm.requested_app_port,
  ])

  useEffect(() => {
    if (!editingManifestProjectId || !manifestDocument) {
      return
    }
    const nextContent = buildManifestContentFromGuidedForm({
      baseObject: parseManifestYamlObject(manifestForm.content),
      guidedForm: manifestGuidedForm,
      settingsForm,
      pathWithNamespace: manifestDocument.path_with_namespace,
    })
    if (nextContent === manifestForm.content) {
      return
    }
    setManifestValidationPreview(null)
    setManifestForm((current) => ({
      ...current,
      content: nextContent,
    }))
  }, [
    editingManifestProjectId,
    manifestDocument,
    manifestGuidedForm,
    manifestForm.content,
    settingsForm.requested_app_port,
    settingsForm.database_required,
    settingsForm.database_engine,
    settingsForm.deployment_environment,
  ])

  const projectCount = inventory.projects?.length || 0
  const lastSync = inventory.last_sync
  const statusValue = inventory.configured ? 'Configured' : 'Needs setup'
  const syncValue = lastSync?.status === 'success' ? 'Synced' : lastSync?.status === 'error' ? 'Sync error' : 'Idle'
  const defaultNamespacePath = inventory.default_namespace_path || 'heimdall'
  const setupProjects = inventory.projects || []

  return (
    <div className="mx-auto max-w-[1440px] space-y-8">
      <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 px-8 py-8 xl:px-10">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-stretch">
            <div className="max-w-4xl space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm font-medium text-blue-700">
                <GitBranch className="h-4 w-4" />
                GitLab Workspace
              </div>
              <div className="space-y-2">
                <h2 className="text-3xl font-semibold tracking-tight text-gray-900">
                  GitLab inventory를 platform DB 기준으로 확인합니다
                </h2>
                <p className="text-sm leading-6 text-gray-600">
                  이 탭은 저장된 GitLab 프로젝트 목록을 보여주고, 필요할 때만 수동 동기화를 실행합니다.
                </p>
              </div>
            </div>

            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-5">
              <div className="flex h-full flex-col gap-4">
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-gray-900">수동 동기화</p>
                  <p className="text-sm leading-6 text-gray-600">
                    System Hook이 들어와도 수동 sync를 fallback으로 유지합니다.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleSync}
                  disabled={!inventory.can_sync || syncing}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-3 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                >
                  <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
                  Sync now
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-4 px-8 py-6 md:grid-cols-2 xl:px-10">
          <article className="rounded-xl border border-gray-200 bg-white p-5 border-l-4 border-l-blue-500">
            <p className="text-sm font-medium text-gray-500">GitLab config</p>
            <p className="mt-2 text-xl font-semibold text-gray-900">{statusValue}</p>
            <p className="mt-3 text-sm leading-6 text-gray-600">
              {inventory.configuration_error || 'GitLab base URL validation passed.'}
            </p>
          </article>
          <article className="rounded-xl border border-gray-200 bg-white p-5 border-l-4 border-l-emerald-500">
            <p className="text-sm font-medium text-gray-500">Persisted projects</p>
            <p className="mt-2 text-xl font-semibold text-gray-900">{projectCount}</p>
            <p className="mt-3 text-sm leading-6 text-gray-600">
              Last sync state: {syncValue}
              {lastSync?.updated_at ? ` · ${lastSync.updated_at}` : ''}
            </p>
          </article>
        </div>
      </section>

      {error ? (
        <section className="rounded-2xl border border-rose-200 bg-rose-50 px-6 py-4 text-sm text-rose-700">
          {error}
        </section>
      ) : null}

      <section className="rounded-2xl border border-gray-200 bg-white px-8 shadow-sm xl:px-10">
        <div className="flex flex-col gap-4 border-b border-gray-200 py-5 sm:flex-row sm:items-end sm:justify-between">
          <div
            role="tablist"
            aria-label="GitLab workspace views"
            className="flex w-full items-center gap-2 overflow-x-auto"
          >
            <button
              type="button"
              onClick={() => setActiveView('overview')}
              id="gitlab-workspace-tab-overview"
              role="tab"
              aria-selected={activeView === 'overview'}
              aria-controls="gitlab-workspace-panel-overview"
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeView === 'overview'
                  ? 'text-blue-600 border-blue-600'
                  : 'text-gray-600 border-transparent hover:text-gray-900'
              }`}
            >
              Overview
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveView('project-setup')
                setShowCreateForm(false)
                setCreateError('')
              }}
              id="gitlab-workspace-tab-project-setup"
              role="tab"
              aria-selected={activeView === 'project-setup'}
              aria-controls="gitlab-workspace-panel-project-setup"
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeView === 'project-setup'
                  ? 'text-blue-600 border-blue-600'
                  : 'text-gray-600 border-transparent hover:text-gray-900'
              }`}
            >
              Project Setup
            </button>
          </div>

          <div className="flex shrink-0 items-center gap-3">
            {activeView === 'overview' ? (
              <button
                type="button"
                onClick={() => {
                  setCreateError('')
                  setShowCreateForm((current) => !current)
                }}
                className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400"
              >
                {showCreateForm ? 'Hide create form' : 'Create repo'}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setActiveView('overview')
                  setShowCreateForm(false)
                }}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:border-blue-300 hover:text-blue-700"
              >
                Back to overview
              </button>
            )}
          </div>
        </div>
      </section>

      {inventoryNotice ? (
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 px-6 py-4 text-sm text-emerald-700">
          {inventoryNotice}
        </section>
      ) : null}

      {activeView === 'overview' ? (
        <div
          id="gitlab-workspace-panel-overview"
          role="tabpanel"
          aria-labelledby="gitlab-workspace-tab-overview"
          className="space-y-6"
        >
          <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_380px]">
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-blue-50 p-2">
                  <GitBranch className="h-5 w-5 text-blue-700" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">연결 이후 기본 흐름</h3>
                  <p className="text-sm text-gray-500">첫 inventory slice에서 유지할 운영 기준입니다.</p>
                </div>
              </div>

              <div className="mt-6 space-y-4">
                {rolloutSteps.map(({ title, description, icon: Icon }) => (
                  <div key={title} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex items-start gap-3">
                      <div className="rounded-lg bg-white p-2 shadow-sm">
                        <Icon className="h-4 w-4 text-gray-700" />
                      </div>
                      <div>
                        <h4 className="text-sm font-semibold text-gray-900">{title}</h4>
                        <p className="mt-2 text-sm leading-6 text-gray-600">{description}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm xl:self-start">
              <h3 className="text-lg font-semibold text-gray-900">현재 상태</h3>
              <div className="mt-4 space-y-3 text-sm leading-6 text-gray-600">
                <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                  persisted inventory를 기본으로 노출하고, project 관련 GitLab System Hook이 들어오면 inventory sync만 자동 반영합니다.
                </p>
                <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                  sync 실행과 System Hook 처리에는 GitLab token과 webhook secret이 필요하고, 목록 조회는 DB에 저장된 결과를 그대로 사용합니다.
                </p>
                {!inventory.can_sync ? (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
                    <div className="flex items-start gap-3">
                      <ShieldAlert className="mt-0.5 h-5 w-5 text-amber-600" />
                      <p>수동 동기화를 실행하려면 유효한 `GITLAB_BASE_URL`과 `GITLAB_API_TOKEN`이 필요합니다.</p>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Persisted GitLab Projects</h3>
                <p className="text-sm text-gray-500">레포 목록과 clone 주소를 중심으로 빠르게 확인합니다.</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setCreateError('')
                  setShowCreateForm((current) => !current)
                }}
                className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400"
              >
                {showCreateForm ? 'Hide create form' : 'Create repo'}
              </button>
            </div>

            {showCreateForm ? (
              <div className="mt-6 rounded-2xl border border-blue-100 bg-blue-50/50 p-5">
                <div className="flex items-center gap-4">
                  <div>
                    <h4 className="text-base font-semibold text-gray-900">Create GitLab Project</h4>
                    <p className="text-sm text-gray-500">GitLab UI를 열지 않고 바로 새 저장소를 만듭니다.</p>
                  </div>
                </div>

                <form className="mt-6 space-y-4" onSubmit={handleCreateProject}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-gray-700">Name</span>
                      <input
                        type="text"
                        name="name"
                        value={createForm.name}
                        onChange={handleCreateFormChange}
                        required
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                        placeholder="my-service"
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-gray-700">Path</span>
                      <input
                        type="text"
                        name="path"
                        value={createForm.path}
                        onChange={handleCreateFormChange}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                        placeholder="optional-repo-path"
                      />
                    </label>
                    <div className="space-y-2">
                      <span className="text-sm font-medium text-gray-700">Namespace</span>
                      <div className="rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-700">
                        {defaultNamespacePath}
                      </div>
                    </div>
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-gray-700">Visibility</span>
                      <select
                        name="visibility"
                        value={createForm.visibility}
                        onChange={handleCreateFormChange}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                      >
                        <option value="private">private</option>
                        <option value="internal">internal</option>
                        <option value="public">public</option>
                      </select>
                    </label>
                  </div>

                  <label className="block space-y-2">
                    <span className="text-sm font-medium text-gray-700">Description</span>
                    <textarea
                      name="description"
                      value={createForm.description}
                      onChange={handleCreateFormChange}
                      rows={3}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                      placeholder="optional project description"
                    />
                  </label>

                  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-gray-700">Default branch</span>
                      <input
                        type="text"
                        name="default_branch"
                        value={createForm.default_branch}
                        onChange={handleCreateFormChange}
                        disabled={!createForm.initialize_with_readme}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400 disabled:bg-gray-50 disabled:text-gray-400"
                        placeholder={createForm.initialize_with_readme ? 'main' : 'README initialization required'}
                      />
                    </label>
                    <label className="inline-flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        name="initialize_with_readme"
                        checked={createForm.initialize_with_readme}
                        onChange={handleCreateFormChange}
                        className="h-4 w-4 rounded border-gray-300 text-blue-600"
                      />
                      Initialize with README
                    </label>
                  </div>

                  {createError ? (
                    <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                      {createError}
                    </div>
                  ) : null}

                  <div className="flex items-center justify-between gap-4 border-t border-gray-200 pt-4">
                    <p className="text-sm text-gray-500">
                      새 프로젝트는 고정 namespace `{defaultNamespacePath}` 에 생성됩니다.
                    </p>
                    <button
                      type="submit"
                      disabled={creating || !inventory.can_sync}
                      className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                    >
                      <RefreshCw className={`h-4 w-4 ${creating ? 'animate-spin' : ''}`} />
                      Create project
                    </button>
                  </div>
                </form>
              </div>
            ) : null}

            <div className="mt-6">
              {loading ? (
                <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-600">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  GitLab inventory를 불러오는 중입니다.
                </div>
              ) : projectCount === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-sm text-gray-600">
                  저장된 GitLab 프로젝트가 없습니다. 설정을 확인한 뒤 `Sync now`를 실행하세요.
                </div>
              ) : (
                <div className="space-y-4">
                  {inventory.projects.map((project) => {
                    const isCloneOpen = expandedCloneProjectId === project.gitlab_project_id
                    const configurationStatus = project.configuration_status || 'discovered'
                    const visibilityBadgeClassName =
                      visibilityBadgeClassNames[project.visibility] || visibilityBadgeClassNames.private
                    const configurationBadgeClassName =
                      configurationStatusBadgeClassNames[configurationStatus] ||
                      configurationStatusBadgeClassNames.discovered
                    const configurationLabel =
                      configurationStatusLabels[configurationStatus] || configurationStatusLabels.discovered

                    return (
                      <article
                        key={project.gitlab_project_id}
                        className="rounded-xl border border-gray-200 bg-gray-50 p-4 transition-colors hover:border-blue-200 hover:bg-blue-50/60 md:p-5"
                      >
                        <div className="flex flex-col gap-5 xl:grid xl:grid-cols-[minmax(0,1fr)_220px] xl:items-start">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="truncate text-base font-semibold text-gray-900">{project.path_with_namespace}</p>
                              <span
                                className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${visibilityBadgeClassName}`}
                              >
                                {project.visibility}
                              </span>
                              {project.archived ? (
                                <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700">
                                  archived
                                </span>
                              ) : null}
                              <span
                                className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${configurationBadgeClassName}`}
                              >
                                {configurationLabel}
                              </span>
                            </div>
                            <p className="mt-2 break-all text-sm text-gray-500">{project.http_url_to_repo}</p>

                            <div className="mt-4 grid gap-3 md:grid-cols-2">
                              {[
                                { label: 'Default branch', value: project.default_branch || '-' },
                                { label: 'Last activity', value: project.last_activity_at || '-' },
                              ].map(({ label, value }) => (
                                <div key={label} className="rounded-lg border border-white bg-white px-4 py-3">
                                  <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                    {label}
                                  </p>
                                  <p className="mt-1 break-all text-sm font-medium text-gray-700">
                                    {value}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center gap-2 lg:justify-end xl:flex-col xl:items-stretch">
                            <a
                              href={project.web_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:border-blue-300 hover:text-blue-700 xl:w-full"
                            >
                              Open
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleCloneToggle(project.gitlab_project_id)}
                              aria-expanded={isCloneOpen}
                              className="inline-flex items-center justify-center gap-2 rounded-md border border-blue-300 bg-white px-3 py-2 text-xs font-medium text-blue-700 transition-colors hover:border-blue-400 xl:w-full"
                            >
                              Clone
                              {isCloneOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                            </button>
                          </div>
                        </div>

                        {isCloneOpen ? (
                          <div className="mt-4 rounded-xl border border-gray-200 bg-white p-4">
                            <div className="grid gap-3 md:grid-cols-2">
                              {[
                                { label: 'HTTPS', field: 'http_url_to_repo', value: project.http_url_to_repo },
                                { label: 'SSH', field: 'ssh_url_to_repo', value: project.ssh_url_to_repo },
                              ].map(({ label, field, value }) => {
                                const status =
                                  copyFeedback.projectId === project.gitlab_project_id && copyFeedback.field === field
                                    ? copyFeedback.status
                                    : ''

                                return (
                                  <div key={field} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                                    <div className="flex items-center justify-between gap-3">
                                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p>
                                      <button
                                        type="button"
                                        onClick={() => handleCopyCloneUrl(project.gitlab_project_id, field, value)}
                                        disabled={!value}
                                        className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:border-blue-300 hover:text-blue-700 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                      >
                                        {status === 'copied' ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                                        Copy
                                      </button>
                                    </div>
                                    <p className="mt-2 break-all text-sm text-gray-700">{value || 'Not available yet. Run sync to backfill existing rows.'}</p>
                                    {status === 'copied' ? (
                                      <p className="mt-2 text-xs text-emerald-600">Copied to clipboard.</p>
                                    ) : null}
                                    {status === 'failed' ? (
                                      <p className="mt-2 text-xs text-rose-600">Clipboard copy failed in this browser.</p>
                                    ) : null}
                                    {status === 'unavailable' ? (
                                      <p className="mt-2 text-xs text-gray-500">No clone URL is stored for this protocol yet.</p>
                                    ) : null}
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        ) : null}
                      </article>
                    )
                  })}
                </div>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">운영 화면으로 이동</h3>
                <p className="text-sm text-gray-500">GitLab inventory와 별개로 바로 사용할 수 있는 기존 화면입니다.</p>
              </div>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-3">
              {navigationCards.map(({ title, description, path, label, icon: Icon }) => (
                <article key={title} className="rounded-xl border border-gray-200 bg-gray-50 p-5">
                  <div className="flex items-center gap-3">
                    <div className="rounded-lg bg-white p-2 shadow-sm">
                      <Icon className="h-5 w-5 text-gray-700" />
                    </div>
                    <h4 className="text-sm font-semibold text-gray-900">{title}</h4>
                  </div>
                  <p className="mt-4 text-sm leading-6 text-gray-600">{description}</p>
                  <Link
                    to={path}
                    className="mt-5 inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:border-blue-300 hover:text-blue-700"
                  >
                    {label}
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </article>
              ))}
            </div>
          </section>
        </div>
      ) : (
        <div
          id="gitlab-workspace-panel-project-setup"
          role="tabpanel"
          aria-labelledby="gitlab-workspace-tab-project-setup"
          className="space-y-6"
        >
          <section className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm xl:self-start">
              <h3 className="text-lg font-semibold text-gray-900">Project Setup</h3>
              <div className="mt-4 space-y-3 text-sm leading-6 text-gray-600">
                <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                  이 화면은 repo 안의 `.heimdall/project.yaml`과 플랫폼 DB의 배포 계약을 한 흐름으로 편집합니다. 저장 경로는 분리되지만, 작업 순서는 여기서 같이 진행합니다.
                </p>
                <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                  먼저 `1. 배포 설정`에서 environment·pool·port를 정하고, 그 값을 바탕으로 `2. Manifest 생성`에서 runtime·compose·healthcheck를 채운 뒤, `3. 최종 점검`에서 저장과 `Deploy Staging`까지 이어갑니다.
                </p>
                <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                  host 생성과 registry 등록은 계속 `Create Instance`와 `Instance List`에서 관리합니다. 현재 실제 실행 가능한 환경은 `staging`입니다.
                </p>
              </div>
            </div>

            <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Project setup flow</h3>
                  <p className="text-sm text-gray-500">프로젝트별 manifest와 배포 계약을 같은 카드 안에서 순서대로 편집합니다.</p>
                </div>
                <span className="text-sm text-gray-500">{setupProjects.length} project(s)</span>
              </div>

              <div className="mt-6">
                {loading ? (
                  <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-600">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    프로젝트 설정 대상을 불러오는 중입니다.
                  </div>
                ) : setupProjects.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-sm text-gray-600">
                    설정할 GitLab 프로젝트가 없습니다. 먼저 Overview에서 프로젝트를 동기화하거나 생성하세요.
                  </div>
                ) : (
                  <div className="space-y-4">
                    {setupProjects.map((project) => {
                      const isSettingsOpen = editingSettingsProjectId === project.gitlab_project_id
                      const isManifestOpen = editingManifestProjectId === project.gitlab_project_id
                      const configurationStatus = project.configuration_status || 'discovered'
                      const configurationBadgeClassName =
                        configurationStatusBadgeClassNames[configurationStatus] ||
                        configurationStatusBadgeClassNames.discovered
                      const configurationLabel =
                        configurationStatusLabels[configurationStatus] || configurationStatusLabels.discovered
                      const settingsSummary = project.settings_summary
                      const settingsUpdatedAt = settingsSummary?.updated_at || '-'
                      const deployBranchSummary = settingsSummary?.deploy_branch || 'main'
                      const bootstrapStrategySummary =
                        bootstrapStrategyLabels[settingsSummary?.bootstrap_strategy] || 'Merge Request'
                      const deploymentEnvironmentSummaryLabel = getDeploymentEnvironmentLabel(
                        project.deployment_environment_options,
                        project.deployment_environment || 'staging',
                      )
                      const deploymentPoolSummaryLabel =
                        project.deployment_pool_summary?.label ||
                        (project.deployment_pool_key ? project.deployment_pool_key : 'Not selected')
                      const databaseSummaryLabel =
                        settingsSummary?.database_required
                          ? `${settingsSummary.database_engine || 'postgres'} · ${settingsSummary.database_mode || 'shared-cluster'}`
                          : 'Not required'
                      const manifestDeploySummary = project.manifest_deploy_summary || null
                      const appPortSummaryLabel =
                        project.effective_app_port != null
                          ? `${project.effective_app_port}${project.app_port_source === 'manifest' ? ' (manifest)' : ''}`
                          : 'Not set'
                      const manifestStatus = project.manifest_status || 'unchecked'
                      const manifestLabel =
                        manifestStatusLabels[manifestStatus] || manifestStatusLabels.unchecked
                      const manifestBadgeClassName =
                        manifestStatusBadgeClassNames[manifestStatus] ||
                        manifestStatusBadgeClassNames.unchecked
                      const manifestSummary =
                        project.manifest_summary || 'Manifest validation has not run yet.'
                      const openManifestStatus = isManifestOpen
                        ? manifestValidationPreview?.manifest_status ||
                          manifestDocument?.manifest_status ||
                          manifestStatus
                        : manifestStatus
                      const openManifestLabel =
                        manifestStatusLabels[openManifestStatus] || manifestStatusLabels.unchecked
                      const openManifestBadgeClassName =
                        manifestStatusBadgeClassNames[openManifestStatus] ||
                        manifestStatusBadgeClassNames.unchecked
                      const openManifestSummary = isManifestOpen
                        ? manifestValidationPreview?.manifest_summary ||
                          manifestDocument?.manifest_summary ||
                          manifestSummary
                        : manifestSummary
                      const openManifestDeploySummary = isManifestOpen
                        ? manifestValidationPreview?.manifest_deploy_summary ||
                          manifestDocument?.manifest_deploy_summary ||
                          null
                        : manifestDeploySummary
                      const manifestRefSummary = isManifestOpen
                        ? manifestDocument?.manifest_ref ||
                          settingsSummary?.deploy_branch ||
                          project.default_branch ||
                          '-'
                        : settingsSummary?.deploy_branch || project.default_branch || '-'
                      const manifestFileStateLabel = isManifestOpen
                        ? manifestDocument?.manifest_exists
                          ? 'Present'
                          : 'Missing'
                        : manifestStatus === 'missing'
                          ? 'Missing'
                          : manifestStatus === 'valid' || manifestStatus === 'invalid'
                            ? 'Present'
                            : 'Unknown'
                      const activeEnvironmentOptions = isSettingsOpen
                        ? settingsEnvironmentOptions
                        : project.deployment_environment_options
                      const activePoolOptions = isSettingsOpen
                        ? settingsPoolOptions
                        : []
                      const activeContractPreview = isSettingsOpen ? settingsContractPreview : null
                      const activePoolSummary = isSettingsOpen
                        ? activeContractPreview?.deployment_pool_summary
                        : project.deployment_pool_summary
                      const activeReadinessSummary = isSettingsOpen
                        ? activeContractPreview?.readiness_summary
                        : project.readiness_summary
                      const activePortOptions = isSettingsOpen
                        ? activeContractPreview?.available_port_options || []
                        : []
                      const activePortRangeLabel =
                        (isSettingsOpen
                          ? activeContractPreview?.port_range_summary?.label
                          : null) || '-'
                      const activeSuggestedPort = isSettingsOpen
                        ? activeContractPreview?.suggested_app_port
                        : null
                      const activeEffectivePort = isSettingsOpen
                        ? activeContractPreview?.effective_app_port
                        : project.effective_app_port
                      const activeAppPortSource = isSettingsOpen
                        ? activeContractPreview?.app_port_source
                        : project.app_port_source
                      const readyPoolCount = activePoolOptions.filter(
                        (option) => option?.state === 'available',
                      ).length
                      const blockedPoolCount = activePoolOptions.filter(
                        (option) => option?.state === 'full',
                      ).length
                      const environmentPoolState =
                        activePoolOptions.length === 0
                          ? 'empty'
                          : readyPoolCount > 0
                            ? 'available'
                            : 'full'
                      const environmentPoolSummary =
                        environmentPoolState === 'empty'
                          ? {
                              title: '등록된 host pool 없음',
                              description:
                                '이 환경에는 아직 등록된 staging host pool이 없습니다. 먼저 host를 만들고 registry에 올려야 합니다.',
                              className: 'border border-amber-200 bg-amber-50 text-amber-900',
                            }
                          : environmentPoolState === 'available'
                            ? {
                                title: '배치 가능한 host pool 있음',
                                description: `현재 ${readyPoolCount}개 pool에서 ready host를 사용할 수 있습니다. 이 중 하나를 선택하면 포트 후보도 바로 계산됩니다.`,
                                className: 'border border-emerald-200 bg-emerald-50 text-emerald-800',
                              }
                            : {
                                title: '등록은 되어 있지만 현재 배치 불가',
                                description:
                                  'host pool은 존재하지만 ready host가 없거나 허용 포트 범위가 모두 사용 중입니다. 새 host를 추가하거나 기존 host 상태를 정리해야 합니다.',
                                className: 'border border-rose-200 bg-rose-50 text-rose-800',
                              }
                      const isDeployReady =
                        !project.archived && Boolean(activeReadinessSummary?.can_request_staging_deploy)
                      const primaryBlockingReason =
                        activeReadinessSummary?.blocking_reasons?.[0] ||
                        activeReadinessSummary?.summary ||
                        'Deploy Staging 조건을 확인하세요.'
                      const deployFeedbackForProject =
                        deployFeedback.projectId === project.gitlab_project_id ? deployFeedback : null

                      return (
                        <article
                          key={project.gitlab_project_id}
                          className="rounded-xl border border-gray-200 bg-gray-50 p-5"
                        >
                          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="truncate text-base font-semibold text-gray-900">
                                  {project.path_with_namespace}
                                </p>
                                <span
                                  className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${configurationBadgeClassName}`}
                                >
                                  {configurationLabel}
                                </span>
                              </div>
                              <div className="mt-4 grid gap-3 md:grid-cols-2">
                                {[
                                  { label: 'Environment', value: deploymentEnvironmentSummaryLabel },
                                  { label: 'Pool', value: deploymentPoolSummaryLabel },
                                  { label: 'Manifest', value: manifestLabel },
                                  { label: 'Database', value: databaseSummaryLabel },
                                  { label: 'Deploy branch', value: deployBranchSummary },
                                  { label: 'App port', value: appPortSummaryLabel },
                                  { label: 'Bootstrap', value: bootstrapStrategySummary },
                                  { label: 'Settings updated', value: settingsUpdatedAt },
                                ].map(({ label, value }) => (
                                  <div key={label} className="rounded-lg border border-white bg-white px-4 py-3">
                                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                      {label}
                                    </p>
                                    <p className="mt-1 break-all text-sm font-medium text-gray-700">
                                      {value}
                                    </p>
                                  </div>
                                ))}
                              </div>
                            </div>

                            <button
                              type="button"
                              onClick={() => handleSettingsToggle(project.gitlab_project_id)}
                              disabled={settingsLoadingProjectId === project.gitlab_project_id}
                              className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                            >
                              {settingsLoadingProjectId === project.gitlab_project_id
                                ? 'Loading...'
                                : isSettingsOpen
                                  ? 'Close flow'
                                  : 'Open flow'}
                            </button>
                          </div>

                          {isSettingsOpen ? (
                            <div className="mt-4 rounded-xl border border-gray-200 bg-white p-4">
                              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                <div>
                                  <h4 className="text-sm font-semibold text-gray-900">Project setup flow</h4>
                                  <p className="mt-1 text-sm text-gray-500">
                                    배포 설정을 먼저 정하고, 그 값을 바탕으로 manifest를 생성한 뒤, 최종 점검까지 같은 카드에서 이어서 진행합니다. repo 파일 저장과 platform 설정 저장은 분리되지만 여기서 연속으로 처리합니다.
                                  </p>
                                </div>
                                <span
                                  className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${configurationBadgeClassName}`}
                                >
                                  {configurationLabel}
                                </span>
                              </div>

                              <div className="mt-4 flex flex-col gap-4">
                                <div className="order-8 rounded-lg border border-gray-200 bg-gray-50 p-4">
                                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                    <div>
                                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                                        2. Manifest 생성
                                      </p>
                                      <p className="mt-1 text-sm font-medium text-gray-900">
                                        `.heimdall/project.yaml`
                                      </p>
                                      <p className="mt-1 text-sm text-gray-500">
                                        위에서 정한 배포 설정을 바탕으로 preview를 만들고, 현재 branch의 repo 파일과 비교하면서 검사와 repo 저장까지 처리합니다.
                                      </p>
                                    </div>
                                    <span
                                      className={`inline-flex items-center self-start rounded-full border px-2 py-1 text-[11px] font-semibold ${openManifestBadgeClassName}`}
                                    >
                                      {openManifestLabel}
                                    </span>
                                  </div>

                                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                                    {[
                                      { label: 'Manifest ref', value: manifestRefSummary },
                                      { label: 'File state', value: manifestFileStateLabel },
                                      {
                                        label: 'Compose file',
                                        value:
                                          manifestGuidedForm.composeFile ||
                                          openManifestDeploySummary?.compose_file ||
                                          '-',
                                      },
                                      {
                                        label: 'Healthcheck',
                                        value:
                                          manifestGuidedForm.healthcheckType === 'http'
                                            ? `http ${normalizeHealthcheckPath(manifestGuidedForm.healthcheckPath)}`
                                            : manifestGuidedForm.healthcheckType === 'tcp'
                                              ? `tcp ${manifestGuidedForm.healthcheckPort || 'app port'}`
                                              : manifestGuidedForm.healthcheckType === 'command'
                                                ? manifestGuidedForm.healthcheckCommand || 'command required'
                                                : 'none',
                                      },
                                    ].map(({ label, value }) => (
                                      <div
                                        key={label}
                                        className="rounded-lg border border-white bg-white px-4 py-3"
                                      >
                                        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                          {label}
                                        </p>
                                        <p className="mt-1 break-all text-sm font-medium text-gray-700">
                                          {value}
                                        </p>
                                      </div>
                                    ))}
                                  </div>

                                  <p
                                    className={`mt-4 rounded-lg px-3 py-2 text-sm ${
                                      openManifestStatus === 'valid'
                                        ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                                        : openManifestStatus === 'unchecked'
                                          ? 'border border-gray-200 bg-white text-gray-700'
                                          : 'border border-amber-200 bg-amber-50 text-amber-900'
                                    }`}
                                  >
                                    {openManifestSummary}
                                  </p>

                                  {manifestLoadingProjectId === project.gitlab_project_id && !isManifestOpen ? (
                                    <div className="mt-4 flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
                                      <RefreshCw className="h-4 w-4 animate-spin" />
                                      manifest 내용을 불러오는 중입니다.
                                    </div>
                                  ) : (
                                    <>
                                      {manifestValidationPreview ? (
                                        <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
                                          현재 선택한 배포 설정과 아래 manifest 입력값 기준 검사 결과를 보여주고 있습니다. 아직 저장되지 않은 내용일 수 있습니다.
                                        </div>
                                      ) : null}

                                      <div className="mt-4 grid gap-4 md:grid-cols-2">
                                        <label className="space-y-2">
                                          <span className="text-sm font-medium text-gray-700">Target branch</span>
                                          <input
                                            type="text"
                                            name="branch"
                                            value={manifestForm.branch}
                                            onChange={handleManifestFormChange}
                                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                            placeholder={manifestDocument?.deploy_branch || manifestDocument?.default_branch || 'main'}
                                          />
                                        </label>

                                        <label className="space-y-2">
                                          <span className="text-sm font-medium text-gray-700">Commit message</span>
                                          <input
                                            type="text"
                                            name="commitMessage"
                                            value={manifestForm.commitMessage}
                                            onChange={handleManifestFormChange}
                                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                            placeholder="Add .heimdall/project.yaml via Heimdall"
                                          />
                                        </label>
                                      </div>

                                      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                                        <label className="space-y-2 xl:col-span-2">
                                          <span className="text-sm font-medium text-gray-700">App name</span>
                                          <input
                                            type="text"
                                            name="name"
                                            value={manifestGuidedForm.name}
                                            onChange={handleManifestGuidedFormChange}
                                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                            placeholder={buildProjectManifestName(project.path_with_namespace)}
                                          />
                                        </label>

                                        <label className="space-y-2 xl:col-span-2">
                                          <span className="text-sm font-medium text-gray-700">Runtime</span>
                                          <input
                                            type="text"
                                            name="runtime"
                                            value={manifestGuidedForm.runtime}
                                            onChange={handleManifestGuidedFormChange}
                                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                            placeholder="node, python, go, java"
                                          />
                                        </label>

                                        <label className="space-y-2 xl:col-span-2">
                                          <span className="text-sm font-medium text-gray-700">Compose file</span>
                                          <input
                                            type="text"
                                            name="composeFile"
                                            value={manifestGuidedForm.composeFile}
                                            onChange={handleManifestGuidedFormChange}
                                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                            placeholder="deploy/docker-compose.yml"
                                          />
                                        </label>

                                        <label className="space-y-2 xl:col-span-2">
                                          <span className="text-sm font-medium text-gray-700">Healthcheck type</span>
                                          <select
                                            name="healthcheckType"
                                            value={manifestGuidedForm.healthcheckType}
                                            onChange={handleManifestGuidedFormChange}
                                            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                          >
                                            <option value="http">http</option>
                                            <option value="tcp">tcp</option>
                                            <option value="command">command</option>
                                            <option value="none">none</option>
                                          </select>
                                        </label>

                                        {manifestGuidedForm.healthcheckType === 'http' ? (
                                          <>
                                            <label className="space-y-2 xl:col-span-2">
                                              <span className="text-sm font-medium text-gray-700">HTTP path</span>
                                              <input
                                                type="text"
                                                name="healthcheckPath"
                                                value={manifestGuidedForm.healthcheckPath}
                                                onChange={handleManifestGuidedFormChange}
                                                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                                placeholder="/health"
                                              />
                                            </label>

                                            <label className="space-y-2 xl:col-span-2">
                                              <span className="text-sm font-medium text-gray-700">HTTP port override</span>
                                              <input
                                                type="number"
                                                name="healthcheckPort"
                                                value={manifestGuidedForm.healthcheckPort}
                                                onChange={handleManifestGuidedFormChange}
                                                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                                placeholder="비워두면 app port 사용"
                                              />
                                            </label>
                                          </>
                                        ) : null}

                                        {manifestGuidedForm.healthcheckType === 'tcp' ? (
                                          <label className="space-y-2 xl:col-span-2">
                                            <span className="text-sm font-medium text-gray-700">TCP port override</span>
                                            <input
                                              type="number"
                                              name="healthcheckPort"
                                              value={manifestGuidedForm.healthcheckPort}
                                              onChange={handleManifestGuidedFormChange}
                                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                              placeholder="비워두면 app port 사용"
                                            />
                                          </label>
                                        ) : null}

                                        {manifestGuidedForm.healthcheckType === 'command' ? (
                                          <label className="space-y-2 xl:col-span-2">
                                            <span className="text-sm font-medium text-gray-700">Command</span>
                                            <input
                                              type="text"
                                              name="healthcheckCommand"
                                              value={manifestGuidedForm.healthcheckCommand}
                                              onChange={handleManifestGuidedFormChange}
                                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                              placeholder="docker compose ps"
                                            />
                                          </label>
                                        ) : null}
                                      </div>

                                      <div className="mt-4 rounded-lg border border-white bg-white px-4 py-3 text-sm leading-6 text-gray-600">
                                        위 `1. 배포 설정`에서 고른 port와 DB 여부가 preview YAML에 함께 반영됩니다.
                                        이 단계에서는 runtime, compose file, healthcheck 계약만 채우면 됩니다.
                                      </div>

                                      <div className="mt-4 flex flex-wrap gap-3">
                                        <button
                                          type="button"
                                          onClick={() => handleManifestReload(project.gitlab_project_id)}
                                          disabled={manifestLoadingProjectId === project.gitlab_project_id}
                                          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:border-blue-300 hover:text-blue-700 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                        >
                                          <RefreshCw className={`h-4 w-4 ${manifestLoadingProjectId === project.gitlab_project_id ? 'animate-spin' : ''}`} />
                                          Reload from repo
                                        </button>
                                        <button
                                          type="button"
                                          onClick={handleManifestUseDraft}
                                          className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400"
                                        >
                                          Use starter values
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => handleValidateManifest(project.gitlab_project_id)}
                                          disabled={manifestPreviewLoading}
                                          className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm font-medium text-emerald-700 transition-colors hover:border-emerald-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                        >
                                          <RefreshCw className={`h-4 w-4 ${manifestPreviewLoading ? 'animate-spin' : ''}`} />
                                          Validate preview
                                        </button>
                                        <button
                                          type="button"
                                          onClick={handleManifestResetToRepo}
                                          disabled={!manifestDocument?.raw_content}
                                          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:border-blue-300 hover:text-blue-700 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                        >
                                          Reset to repo values
                                        </button>
                                      </div>

                                      <label className="mt-4 block space-y-2">
                                        <span className="text-sm font-medium text-gray-700">Generated manifest preview</span>
                                        <textarea
                                          name="content"
                                          value={manifestForm.content}
                                          readOnly
                                          rows={16}
                                          className="w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-3 font-mono text-sm text-gray-900 outline-none"
                                          spellCheck={false}
                                          placeholder="# .heimdall/project.yaml"
                                        />
                                      </label>

                                      {manifestError ? (
                                        <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                                          {manifestError}
                                        </div>
                                      ) : null}

                                      <div className="mt-4 flex items-center justify-between gap-4 border-t border-gray-200 pt-4">
                                        <p className="text-sm text-gray-500">
                                          위 배포 설정과 manifest 입력값이 합쳐져 preview YAML로 변환됩니다. invalid면 저장은 되어도 다음 단계 deploy는 계속 막힐 수 있습니다.
                                        </p>
                                        <button
                                          type="button"
                                          onClick={() => handleSaveManifest(project.gitlab_project_id)}
                                          disabled={manifestSavingProjectId === project.gitlab_project_id}
                                          className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                        >
                                          <RefreshCw className={`h-4 w-4 ${manifestSavingProjectId === project.gitlab_project_id ? 'animate-spin' : ''}`} />
                                          {manifestDocument?.manifest_exists ? 'Save manifest' : 'Create manifest'}
                                        </button>
                                      </div>
                                    </>
                                  )}
                                </div>

                                <div className="order-1 rounded-lg border border-gray-200 bg-gray-50 p-4">
                                  <div className="space-y-1">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                                      1. 배포 설정
                                    </p>
                                    <p className="text-sm font-medium text-gray-900">Environment contract</p>
                                    <p className="text-sm text-gray-500">
                                      먼저 어떤 environment와 pool에 어떤 포트로 올릴지 정합니다. 여기서 고른 값이 아래 manifest preview와 최종 deploy에 같이 반영됩니다.
                                    </p>
                                  </div>
                                </div>

                                <div className="order-2 grid gap-4 md:grid-cols-3">
                                  <label className="space-y-2">
                                    <span className="text-sm font-medium text-gray-700">Environment</span>
                                    <select
                                      name="deployment_environment"
                                      value={settingsForm.deployment_environment}
                                      onChange={handleSettingsFormChange}
                                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                    >
                                      {activeEnvironmentOptions.map((option) => (
                                        <option key={option.key} value={option.key}>
                                          {option.label}
                                        </option>
                                      ))}
                                    </select>
                                  </label>

                                  <label className="space-y-2">
                                    <span className="text-sm font-medium text-gray-700">Deploy branch</span>
                                    <input
                                      type="text"
                                      name="deploy_branch"
                                      value={settingsForm.deploy_branch}
                                      onChange={handleSettingsFormChange}
                                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                      placeholder="main"
                                    />
                                  </label>

                                  <label className="space-y-2">
                                    <span className="text-sm font-medium text-gray-700">Bootstrap strategy</span>
                                    <select
                                      name="bootstrap_strategy"
                                      value={settingsForm.bootstrap_strategy}
                                      onChange={handleSettingsFormChange}
                                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                    >
                                      <option value="merge_request">merge_request</option>
                                      <option value="direct_commit">direct_commit</option>
                                      <option value="manual">manual</option>
                                    </select>
                                  </label>
                                </div>

                                <div className="order-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
                                  <div className="space-y-1">
                                    <p className="text-sm font-medium text-gray-900">Host pool</p>
                                    <p className="text-sm text-gray-500">
                                      선택한 환경에 등록된 host pool을 보여주고, 그 안에서 배치 가능한 상태를 계산합니다.
                                    </p>
                                  </div>

                                  <div className={`mt-4 rounded-xl p-4 ${environmentPoolSummary.className}`}>
                                    <p className="text-sm font-semibold">{environmentPoolSummary.title}</p>
                                    <p className="mt-2 text-sm leading-6">{environmentPoolSummary.description}</p>
                                    <div className="mt-3 flex flex-wrap gap-2 text-xs font-medium">
                                      <span className="rounded-full border border-white/80 bg-white/70 px-2.5 py-1">
                                        total pools {activePoolOptions.length}
                                      </span>
                                      <span className="rounded-full border border-white/80 bg-white/70 px-2.5 py-1">
                                        available {readyPoolCount}
                                      </span>
                                      <span className="rounded-full border border-white/80 bg-white/70 px-2.5 py-1">
                                        blocked {blockedPoolCount}
                                      </span>
                                    </div>
                                    {environmentPoolState !== 'available' ? (
                                      <div className="mt-4 flex flex-wrap gap-3">
                                        <Link
                                          to="/create"
                                          className="inline-flex items-center gap-2 rounded-lg border border-white/80 bg-white px-3 py-2 text-sm font-medium"
                                        >
                                          Create Instance
                                          <ArrowRight className="h-4 w-4" />
                                        </Link>
                                        <Link
                                          to="/list"
                                          className="inline-flex items-center gap-2 rounded-lg border border-white/80 bg-white px-3 py-2 text-sm font-medium"
                                        >
                                          Instance List
                                        </Link>
                                      </div>
                                    ) : null}
                                  </div>

                                  {settingsPreviewLoading ? (
                                    <div className="mt-4 flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
                                      <RefreshCw className="h-4 w-4 animate-spin" />
                                      pool / port preview를 갱신하는 중입니다.
                                    </div>
                                  ) : null}

                                  {activePoolOptions.length === 0 ? (
                                    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
                                      <div className="flex items-start gap-3">
                                        <ShieldAlert className="mt-0.5 h-5 w-5 text-amber-700" />
                                        <div className="space-y-2">
                                          <p className="text-sm font-semibold text-amber-900">
                                            선택한 환경에 등록된 host pool이 없습니다
                                          </p>
                                          <p className="text-sm leading-6 text-amber-800">
                                            먼저 `Create Instance`에서 host를 만들고 registry에 등록해야 환경 선택 이후 port 계약을 진행할 수 있습니다.
                                          </p>
                                          <div className="flex flex-wrap gap-3 pt-1">
                                            <Link
                                              to="/create"
                                              className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-800"
                                            >
                                              Create Instance
                                              <ArrowRight className="h-4 w-4" />
                                            </Link>
                                            <Link
                                              to="/list"
                                              className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-100/60 px-3 py-2 text-sm font-medium text-amber-900"
                                            >
                                              Instance List
                                            </Link>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="mt-4 space-y-4">
                                      <label className="space-y-2">
                                        <span className="text-sm font-medium text-gray-700">Pool</span>
                                        <select
                                          name="deployment_pool_key"
                                          value={settingsForm.deployment_pool_key}
                                          onChange={handleSettingsFormChange}
                                          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                        >
                                          <option value="">Pool 선택</option>
                                          {activePoolOptions.map((option) => (
                                            <option key={`${option.environment}:${option.pool_key}`} value={option.pool_key}>
                                              {option.label} · {option.state === 'available' ? 'ready' : 'blocked'} {option.ready_hosts}/{option.total_hosts}
                                            </option>
                                          ))}
                                        </select>
                                      </label>

                                      {activePoolSummary ? (
                                        <div
                                          className={`rounded-xl p-4 ${
                                            activePoolSummary.state === 'available'
                                              ? 'border border-emerald-200 bg-emerald-50'
                                              : activePoolSummary.state === 'full'
                                                ? 'border border-rose-200 bg-rose-50'
                                                : 'border border-gray-200 bg-white'
                                          }`}
                                        >
                                          <div className="space-y-2">
                                            <p className="text-sm font-semibold text-gray-900">
                                              {activePoolSummary.label || settingsForm.deployment_pool_key}
                                            </p>
                                            <p className="text-sm leading-6 text-gray-700">
                                              {activePoolSummary.summary || 'pool 상태를 확인합니다.'}
                                            </p>
                                          </div>

                                          <div className="mt-4 grid gap-3 md:grid-cols-3">
                                            {[
                                              { label: 'Total hosts', value: activePoolSummary.total_hosts ?? '-' },
                                              { label: 'Ready hosts', value: activePoolSummary.ready_hosts ?? '-' },
                                              { label: 'Blocked hosts', value: activePoolSummary.blocked_hosts ?? '-' },
                                            ].map(({ label, value }) => (
                                              <div key={label} className="rounded-lg border border-white bg-white px-4 py-3">
                                                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                                  {label}
                                                </p>
                                                <p className="mt-1 text-sm font-medium text-gray-700">{value}</p>
                                              </div>
                                            ))}
                                          </div>

                                          {activePoolSummary.selected_host ? (
                                            <div className="mt-4 rounded-lg border border-white bg-white px-4 py-3">
                                              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                                Selected host
                                              </p>
                                              <p className="mt-1 text-sm font-medium text-gray-700">
                                                {activePoolSummary.selected_host.name || activePoolSummary.selected_host.node}
                                                {' · '}
                                                {activePoolSummary.selected_host.host_ip}
                                              </p>
                                            </div>
                                          ) : null}
                                        </div>
                                      ) : null}
                                    </div>
                                  )}
                                </div>

                                <div className="order-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
                                  <div className="space-y-1">
                                    <p className="text-sm font-medium text-gray-900">App port</p>
                                    <p className="text-sm text-gray-500">
                                      선택한 environment / pool 기준으로 현재 사용할 수 있는 포트만 보여줍니다. 입력값이 없으면 manifest의 `deploy.app_port`를 fallback으로 사용합니다.
                                    </p>
                                  </div>

                                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                                    <div className="rounded-lg border border-white bg-white px-4 py-3">
                                      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                        Effective port
                                      </p>
                                      <p className="mt-1 text-sm font-medium text-gray-700">
                                        {activeEffectivePort != null
                                          ? `${activeEffectivePort}${activeAppPortSource === 'manifest' ? ' (manifest)' : ''}`
                                          : 'Not set'}
                                      </p>
                                    </div>
                                    <div className="rounded-lg border border-white bg-white px-4 py-3">
                                      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                        Allowed range
                                      </p>
                                      <p className="mt-1 text-sm font-medium text-gray-700">{activePortRangeLabel}</p>
                                    </div>
                                  </div>

                                  <div className="mt-4 grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
                                    <label className="space-y-2">
                                      <span className="text-sm font-medium text-gray-700">Requested port</span>
                                      <input
                                        type="number"
                                        name="requested_app_port"
                                        value={settingsForm.requested_app_port}
                                        onChange={handleSettingsFormChange}
                                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                        placeholder={activeSuggestedPort ? String(activeSuggestedPort) : '3000'}
                                      />
                                    </label>

                                    <div className="space-y-2">
                                      <span className="text-sm font-medium text-gray-700">Available ports</span>
                                      {activePortOptions.length === 0 ? (
                                        <div className="rounded-lg border border-dashed border-gray-300 bg-white px-4 py-3 text-sm text-gray-500">
                                          pool을 먼저 고르거나, 현재 pool 상태를 확인하세요.
                                        </div>
                                      ) : (
                                        <div className="flex flex-wrap gap-2 rounded-lg border border-white bg-white p-3">
                                          {activePortOptions.map((option) => (
                                            <button
                                              key={option.port}
                                              type="button"
                                              onClick={() =>
                                                setSettingsForm((current) => ({
                                                  ...current,
                                                  requested_app_port: String(option.port),
                                                }))
                                              }
                                              className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
                                                String(settingsForm.requested_app_port) === String(option.port)
                                                  ? 'border-blue-400 bg-blue-50 text-blue-700'
                                                  : 'border-gray-300 bg-white text-gray-700 hover:border-blue-300 hover:text-blue-700'
                                              }`}
                                            >
                                              {option.port}
                                              {' '}
                                              <span className="text-xs text-gray-400">+{option.available_host_count}</span>
                                            </button>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>

                                <div className="order-5 rounded-lg border border-gray-200 bg-gray-50 p-4">
                                  <label className="flex items-start gap-3 text-sm text-gray-700">
                                    <input
                                      type="checkbox"
                                      name="database_required"
                                      checked={settingsForm.database_required}
                                      onChange={handleSettingsFormChange}
                                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
                                    />
                                    <span>
                                      <span className="block font-medium text-gray-900">Database required</span>
                                      <span className="mt-1 block text-gray-500">
                                        staging 배포 전에 플랫폼 DB 자동화가 필요한 프로젝트인지 표시합니다.
                                      </span>
                                    </span>
                                  </label>

                                  {settingsForm.database_required ? (
                                    <div className="mt-4 grid gap-4 md:grid-cols-2">
                                      <label className="space-y-2">
                                        <span className="text-sm font-medium text-gray-700">Database engine</span>
                                        <select
                                          name="database_engine"
                                          value={settingsForm.database_engine}
                                          onChange={handleSettingsFormChange}
                                          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                        >
                                          <option value="postgres">postgres</option>
                                        </select>
                                      </label>

                                      <label className="space-y-2">
                                        <span className="text-sm font-medium text-gray-700">Database mode</span>
                                        <select
                                          name="database_mode"
                                          value={settingsForm.database_mode}
                                          onChange={handleSettingsFormChange}
                                          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                        >
                                          <option value="shared-cluster">shared-cluster</option>
                                          <option value="dedicated-instance">dedicated-instance</option>
                                        </select>
                                      </label>

                                      <label className="space-y-2 md:col-span-2">
                                        <span className="text-sm font-medium text-gray-700">Migration command</span>
                                        <input
                                          type="text"
                                          name="migration_command"
                                          value={settingsForm.migration_command}
                                          onChange={handleSettingsFormChange}
                                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                          placeholder="npm run migrate 또는 alembic upgrade head"
                                        />
                                      </label>
                                    </div>
                                  ) : null}
                                </div>

                                <label className="order-6 block space-y-2">
                                  <span className="text-sm font-medium text-gray-700">Notes</span>
                                  <textarea
                                    name="notes"
                                    value={settingsForm.notes}
                                    onChange={handleSettingsFormChange}
                                    rows={3}
                                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-400"
                                    placeholder="환경 계약 저장 전에 남길 메모를 적습니다."
                                  />
                                </label>

                                {settingsError ? (
                                  <div className="order-7 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                                    {settingsError}
                                  </div>
                                ) : null}

                                <div className="order-9 rounded-lg border border-gray-200 bg-gray-50 p-4">
                                  <div className="space-y-1">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                                      3. 최종 점검 / Deploy
                                    </p>
                                    <p className="text-sm font-medium text-gray-900">
                                      저장 후 바로 staging deploy까지 이어갑니다.
                                    </p>
                                    <p className="text-sm text-gray-500">
                                      manifest valid 여부, pool 준비 상태, 포트 가능 여부를 다시 확인한 뒤 `Deploy Staging`을 실행합니다.
                                    </p>
                                  </div>
                                </div>

                                {deployFeedbackForProject ? (
                                  <div
                                    className={`order-10 rounded-xl px-4 py-3 text-sm ${
                                      deployFeedbackForProject.type === 'error'
                                        ? 'border border-rose-200 bg-rose-50 text-rose-700'
                                        : deployFeedbackForProject.type === 'info'
                                          ? 'border border-amber-200 bg-amber-50 text-amber-800'
                                          : 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                                    }`}
                                  >
                                    <p>{deployFeedbackForProject.message}</p>
                                    <p className="mt-2">
                                      Task Board에서 확인:
                                      {' '}
                                      <Link to="/tasks" className="font-medium underline">
                                        /tasks
                                      </Link>
                                      {deployFeedbackForProject.taskId ? ` · task_id: ${deployFeedbackForProject.taskId}` : ''}
                                    </p>
                                  </div>
                                ) : null}

                                <div className="order-11 flex items-center justify-between gap-4 border-t border-gray-200 pt-4">
                                  <p className="text-sm text-gray-500">
                                    현재 `Deploy Staging`은 저장된 environment contract를 다시 검증한 뒤, 선택된 pool 안에서 포트가 비어 있는 host를 골라 앱 배포와 healthcheck까지 수행합니다. DB 자동화는 아직 제외됩니다.
                                  </p>
                                  <div className="flex flex-wrap items-center justify-end gap-3">
                                    <button
                                      type="button"
                                      onClick={() => handleRequestStagingDeploy(project)}
                                      disabled={
                                        !isDeployReady ||
                                        settingsPreviewLoading ||
                                        deployRequestingProjectId === project.gitlab_project_id
                                      }
                                      className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-4 py-2 text-sm font-medium text-emerald-700 transition-colors hover:border-emerald-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                    >
                                      <GitBranch className="h-4 w-4" />
                                      {deployRequestingProjectId === project.gitlab_project_id ? 'Starting...' : 'Deploy Staging'}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleSaveSettings(project.gitlab_project_id)}
                                      disabled={settingsSavingProjectId === project.gitlab_project_id}
                                      className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:border-blue-400 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                                    >
                                      <RefreshCw className={`h-4 w-4 ${settingsSavingProjectId === project.gitlab_project_id ? 'animate-spin' : ''}`} />
                                      Save deployment setup
                                    </button>
                                  </div>
                                </div>
                                {!isDeployReady ? (
                                  <p className="order-12 text-sm text-amber-700">
                                    {primaryBlockingReason}
                                  </p>
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                        </article>
                      )
                    })}
                  </div>
                )}
              </div>
            </section>
          </section>
        </div>
      )}
    </div>
  )
}

export default GitLabWorkspace
