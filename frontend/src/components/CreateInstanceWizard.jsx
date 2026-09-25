import { randomUUID } from '../shared/requestId.js'
import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ClipboardCheck, KeyRound, Loader2, Network, PlayCircle, Rocket, Server, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { apiV1Client } from '../services/apiV1'
import { authFailureMessage } from '../utils/auth'
import { buildCreateVmDefaults, normalizeCreateVmProfiles, resetHardwareForProfile, hardwareFromTemplate } from '../utils/createVmDefaults'
import {
  approveCreateVmReview,
  buildCreateVmInputFromConfig,
  buildStaticIpObservation,
  createVmWithProxmox,
  loadCreateVmReviewModel,
  normalizeTemplateOptions,
  selectPreferredTemplate,
  templateRequirementStatus,
  validateTemplateSelection,
} from '../utils/createVmFlow'

const CHECK_LABELS = {
  profile_schema: '프로필',
  profile_enabled: '프로필 활성화',
  profile_cpu_range: 'CPU 범위',
  profile_memory_mb_range: '메모리 범위',
  profile_disk_gb_range: '디스크 범위',
  access_cloud_init_user_present: '접속 사용자',
  access_password_login_disabled: '비밀번호 로그인',
  access_ssh_key_present: 'SSH 키',
  access_ssh_key_valid: 'SSH 키 형식',
  profile_template_disk_limit: '프로필 디스크',
  template_available: '템플릿',
  template_matches_profile: '템플릿 프로필',
  template_cloud_init_ready: 'Cloud-init',
  template_guest_agent_ready: 'Guest agent',
  template_disk_floor: '템플릿 디스크',
  target_node_online: '노드 상태',
  storage_available: '스토리지',
  bridge_selection: '브리지 선택',
  bridge_exists: '브리지',
  static_ip_present: '고정 IP 입력',
  static_ip_valid: '고정 IP 형식',
  static_prefix_present: 'Prefix 입력',
  static_prefix_valid: 'Prefix 형식',
  static_gateway_present: 'Gateway 입력',
  static_gateway_valid: 'Gateway 형식',
  vmid_available: 'VMID',
  name_available: 'VM 이름',
  static_ip_available: '고정 IP 사용 여부',
  inventory_guest_agent_complete: 'VM IP 관찰',
  inventory_storage_complete: '스토리지 관찰',
  inventory_network_complete: '네트워크 관찰',
  inventory_vm_config_complete: 'VM 설정 관찰',
  inventory_vm_detail_complete: 'VM 상세 관찰',
  destroy_delete_plan_absent: '삭제 계획 없음',
  credential_scope_read_only: '인증 범위',
}

function StatusPill({ tone = 'slate', children }) {
  const tones = {
    green: 'bg-green-50 text-green-700 border-green-200',
    yellow: 'bg-yellow-50 text-yellow-700 border-yellow-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    slate: 'bg-slate-50 text-slate-700 border-slate-200',
  }
  return <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone] || tones.slate}`}>{children}</span>
}

function DetailRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 last:border-b-0">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-right text-sm font-medium text-slate-900 break-all">{value || '—'}</span>
    </div>
  )
}

function SummaryTile({ label, value, icon: Icon, wide = false }) {
  return (
    <div className={`min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 ${wide ? 'col-span-2 lg:col-span-1' : ''}`}>
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        {label}
      </div>
      <div className="mt-1 break-all text-sm font-semibold text-slate-950">{value || '—'}</div>
    </div>
  )
}

const WIZARD_STEPS = ['기본 정보', '배치·사양', '네트워크·접속', '최종 검토']

function StepIndicator({ currentStep }) {
  return <ol aria-label="VM 생성 단계" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
    {WIZARD_STEPS.map((label, index) => <li key={label} aria-current={index === currentStep ? 'step' : undefined}
      className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-sm ${index === currentStep ? 'border-blue-300 bg-blue-50 font-semibold text-blue-800' : 'border-slate-200 bg-white text-slate-500'}`}>
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-white">{index < currentStep ? <CheckCircle2 className="h-4 w-4" /> : index + 1}</span>{label}
    </li>)}
  </ol>
}

function toneForRiskLevel(level) {
  if (level === 'red') return 'red'
  if (level === 'yellow') return 'yellow'
  if (level === 'green') return 'green'
  return 'slate'
}

function riskLabel(level) {
  if (level === 'green') return '정상'
  if (level === 'yellow') return '확인 필요'
  if (level === 'red') return '차단'
  return '대기'
}

function checkLabel(code) {
  return CHECK_LABELS[code] || String(code || '').replace(/_/g, ' ')
}

function checkStatusLabel(check) {
  if (check.status === 'pass' && check.level === 'green') return '정상'
  if (check.level === 'yellow') return '확인'
  if (check.level === 'red') return '차단'
  return check.status || '대기'
}

function statusToneFromCheck(check) {
  if (check.level === 'red') return 'red'
  if (check.level === 'yellow') return 'yellow'
  if (check.status === 'pass') return 'green'
  return 'slate'
}

export function CreateVmPreflightCheck({ check }) {
  const ipObservation = buildStaticIpObservation(check)
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 p-2 text-sm">
      <div className="min-w-0">
        <span className="font-medium text-slate-800">{checkLabel(check.code)}</span>
        {ipObservation ? (
          <div className="mt-1 space-y-2 text-xs text-slate-600">
            <p>{ipObservation.message}</p>
            <div>
              <p><span className="font-medium text-slate-700">기존 VM 정보:</span> {ipObservation.inventoryMessage}</p>
              {ipObservation.conflicts.length > 0 && (
                <p className="mt-1 break-words">같은 IP를 사용하는 VM: {ipObservation.conflicts.map((vm) => `${vm.node_id}:${vm.vmid}${vm.name ? ` (${vm.name})` : ''}`).join(', ')}</p>
              )}
              {ipObservation.inventoryIncomplete && <p className="mt-1">일부 기존 VM의 내부 IP를 읽지 못했습니다.</p>}
              {ipObservation.failedTargets.length > 0 && (
                <p className="mt-1 break-words">IP를 읽지 못한 기존 VM: {ipObservation.failedTargets.join(', ')}</p>
              )}
            </div>
            <div>
              <p><span className="font-medium text-slate-700">Ping 응답:</span> {ipObservation.pingMessage}</p>
              {ipObservation.pingLocation && <p className="mt-1 text-slate-500">{ipObservation.pingLocation}</p>}
            </div>
          </div>
        ) : check.code.startsWith('inventory_') && (
          <>
            <p className="mt-1 text-xs text-slate-600">{check.message}</p>
            {Array.isArray(check.detail?.failed_targets) && check.detail.failed_targets.length > 0 && (
              <p className="mt-1 break-words text-xs text-slate-600">{check.code === 'inventory_guest_agent_complete' ? 'IP를 읽지 못한 기존 VM' : '확인 실패 대상'}: {check.detail.failed_targets.join(', ')}</p>
            )}
          </>
        )}
      </div>
      <StatusPill tone={ipObservation?.tone || statusToneFromCheck(check)}>{ipObservation?.statusLabel || checkStatusLabel(check)}</StatusPill>
    </div>
  )
}

function approvalToneClass(approval) {
  if (approval?.tone === 'green') return 'border-green-200 bg-green-50 text-green-700'
  if (approval?.tone === 'yellow') return 'border-yellow-200 bg-yellow-50 text-yellow-800'
  return 'border-red-200 bg-red-50 text-red-700'
}

function normalizeNodeOptions(nodes = []) {
  return Array.isArray(nodes)
    ? nodes
      .map((node) => ({
        id: node.node_id || node.id || node.name || '',
        label: node.display_name || node.node_id || node.id || '',
        status: node.status || '',
      }))
      .filter((node) => node.id)
      .sort((left, right) => left.id.localeCompare(right.id, undefined, { numeric: true }))
    : []
}

function normalizeStorageOptions(storages = []) {
  return Array.isArray(storages)
    ? storages
      .map((storage) => ({
        id: storage.storage_id || storage.storageId || '',
        nodeId: storage.node_id || storage.nodeId || '',
        type: storage.type || 'unknown',
        freeGb: Number(storage.free_gb ?? storage.freeGb ?? 0),
        totalGb: Number(storage.total_gb ?? storage.totalGb ?? 0),
        content: Array.isArray(storage.content) ? storage.content : [],
      }))
      .filter((storage) => storage.id && storage.nodeId)
      .sort((left, right) => {
        const nodeSort = left.nodeId.localeCompare(right.nodeId, undefined, { numeric: true })
        if (nodeSort) return nodeSort
        return left.id.localeCompare(right.id, undefined, { numeric: true })
      })
    : []
}

function normalizeBridgeOptions(networks = []) {
  return Array.isArray(networks)
    ? networks
      .map((network) => ({
        id: `${network.node_id || network.nodeId || ''}/${network.bridge_id || network.bridgeId || ''}`,
        bridgeId: network.bridge_id || network.bridgeId || '',
        nodeId: network.node_id || network.nodeId || '',
        type: network.type || 'bridge',
        active: network.active === true,
        displayName: network.display_name || network.displayName || network.name || '',
      }))
      .filter((bridge) => bridge.bridgeId && bridge.nodeId)
      .sort((left, right) => left.id.localeCompare(right.id, undefined, { numeric: true }))
    : []
}

function storageLabel(storage) {
  const free = Number.isFinite(storage.freeGb) ? `${storage.freeGb} GB free` : ''
  return [storage.id, storage.type, free].filter(Boolean).join(' · ')
}

function templateLabel(template, disabledReason = '') {
  const disk = template.diskGb > 0 ? `${template.diskGb} GB` : ''
  const label = [template.name, `${template.nodeId}/${template.vmid}`, disk].filter(Boolean).join(' · ')
  return disabledReason ? `${label} - ${disabledReason}` : label
}

function profileDisplayName(profile) {
  return [profile?.displayNameKo, profile?.displayName].filter(Boolean).join(' / ')
}

function hardwareForTemplate(hardware = {}, template = null) {
  const currentDiskGb = Number(hardware.diskGb ?? hardware.disk_gb ?? 0)
  const templateDiskGb = Number(template?.diskGb ?? 0)
  if (!templateDiskGb || currentDiskGb >= templateDiskGb) return hardware
  return { ...hardware, diskGb: templateDiskGb }
}

function selectPreferredStorage(storages, nodeId, currentStorageId = '') {
  const candidates = (storages || []).filter((storage) => storage.nodeId === nodeId && storage.content.includes('images') && storage.freeGb > 0)
  if (!candidates.length) return null
  return candidates.find((storage) => storage.id === currentStorageId)
    || candidates.find((storage) => storage.type === 'nfs')
    || candidates[0]
}

function bridgeLabel(bridge) {
  const status = bridge.active ? '활성' : '비활성'
  const name = bridge.displayName || ''
  const parts = [name, bridge.bridgeId, bridge.type, status].filter(Boolean)
  return parts.join(' · ')
}

function selectPreferredBridge(bridges, nodeId, currentBridgeId = '') {
  const candidates = (bridges || []).filter((bridge) => bridge.nodeId === nodeId && bridge.active === true)
  if (!candidates.length) return null
  return candidates.find((bridge) => bridge.bridgeId === currentBridgeId) || candidates[0]
}

function firstRangeStart(bridge) {
  const range = bridge?.staticIpRanges?.find((item) => item?.start)
  return range?.start || ''
}

function buildInitialForm(config, currentUser = null) {
  const defaults = buildCreateVmDefaults()
  const input = buildCreateVmInputFromConfig(config, {
    operatorId: currentUser?.username || 'authenticated-session',
    jobId: `ui-${randomUUID()}`,
    creationMode: config.creationMode || 'template',
    profileId: '',
    targetNodeId: '',
    bridgeId: '',
    storageId: '',
    staticIp: '',
    prefix: defaults.network.prefix,
    gateway: defaults.network.gateway,
    ipMode: defaults.network.ipMode,
    cloudInitUser: defaults.access.cloudInitUser,
    sshPublicKey: defaults.access.sshPublicKey,
    passwordLogin: defaults.access.passwordLogin,
    powerPolicy: 'stopped',
  })
  return {
    ...input,
    creationMode: config.creationMode || 'template',
    profileId: config.creationMode === 'profile' ? (config.profileId || '') : '',
    targetNodeId: config.targetNodeId || '',
    hardware: config.hardware || defaults.hardware,
    storageId: input.storageId || '',
    bridgeId: input.bridgeId || '',
    prefix: input.prefix || defaults.network.prefix,
    gateway: input.gateway || defaults.network.gateway,
    cloudInitUser: config.cloudInitUser || defaults.access.cloudInitUser,
    sshPublicKey: input.sshPublicKey || defaults.access.sshPublicKey,
    passwordLogin: false,
    powerPolicy: input.powerPolicy || 'stopped',
  }
}

function CreateInstanceWizard({ config = {}, onConfigChange = () => {}, currentUser = null, canExecuteLiveMutation = true, testTemplate = '' }) {
  const navigate = useNavigate()
  const [form, setForm] = useState(() => buildInitialForm(config, currentUser))
  const [step, setStep] = useState(0)
  const [model, setModel] = useState(null)
  const [approval, setApproval] = useState(null)
  const [createResult, setCreateResult] = useState(null)
  const [yellowRiskAcknowledged, setYellowRiskAcknowledged] = useState(false)
  const [proxmoxMutationAcknowledged, setProxmoxMutationAcknowledged] = useState(false)
  const [loading, setLoading] = useState(false)
  const [approving, setApproving] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(null)
  const [options, setOptions] = useState({
    nodes: [],
    templates: [],
    storages: [],
    networks: [],
    profiles: [],
    profileError: null,
    loading: true,
    error: null,
  })

  const reviewRiskTone = useMemo(() => {
    const level = model?.review?.riskLevel || model?.preflight?.level
    return toneForRiskLevel(level)
  }, [model])

  const nodeOptions = useMemo(() => normalizeNodeOptions(options.nodes), [options.nodes])
  const templateOptions = useMemo(() => normalizeTemplateOptions(options.templates), [options.templates])
  const testTemplateUnavailable = Boolean(testTemplate) && !options.loading && !templateOptions.some(item => item.key === testTemplate)
  const storageOptions = useMemo(() => normalizeStorageOptions(options.storages), [options.storages])
  const allBridgeOptions = useMemo(() => normalizeBridgeOptions(options.networks), [options.networks])
  const profileOptions = useMemo(() => normalizeCreateVmProfiles(options.profiles), [options.profiles])
  const selectedProfile = profileOptions.find((profile) => profile.profileId === form.profileId) || {}
  const presetUnavailable = form.creationMode === 'profile' && !selectedProfile.profileId
  const nodeStorageOptions = useMemo(
    () => storageOptions.filter((storage) => storage.nodeId === form.targetNodeId && storage.content.includes('images') && storage.freeGb > 0),
    [storageOptions, form.targetNodeId],
  )
  const bridgeOptions = useMemo(
    () => allBridgeOptions.filter((bridge) => bridge.nodeId === form.targetNodeId && bridge.active === true),
    [allBridgeOptions, form.targetNodeId],
  )
  const selectedTemplateKey = form.templateKey || (form.templateNodeId && form.templateVmid ? `${form.templateNodeId}/${form.templateVmid}` : form.templateId)
  const templateSelection = useMemo(
    () => validateTemplateSelection(templateOptions, selectedProfile, selectedTemplateKey),
    [templateOptions, selectedProfile, selectedTemplateKey],
  )
  const hardwareLimits = selectedProfile?.hardware || {}
  const selectedBridge = bridgeOptions.find((bridge) => bridge.bridgeId === form.bridgeId) || null
  const selectedIpModeLabel = form.ipMode === 'dhcp' ? 'DHCP' : '고정 IP'
  const reviewedNetwork = model?.review?.network || {}
  const reviewedAccess = model?.review?.access || {}
  const reviewedStaticIp = reviewedNetwork.static_ip || reviewedNetwork.staticIp || reviewedNetwork.ip_address || reviewedNetwork.ipAddress || form.staticIp
  const reviewedPrefix = reviewedNetwork.prefix ?? form.prefix
  const reviewedGateway = reviewedNetwork.gateway || form.gateway
  const reviewedIpSummary = form.ipMode === 'dhcp'
    ? selectedIpModeLabel
    : [reviewedStaticIp, reviewedPrefix ? `/${reviewedPrefix}` : '', reviewedGateway ? `gw ${reviewedGateway}` : ''].join(' ').replace(' /', '/').trim()
  const hardware = form.hardware || {}
  const cpuValue = hardware.cpu ?? hardwareLimits.cpu?.default ?? 2
  const memoryMb = hardware.memoryMb ?? hardware.memory_mb ?? hardwareLimits.memoryMb?.default ?? 4096
  const diskGb = hardware.diskGb ?? hardware.disk_gb ?? hardwareLimits.diskGb?.default ?? 50
  const staticIpPlaceholder = firstRangeStart(selectedBridge) || '예: 192.168.2.142'
  const reviewedSshKeySummary = reviewedAccess.sshKeyPresent
    ? (reviewedAccess.fingerprint || '키 있음')
    : '없음'
  const bootAndVerifySelected = form.powerPolicy === 'boot_and_verify'
  const reviewedFirstBootLabel = model?.review?.firstPowerOnIncluded ? '부팅 후 확인' : '생성만'
  const mutationAckLabel = model?.review?.firstPowerOnIncluded
    ? 'Proxmox에 VM을 만들고 부팅해서 IP와 cloud-init 확인까지 실행하는 것을 승인합니다.'
    : 'Proxmox에 꺼진 상태의 VM을 실제로 만드는 것을 승인합니다.'
  const nativeCreateButtonLabel = model?.review?.firstPowerOnIncluded ? '생성 후 부팅 확인' : 'Proxmox native create'
  const liveMutationDisabledReason = canExecuteLiveMutation ? '' : 'operator 또는 admin 권한이 필요합니다.'
  const sessionOperatorId = currentUser?.username || form.operatorId || 'authenticated-session'

  useEffect(() => {
    let cancelled = false
    async function loadOptions() {
      const [nodes, templates, storages, networks, profiles] = await Promise.allSettled([
        apiV1Client.listNodes(),
        apiV1Client.listTemplates(),
        apiV1Client.listStorage(),
        apiV1Client.listNetworks(),
        apiV1Client.listProfiles(),
      ])
      if (cancelled) return
      const inventoryFailures = [nodes, templates, storages, networks].filter((result) => result.status === 'rejected')
      const profileValues = profiles.status === 'fulfilled' ? normalizeCreateVmProfiles(profiles.value) : []
      const profileError = profiles.status === 'rejected' ? '프리셋을 불러오지 못했습니다. 템플릿 직접 입력은 사용할 수 있습니다.' : null
      setOptions({
        nodes: nodes.status === 'fulfilled' ? nodes.value : [],
        templates: templates.status === 'fulfilled' ? templates.value : [],
        storages: storages.status === 'fulfilled' ? storages.value : [],
        networks: networks.status === 'fulfilled' ? networks.value : [],
        profiles: profileValues,
        profileError,
        loading: false,
        error: inventoryFailures[0]?.reason?.message || null,
      })
    }
    loadOptions()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!currentUser?.username) return
    setForm((current) => {
      if (current.operatorId === currentUser.username) return current
      const next = { ...current, operatorId: currentUser.username }
      onConfigChange(next)
      return next
    })
  }, [currentUser?.username, onConfigChange])

  const applyFormPatch = (patch) => {
    setForm((current) => {
      const next = { ...current, ...patch, ...(model ? { jobId: `ui-${randomUUID()}` } : {}) }
      onConfigChange(next)
      return next
    })
    setModel(null)
    setYellowRiskAcknowledged(false)
    setProxmoxMutationAcknowledged(false)
    setApproval(null)
    setCreateResult(null)
    setError(null)
  }

  const updateForm = (field, value) => {
    applyFormPatch({ [field]: value })
  }

  useEffect(() => {
    if (options.loading) return
    setForm((current) => {
      const next = { ...current }
      let changed = false
      const fallbackNode = nodeOptions[0]?.id
      if (!next.targetNodeId && fallbackNode) {
        next.targetNodeId = fallbackNode
        changed = true
      }
      const currentTemplateKey = next.templateKey || (next.templateNodeId && next.templateVmid ? `${next.templateNodeId}/${next.templateVmid}` : next.templateId)
      const template = testTemplate ? templateOptions.find(item => item.key === testTemplate) : selectPreferredTemplate(templateOptions, selectedProfile, currentTemplateKey)
      if (template && (currentTemplateKey !== template.key || !next.templateId)) {
        next.templateKey = template.key
        next.templateId = template.templateId
        next.templateVmid = template.vmid
        next.templateNodeId = template.nodeId
        if (next.creationMode === 'template') next.hardware = hardwareFromTemplate(template)
        changed = true
      }
      if (!template && (next.templateKey || next.templateVmid || next.templateId || next.templateNodeId)) {
        next.templateKey = ''
        next.templateId = ''
        next.templateVmid = ''
        next.templateNodeId = ''
        changed = true
      }
      const alignedHardware = hardwareForTemplate(next.hardware, template)
      if (alignedHardware !== next.hardware) {
        next.hardware = alignedHardware
        changed = true
      }
      const storage = selectPreferredStorage(storageOptions, next.targetNodeId, next.storageId)
      if (storage && (!next.storageId || next.storageId !== storage.id)) {
        next.storageId = storage.id
        changed = true
      }
      const bridge = selectPreferredBridge(allBridgeOptions, next.targetNodeId, next.bridgeId)
      if (bridge && (!next.bridgeId || next.bridgeId !== bridge.bridgeId)) {
        next.bridgeId = bridge.bridgeId
        changed = true
      }
      if (changed) onConfigChange(next)
      return changed ? next : current
    })
  }, [nodeOptions, templateOptions, storageOptions, allBridgeOptions, options.loading, onConfigChange, selectedProfile, testTemplate])

  useEffect(() => {
    let cancelled = false
    apiV1Client.suggestVmId().then((suggestion) => {
      if (!cancelled) setForm((current) => current.vmid !== '' ? current : { ...current, vmid: String(suggestion.vmid) })
    }).catch(() => {
      if (!cancelled) setError('VMID 추천을 불러오지 못했습니다. 사용할 번호를 직접 입력하세요.')
    })
    return () => { cancelled = true }
  }, [])

  const nextStep = () => {
    if (testTemplateUnavailable) {
      setError('테스트 원본 템플릿을 조회할 수 없습니다. 연결의 생성 원본 범위를 확인하세요.')
      return
    }
    const panel = document.getElementById('create-vm-inputs')
    if (panel && !Array.from(panel.querySelectorAll('input, select, textarea')).every((input) => input.reportValidity())) return
    setError(null)
    setStep((current) => Math.min(3, current + 1))
  }

  const handleNodeChange = (nodeId) => {
    const bridge = selectPreferredBridge(allBridgeOptions, nodeId)
    const storage = selectPreferredStorage(storageOptions, nodeId)
    applyFormPatch({
      targetNodeId: nodeId,
      storageId: storage?.id || '',
      bridgeId: bridge?.bridgeId || '',
      staticIp: form.staticIp,
    })
  }

  const handleProfileChange = (profileId) => {
    const profile = profileOptions.find((item) => item.profileId === profileId)
    const template = selectPreferredTemplate(templateOptions, profile || {}, selectedTemplateKey)
    applyFormPatch({
      profileId,
      creationMode: profile ? 'profile' : 'template',
      templateKey: template?.key || '',
      templateId: template?.templateId || '',
      templateVmid: template?.vmid || '',
      templateNodeId: template?.nodeId || '',
      hardware: profile ? resetHardwareForProfile(profile, template?.diskGb) : hardwareFromTemplate(template),
      cloudInitUser: form.cloudInitUser || profile?.accessRecommendations.defaultUser || '',
      passwordLogin: false,
    })
  }

  const handleHardwareChange = (field, value) => {
    const nextValue = value === '' ? '' : Number(value)
    applyFormPatch({
      hardware: {
        ...(form.hardware || {}),
        [field]: nextValue,
      },
    })
  }

  const handleTemplateChange = (templateKey) => {
    const template = templateOptions.find((item) => item.key === templateKey)
    const status = templateRequirementStatus(template, selectedProfile)
    if (!template || status.disabled) {
      setError(status.reason ? `선택한 템플릿은 ${status.reason} 조건을 만족하지 않습니다.` : '요구사항을 만족하는 템플릿을 선택하세요.')
      return
    }
    applyFormPatch({
      templateKey,
      templateId: template?.templateId || '',
      templateVmid: template?.vmid || '',
      templateNodeId: template?.nodeId || '',
      hardware: form.creationMode === 'template' ? hardwareFromTemplate(template) : hardwareForTemplate(form.hardware, template),
    })
  }

  const handleBridgeChange = (bridgeId) => {
    applyFormPatch({
      bridgeId,
      staticIp: form.staticIp,
    })
  }

  const runReview = async () => {
    if (testTemplate && selectedTemplateKey !== testTemplate) {
      setError('테스트 원본 템플릿을 조회할 수 없습니다. 생성 원본 범위에 등록·검증·전환한 뒤 다시 여세요.')
      return
    }
    if (!canExecuteLiveMutation) {
      setError(liveMutationDisabledReason)
      return
    }
    if (presetUnavailable) {
      setError(options.profileError || 'Create VM profiles are unavailable.')
      return
    }
    const selection = validateTemplateSelection(templateOptions, selectedProfile, selectedTemplateKey)
    if (!selection.ok) {
      setError(selection.reason)
      return
    }
    // A new review captures new observations; an existing job keeps its exact plan.
    const reviewInput = { ...form, jobId: `ui-${randomUUID()}` }
    setForm(reviewInput)
    onConfigChange(reviewInput)
    setLoading(true)
    setModel(null)
    setYellowRiskAcknowledged(false)
    setError(null)
    setApproval(null)
    setCreateResult(null)
    setProxmoxMutationAcknowledged(false)
    try {
      const reviewModel = await loadCreateVmReviewModel(apiV1Client, reviewInput)
      setModel(reviewModel)
      setStep(3)
    } catch (err) {
      setError(authFailureMessage(err, 'VM 검토를 만들지 못했습니다.'))
      setModel(null)
    } finally {
      setLoading(false)
    }
  }

  const approveReview = async () => {
    if (!model?.review?.canApprove) return
    if (!canExecuteLiveMutation) {
      setError(liveMutationDisabledReason)
      return
    }
    setApproving(true)
    setError(null)
    try {
      const result = await approveCreateVmReview(apiV1Client, model, { yellowRiskAcknowledged })
      setApproval(result)
    } catch (err) {
      setError(authFailureMessage(err, '승인 처리에 실패했습니다.'))
      setApproval(null)
    } finally {
      setApproving(false)
    }
  }

  const createWithProxmox = async () => {
    if (!approval?.canApprove || !model?.review?.canCreateProxmox) return
    if (!canExecuteLiveMutation) {
      setError(liveMutationDisabledReason)
      return
    }
    setCreating(true)
    setError(null)
    const jobId = model?.draft?.jobId || form.jobId
    const operationId = model?.operation?.id || ''
    const createPromise = createVmWithProxmox(apiV1Client, model, {
      yellowRiskAcknowledged,
      proxmoxMutationAcknowledged,
    })
    navigate(operationId
      ? `/operations/${encodeURIComponent(operationId)}`
      : `/operations/jobs?job=${encodeURIComponent(jobId)}&compatibility=operation`)
    try {
      const result = await createPromise
      setCreateResult(result)
    } catch (err) {
      setError(authFailureMessage(err, 'Proxmox native VM 생성에 실패했습니다.'))
      const observed = err?.details?.proxmox_create?.observed_after
      const proxmoxCreate = err?.details?.proxmox_create
      setCreateResult(proxmoxCreate ? {
        status: proxmoxCreate.status || 'apply_failed',
        tone: 'red',
        observedAfter: observed || null,
        observedAfterArtifactId: proxmoxCreate?.observed_after_artifact?.artifact_id || proxmoxCreate?.observed_after_artifact?.id || '',
        observedAfterPath: '',
        fingerprintHash: observed?.fingerprint?.hash || '',
        operatorMessage: 'VM 생성 확인이 완료되지 않았습니다.',
      } : null)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      {testTemplate && <p className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm">템플릿 {testTemplate} 테스트 배포입니다. 별도 새 VMID와 SSH 공개키를 입력하고 부팅 후 확인을 검토하세요. 생성 작업에서 항목별 검사·접속 결과·명시적 정리로 이어집니다.</p>}
      {testTemplateUnavailable && <p role="alert" className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">지정한 원본 템플릿이 조회되지 않습니다. 생성 원본 범위에 등록·검증·전환한 뒤 다시 여세요.</p>}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Server className="h-4 w-4" />
            Verified creation
          </div>
          <h2 className="mt-2 text-3xl font-semibold text-slate-950">새 VM 만들기</h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">Proxmox 템플릿을 선택하고 사양과 접속 정보를 입력한 뒤 생성 내용을 검토하세요.</p>
        </div>
        <StatusPill tone="blue">생성 전 검토</StatusPill>
      </header>

      <StepIndicator currentStep={step} />
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
        <div className="mb-5 border-b border-slate-100 pb-4">
          <p className="text-xs font-semibold text-blue-600">STEP {step + 1} / 4</p>
          <h3 className="mt-1 text-xl font-semibold text-slate-950">{WIZARD_STEPS[step]}</h3>
          <p className="mt-1 text-sm text-slate-500">{['복제할 템플릿과 새 VM의 식별 정보를 정하세요.', 'VM을 배치할 위치와 필요한 자원을 선택하세요.', '네트워크와 SSH 접속 정보를 입력하세요.', '설정을 검토하고 차단·주의 항목을 확인하세요.'][step]}</p>
        </div>
        <fieldset id="create-vm-inputs" disabled={loading || approving || creating || options.loading}>
          {step === 0 && <>
        <div className="mt-6">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">템플릿</span>
            <select disabled={Boolean(testTemplate)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={selectedTemplateKey || ''} onChange={(event) => handleTemplateChange(event.target.value)}>
              {testTemplateUnavailable && <option value="">지정한 원본 조회 불가</option>}
              {templateOptions.length === 0 && <option value="">템플릿 없음</option>}
              {templateOptions.length > 0 && !templateSelection.options.some((template) => !template.disabled) && <option value="">요구사항 만족 템플릿 없음</option>}
              {templateOptions.map((template) => {
                const status = templateRequirementStatus(template, selectedProfile)
                return (
                  <option key={template.key} value={template.key} disabled={status.disabled}>
                    {templateLabel(template, status.reason)}
                  </option>
                )
              })}
            </select>
            {!options.loading && templateSelection.reason && (
              <span className="block text-xs font-medium text-red-600">{templateSelection.reason}</span>
            )}
          </label>
        </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="space-y-1"><span className="text-sm font-medium text-slate-700">VM 이름</span>
                <input required maxLength={63} pattern="[A-Za-z0-9](([A-Za-z0-9]|-)*[A-Za-z0-9])?" placeholder="예: app-server-01" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.vmName} onChange={(event) => updateForm('vmName', event.target.value)} />
              </label>
              <label className="space-y-1"><span className="text-sm font-medium text-slate-700">VMID</span>
                <input required type="number" min="100" max="999999999" step="1" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.vmid} onChange={(event) => updateForm('vmid', event.target.value)} />
                <span className="block text-xs text-slate-500">자동 추천 번호를 수정할 수 있습니다. 검토·생성 직전에 중복을 확인합니다.</span>
              </label>
            </div>
          </>}
          {step === 1 && <>
            <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">생성 노드</span>
            <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.targetNodeId} onChange={(event) => handleNodeChange(event.target.value)}>
              {nodeOptions.length === 0 && <option value={form.targetNodeId}>{form.targetNodeId || '노드 없음'}</option>}
              {nodeOptions.map((node) => (
                <option key={node.id} value={node.id}>{node.label || node.id}</option>
              ))}
            </select>
          </label>

          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">스토리지</span>
            <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.storageId || ''} onChange={(event) => updateForm('storageId', event.target.value)}>
              {nodeStorageOptions.length === 0 && <option value="">사용 가능한 스토리지 없음</option>}
              {nodeStorageOptions.map((storage) => (
                <option key={`${storage.nodeId}/${storage.id}`} value={storage.id}>{storageLabel(storage)}</option>
              ))}
            </select>
          </label>
            </div>
        <label className="mt-6 block space-y-1">
          <span className="text-sm font-medium text-slate-700">사양 프리셋 (선택 사항)</span>
          <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.profileId} onChange={(event) => handleProfileChange(event.target.value)}>
            <option value="">사용하지 않음 — 템플릿 사양에서 시작</option>
            {profileOptions.map((profile) => <option key={profile.profileId} value={profile.profileId} disabled={!profile.enabled || !profile.createEnabled}>{profileDisplayName(profile)}</option>)}
          </select>
          {options.profileError && <p className="text-xs text-amber-700">{options.profileError}</p>}
        </label>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">CPU</span>
            <input
              type="number"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              required value={cpuValue}
              min={hardwareLimits.cpu?.min || 1}
              max={hardwareLimits.cpu?.max}
              step="1"
              onChange={(event) => handleHardwareChange('cpu', event.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">메모리 MB</span>
            <input
              type="number"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              required value={memoryMb}
              min={hardwareLimits.memoryMb?.min || 1}
              max={hardwareLimits.memoryMb?.max}
              step="1"
              onChange={(event) => handleHardwareChange('memoryMb', event.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">디스크 GB</span>
            <input
              type="number"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              required value={diskGb}
              min={Math.max(hardwareLimits.diskGb?.min || 1, templateSelection.selected?.diskGb || 1)}
              max={hardwareLimits.diskGb?.max}
              step="1"
              onChange={(event) => handleHardwareChange('diskGb', event.target.value)}
            />
          </label>
        </div>

          </>}
          {step === 2 && <>
            <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">네트워크</span>
            <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.bridgeId || ''} onChange={(event) => handleBridgeChange(event.target.value)}>
              {bridgeOptions.length === 0 && <option value="">브리지 없음</option>}
              {bridgeOptions.map((bridge) => (
                <option key={bridge.id} value={bridge.bridgeId}>{bridgeLabel(bridge)}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">IP 방식</span>
            <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.ipMode} onChange={(event) => updateForm('ipMode', event.target.value)}>
              <option value="static">고정 IP</option>
              <option value="dhcp">DHCP</option>
            </select>
          </label>
            {form.ipMode === 'static' && <>
          <label className="space-y-1 md:col-span-2">
            <span className="text-sm font-medium text-slate-700">고정 IP</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" required value={form.staticIp} onChange={(event) => updateForm('staticIp', event.target.value)} placeholder={staticIpPlaceholder} disabled={form.ipMode === 'dhcp'} />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Prefix</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" required value={form.prefix || ''} onChange={(event) => updateForm('prefix', event.target.value)} placeholder="예: 24" disabled={form.ipMode === 'dhcp'} inputMode="numeric" />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Gateway</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" required value={form.gateway || ''} onChange={(event) => updateForm('gateway', event.target.value)} placeholder="예: 192.168.2.254" disabled={form.ipMode === 'dhcp'} />
          </label>
            </>}
            </div>
        <div className="mt-6 border-t border-slate-100 pt-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-slate-600" />
              <h3 className="text-sm font-semibold text-slate-950">Access</h3>
            </div>
            <StatusPill tone="slate">Password login disabled</StatusPill>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1">
              <span className="text-sm font-medium text-slate-700">접속 사용자</span>
              <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" required value={form.cloudInitUser || ''} onChange={(event) => updateForm('cloudInitUser', event.target.value)} />
            </label>
            <div className="space-y-1">
              <span className="text-sm font-medium text-slate-700">비밀번호 로그인</span>
              <div className="flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">Disabled</div>
            </div>
            <label className="space-y-1 md:col-span-2">
              <span className="text-sm font-medium text-slate-700">SSH public key</span>
              <textarea placeholder="ssh-ed25519 AAAA…" className="min-h-28 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs text-slate-900" required value={form.sshPublicKey || ''} onChange={(event) => updateForm('sshPublicKey', event.target.value)} spellCheck="false" />
            </label>
          </div>
        </div>

          </>}
          {step === 3 && <>
          <div className="space-y-1 md:col-span-2">
            <span className="text-sm font-medium text-slate-700">생성 후 상태</span>
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => updateForm('powerPolicy', 'stopped')}
                aria-pressed={!bootAndVerifySelected}
                className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${
                  !bootAndVerifySelected ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                }`}
              >
                <Server className="h-4 w-4" />
                꺼진 상태로 생성
              </button>
              <button
                type="button"
                onClick={() => updateForm('powerPolicy', 'boot_and_verify')}
                aria-pressed={bootAndVerifySelected}
                className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${
                  bootAndVerifySelected ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                }`}
              >
                <PlayCircle className="h-4 w-4" />
                부팅 후 IP 확인
              </button>
            </div>
          </div>
            <details className="mt-5 text-sm text-slate-500"><summary className="cursor-pointer">작업 상세</summary>
              <p className="mt-2 break-all">작업 ID: {form.jobId}</p><p>세션 사용자: {sessionOperatorId}</p>
            </details>
          </>}
        </fieldset>
      </section>

      {error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {options.error && (
        <div role="status" className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
          {options.error}
        </div>
      )}

      {step === 3 && model && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_360px]">
          <div className="space-y-4">
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-5 w-5 text-slate-600" />
                  <h3 className="font-semibold text-slate-950">생성 검토</h3>
                </div>
                <StatusPill tone={reviewRiskTone}>{riskLabel(model.review.riskLevel)}</StatusPill>
              </div>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                <SummaryTile label="프로필" value={model.review.profileId || '직접 입력'} />
                <SummaryTile label="VM 이름" value={model.review.vmName} icon={Server} />
                <SummaryTile label="VMID" value={model.review.vmid} />
                <SummaryTile label="생성 노드" value={model.review.targetNode} icon={Server} />
                <SummaryTile label="IP" value={reviewedIpSummary} icon={Network} wide />
                <SummaryTile label="사양" value={`${model.review.hardware.cpu} CPU / ${model.review.hardware.memoryMb} MB / ${model.review.hardware.diskGb} GB`} />
                <SummaryTile label="스토리지" value={model.review.storage} />
                <SummaryTile label="템플릿" value={model.review.template} />
                <SummaryTile label="네트워크" value={`${selectedIpModeLabel} / ${model.review.network.bridge_id || model.review.network.bridgeId || form.bridgeId || ''}`} icon={Network} />
                <SummaryTile label="접속 사용자" value={reviewedAccess.username || reviewedAccess.cloudInitUser || form.cloudInitUser} icon={KeyRound} />
                <SummaryTile label="SSH 키" value={reviewedSshKeySummary} icon={KeyRound} wide />
                <SummaryTile label="생성 후 상태" value={reviewedFirstBootLabel} />
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-950">확인 항목</h3>
                <StatusPill tone={toneForRiskLevel(model.preflight.level)}>{riskLabel(model.preflight.level)}</StatusPill>
              </div>
              <div className="grid max-h-[28rem] gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                {model.preflight.checks.map((check) => (
                  <CreateVmPreflightCheck key={check.code} check={check} />
                ))}
              </div>
            </section>
          </div>

          <aside className="space-y-4">
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Rocket className="h-5 w-5 text-slate-600" />
                  <h3 className="font-semibold text-slate-950">생성 준비</h3>
                </div>
                <StatusPill tone={model.review.canCreateProxmox ? 'green' : 'yellow'}>{model.review.canCreateProxmox ? '가능' : '확인 필요'}</StatusPill>
              </div>
              <DetailRow label="생성 방식" value="Proxmox native create" />
              <DetailRow label="실행 조건" value={!canExecuteLiveMutation ? liveMutationDisabledReason : model.review.canCreateProxmox ? '승인 후 생성 가능' : '검토 항목 확인 필요'} />
              <DetailRow label="생성 후 상태" value={reviewedFirstBootLabel} />
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="mb-3 font-semibold text-slate-950">다음 작업</h3>
              {model.review.riskLevel === 'yellow' && (
                <label className="mb-3 flex items-start gap-2 rounded-lg border border-yellow-200 bg-yellow-50 p-2 text-sm text-yellow-800">
                  <input type="checkbox" className="mt-1" checked={yellowRiskAcknowledged} onChange={(event) => setYellowRiskAcknowledged(event.target.checked)} />
                  {model.review.requiresStaticIpConfirmation
                    ? '확인 필요 항목을 검토했으며, 입력한 IP는 제가 직접 확보한 IP입니다.'
                    : '확인 필요 항목을 검토했습니다.'}
                </label>
              )}
              <button type="button" onClick={approveReview} disabled={!canExecuteLiveMutation || !model.review.canApprove || loading || approving || creating} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                검토 내용 승인
              </button>
              <label className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-800">
                <input type="checkbox" className="mt-1" checked={proxmoxMutationAcknowledged} onChange={(event) => setProxmoxMutationAcknowledged(event.target.checked)} disabled={!canExecuteLiveMutation} />
                {mutationAckLabel}
              </label>
              {!canExecuteLiveMutation && (
                <div className="mt-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
                  {liveMutationDisabledReason}
                </div>
              )}
              <button type="button" onClick={createWithProxmox} disabled={!canExecuteLiveMutation || !approval?.canApprove || !model.review.canCreateProxmox || !proxmoxMutationAcknowledged || loading || approving || creating} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                {nativeCreateButtonLabel}
              </button>
              {approval && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${approvalToneClass(approval)}`}>
                  {approval.operatorMessage}
                </div>
              )}
              {createResult && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${createResult.status === 'applied' ? 'border-green-200 bg-green-50 text-green-700' : 'border-yellow-200 bg-yellow-50 text-yellow-800'}`}>
                  <div>{createResult.operatorMessage}</div>
                  <div className={`mt-1 break-all text-xs ${createResult.status === 'applied' ? 'text-green-600' : 'text-yellow-700'}`}>{createResult.fingerprintHash || createResult.observedAfterArtifactId}</div>
                </div>
              )}
            </section>
          </aside>
        </div>
      )}

      {step === 3 && model?.review?.riskLevel === 'red' && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          차단 항목이 있어 승인할 수 없습니다.
        </div>
      )}
      <footer className="sticky bottom-0 z-10 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/95 p-4 shadow-sm backdrop-blur">
        <button type="button" disabled={step === 0 || loading || approving || creating} onClick={() => { setStep((current) => current - 1); setError(null) }} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-40">이전</button>
        <span className="hidden text-xs text-slate-500 sm:block">입력값은 이전 단계로 이동해도 유지됩니다.</span>
        {step < 3 ? <button type="button" onClick={nextStep} disabled={options.loading || !templateSelection.ok} className="rounded-lg bg-slate-950 px-5 py-2 text-sm font-semibold text-white disabled:opacity-40">다음</button>
          : <button type="button" onClick={runReview} disabled={!canExecuteLiveMutation || loading || approving || creating || options.loading || presetUnavailable || !templateSelection.ok} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}{model ? '다시 검토' : '검토 시작'}
          </button>}
      </footer>
    </div>
  )
}

export default CreateInstanceWizard
