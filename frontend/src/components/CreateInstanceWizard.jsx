import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ClipboardCheck, KeyRound, Loader2, Network, Rocket, Server, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { apiV1Client } from '../services/apiV1'
import { buildCreateVmDefaults, normalizeCreateVmProfiles, resetHardwareForProfile } from '../utils/createVmDefaults'
import {
  approveCreateVmReview,
  buildCreateVmInputFromConfig,
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
  network_policy_registered: '네트워크 정책',
  static_ip_range_configured: '고정 IP 범위',
  static_ip_in_policy_range: 'IP 범위 확인',
  static_ip_present: '고정 IP 입력',
  static_ip_valid: '고정 IP 형식',
  static_prefix_present: 'Prefix 입력',
  static_prefix_valid: 'Prefix 형식',
  static_gateway_present: 'Gateway 입력',
  static_gateway_valid: 'Gateway 형식',
  vmid_available: 'VMID',
  name_available: 'VM 이름',
  static_ip_available: '고정 IP',
  shared_root_available: '공유 폴더',
  iac_root_available: '코드 저장소',
  iac_root_writable: '코드 저장소 쓰기',
  iac_git_repo_available: 'Git 저장소',
  iac_write_allowlist_ready: '쓰기 경로',
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
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone] || tones.slate}`}>{children}</span>
}

function DetailRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 last:border-b-0">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-right text-sm font-medium text-slate-900 break-all">{value || '—'}</span>
    </div>
  )
}

function SummaryTile({ label, value, icon: Icon }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        {label}
      </div>
      <div className="mt-1 break-all text-sm font-semibold text-slate-950">{value || '—'}</div>
    </div>
  )
}

function StepIndicator({ model, approval, createResult }) {
  const steps = [
    { label: '요청 입력', done: true, active: !model },
    { label: '검토', done: Boolean(model), active: Boolean(model) && !approval },
    { label: '승인', done: Boolean(approval?.canApprove), active: Boolean(approval) && !createResult },
    { label: 'Native 생성', done: Boolean(createResult), active: Boolean(createResult) },
  ]
  return (
    <div className="grid gap-2 sm:grid-cols-4">
      {steps.map((step, index) => (
        <div
          key={step.label}
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${
            step.active
              ? 'border-blue-300 bg-blue-50 text-blue-700'
              : step.done
                ? 'border-green-200 bg-green-50 text-green-700'
                : 'border-slate-200 bg-white text-slate-500'
          }`}
        >
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-white text-xs font-semibold">
            {step.done && !step.active ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
          </span>
          <span className="text-sm font-medium">{step.label}</span>
        </div>
      ))}
    </div>
  )
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

function buildInitialForm(config) {
  const defaults = buildCreateVmDefaults()
  const now = new Date()
  const datePart = now.toISOString().slice(0, 10).replaceAll('-', '')
  const timePart = now.toTimeString().slice(0, 8).replaceAll(':', '')
  const input = buildCreateVmInputFromConfig(config, {
    operatorId: 'ui-operator',
    jobId: `ui-${datePart}-${timePart}`,
    profileId: config.profileId || config.profile_id || 'general-vm',
    targetNodeId: 'yoonmanserver2',
    bridgeId: '',
    storageId: '',
    staticIp: '',
    prefix: defaults.network.prefix,
    gateway: defaults.network.gateway,
    ipMode: defaults.network.ipMode,
    cloudInitUser: defaults.access.cloudInitUser,
    sshPublicKey: defaults.access.sshPublicKey,
    passwordLogin: defaults.access.passwordLogin,
  })
  const profile = defaults.profileOptions.find((item) => item.profileId === input.profileId) || defaults.profileOptions[0]
  return {
    ...input,
    profileId: input.profileId || defaults.profileId,
    hardware: config.hardware || resetHardwareForProfile(profile),
    storageId: input.storageId || '',
    bridgeId: input.bridgeId || '',
    prefix: input.prefix || defaults.network.prefix,
    gateway: input.gateway || defaults.network.gateway,
    cloudInitUser: input.cloudInitUser || profile.accessRecommendations.defaultUser || defaults.access.cloudInitUser,
    sshPublicKey: input.sshPublicKey || defaults.access.sshPublicKey,
    passwordLogin: false,
  }
}

function CreateInstanceWizard({ config = {}, onConfigChange = () => {} }) {
  const navigate = useNavigate()
  const [form, setForm] = useState(() => buildInitialForm(config))
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
    profiles: buildCreateVmDefaults().profileOptions,
    profilesReady: false,
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
  const storageOptions = useMemo(() => normalizeStorageOptions(options.storages), [options.storages])
  const allBridgeOptions = useMemo(() => normalizeBridgeOptions(options.networks), [options.networks])
  const profileOptions = useMemo(() => normalizeCreateVmProfiles(options.profiles), [options.profiles])
  const profilesReady = options.profilesReady === true && profileOptions.length > 0
  const selectedProfile = profileOptions.find((profile) => profile.profileId === form.profileId) || profileOptions[0]
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
      let profileValues = []
      let profilesReady = false
      let profileError = null
      if (profiles.status === 'fulfilled') {
        profileValues = normalizeCreateVmProfiles(profiles.value)
        profilesReady = profileValues.length > 0
        if (!profilesReady) {
          profileValues = buildCreateVmDefaults().profileOptions
          profileError = 'Create VM profile API returned no active profiles.'
        }
      } else {
        profileValues = buildCreateVmDefaults().profileOptions
        profileError = profiles.reason?.message || 'Create VM profile API is unavailable.'
      }
      setOptions({
        nodes: nodes.status === 'fulfilled' ? nodes.value : [],
        templates: templates.status === 'fulfilled' ? templates.value : [],
        storages: storages.status === 'fulfilled' ? storages.value : [],
        networks: networks.status === 'fulfilled' ? networks.value : [],
        profiles: profileValues,
        profilesReady,
        profileError,
        loading: false,
        error: profileError || inventoryFailures[0]?.reason?.message || null,
      })
    }
    loadOptions()
    return () => {
      cancelled = true
    }
  }, [])

  const applyFormPatch = (patch) => {
    setForm((current) => {
      const next = { ...current, ...patch }
      onConfigChange(next)
      return next
    })
    setModel(null)
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
      const template = selectPreferredTemplate(templateOptions, selectedProfile, currentTemplateKey)
      if (template && currentTemplateKey !== template.key) {
        next.templateKey = template.key
        next.templateId = template.templateId
        next.templateVmid = template.vmid
        next.templateNodeId = template.nodeId
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
  }, [nodeOptions, templateOptions, storageOptions, allBridgeOptions, options.loading, onConfigChange, selectedProfile])

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
    const profile = profileOptions.find((item) => item.profileId === profileId) || profileOptions[0]
    const template = selectPreferredTemplate(templateOptions, profile, selectedTemplateKey)
    applyFormPatch({
      profileId,
      templateKey: template?.key || '',
      templateId: template?.templateId || '',
      templateVmid: template?.vmid || '',
      templateNodeId: template?.nodeId || '',
      hardware: resetHardwareForProfile(profile, template?.diskGb),
      cloudInitUser: form.cloudInitUser || profile.accessRecommendations.defaultUser || 'yoon',
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
      hardware: hardwareForTemplate(form.hardware, template),
    })
  }

  const handleBridgeChange = (bridgeId) => {
    applyFormPatch({
      bridgeId,
      staticIp: form.staticIp,
    })
  }

  const runReview = async () => {
    if (!profilesReady) {
      setError(options.profileError || 'Create VM profiles are unavailable.')
      return
    }
    const selection = validateTemplateSelection(templateOptions, selectedProfile, selectedTemplateKey)
    if (!selection.ok) {
      setError(selection.reason)
      return
    }
    setLoading(true)
    setError(null)
    setApproval(null)
    setCreateResult(null)
    setProxmoxMutationAcknowledged(false)
    try {
      const reviewModel = await loadCreateVmReviewModel(apiV1Client, form)
      setModel(reviewModel)
    } catch (err) {
      setError(err?.message || 'VM 검토를 만들지 못했습니다.')
      setModel(null)
    } finally {
      setLoading(false)
    }
  }

  const approveReview = async () => {
    if (!model?.review?.canApprove) return
    setApproving(true)
    setError(null)
    try {
      const result = await approveCreateVmReview(apiV1Client, model, { yellowRiskAcknowledged })
      setApproval(result)
    } catch (err) {
      setError(err?.message || '승인 처리에 실패했습니다.')
      setApproval(null)
    } finally {
      setApproving(false)
    }
  }

  const createWithProxmox = async () => {
    if (!approval?.canApprove || !model?.review?.canCreateProxmox) return
    setCreating(true)
    setError(null)
    const jobId = model?.draft?.jobId || form.jobId
    const createPromise = createVmWithProxmox(apiV1Client, model, {
      yellowRiskAcknowledged,
      proxmoxMutationAcknowledged,
    })
    navigate(`/jobs?job=${encodeURIComponent(jobId)}`)
    try {
      const result = await createPromise
      setCreateResult(result)
    } catch (err) {
      setError(err?.message || 'Proxmox native VM 생성에 실패했습니다.')
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
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Server className="h-5 w-5 text-slate-700" />
              <h2 className="text-xl font-semibold text-slate-950">새 VM 만들기</h2>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <StatusPill tone="slate">{form.profileId || 'general-vm'}</StatusPill>
              <StatusPill tone="slate">{cpuValue} CPU</StatusPill>
              <StatusPill tone="slate">{memoryMb} MB</StatusPill>
              <StatusPill tone="slate">{diskGb} GB</StatusPill>
            </div>
          </div>
          <StatusPill tone="blue">생성 전 검토</StatusPill>
        </div>

        <div className="mt-5">
          <StepIndicator model={model} approval={approval} createResult={createResult} />
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {profileOptions.map((profile) => {
            const selected = profile.profileId === form.profileId
            const disabled = profile.enabled === false || profile.createEnabled === false
            return (
              <button
                key={profile.profileId}
                type="button"
                disabled={disabled}
                onClick={() => handleProfileChange(profile.profileId)}
                className={`min-h-28 rounded-lg border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  selected ? 'border-blue-400 bg-blue-50 ring-1 ring-blue-200' : 'border-slate-200 bg-white hover:border-slate-300'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-slate-950">{profileDisplayName(profile)}</div>
                    <div className="mt-1 text-xs text-slate-500">{profile.profileId}</div>
                  </div>
                  <StatusPill tone={selected ? 'blue' : 'slate'}>{selected ? '선택' : '프로필'}</StatusPill>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusPill tone="slate">{profile.hardware.cpu.default} CPU</StatusPill>
                  <StatusPill tone="slate">{profile.hardware.memoryMb.default} MB</StatusPill>
                  <StatusPill tone="slate">{profile.hardware.diskGb.default} GB</StatusPill>
                </div>
              </button>
            )
          })}
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">CPU</span>
            <input
              type="number"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={cpuValue}
              min={hardwareLimits.cpu?.min}
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
              value={memoryMb}
              min={hardwareLimits.memoryMb?.min}
              max={hardwareLimits.memoryMb?.max}
              step="512"
              onChange={(event) => handleHardwareChange('memoryMb', event.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">디스크 GB</span>
            <input
              type="number"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={diskGb}
              min={hardwareLimits.diskGb?.min}
              max={hardwareLimits.diskGb?.max}
              step="10"
              onChange={(event) => handleHardwareChange('diskGb', event.target.value)}
            />
          </label>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">담당자</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.operatorId} onChange={(event) => updateForm('operatorId', event.target.value)} />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">작업 ID</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.jobId} onChange={(event) => updateForm('jobId', event.target.value)} />
          </label>
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
            <span className="text-sm font-medium text-slate-700">템플릿</span>
            <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={selectedTemplateKey || ''} onChange={(event) => handleTemplateChange(event.target.value)}>
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
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">스토리지</span>
            <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.storageId || ''} onChange={(event) => updateForm('storageId', event.target.value)}>
              {nodeStorageOptions.length === 0 && <option value="">사용 가능한 스토리지 없음</option>}
              {nodeStorageOptions.map((storage) => (
                <option key={`${storage.nodeId}/${storage.id}`} value={storage.id}>{storageLabel(storage)}</option>
              ))}
            </select>
          </label>
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
          <label className="space-y-1 md:col-span-2">
            <span className="text-sm font-medium text-slate-700">고정 IP</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.staticIp} onChange={(event) => updateForm('staticIp', event.target.value)} placeholder={staticIpPlaceholder} disabled={form.ipMode === 'dhcp'} />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Prefix</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.prefix || ''} onChange={(event) => updateForm('prefix', event.target.value)} placeholder="예: 24" disabled={form.ipMode === 'dhcp'} inputMode="numeric" />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Gateway</span>
            <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.gateway || ''} onChange={(event) => updateForm('gateway', event.target.value)} placeholder="예: 192.168.2.254" disabled={form.ipMode === 'dhcp'} />
          </label>
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
              <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.cloudInitUser || ''} onChange={(event) => updateForm('cloudInitUser', event.target.value)} />
            </label>
            <div className="space-y-1">
              <span className="text-sm font-medium text-slate-700">비밀번호 로그인</span>
              <div className="flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">Disabled</div>
            </div>
            <label className="space-y-1 md:col-span-2">
              <span className="text-sm font-medium text-slate-700">SSH public key</span>
              <textarea className="min-h-28 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs text-slate-900" value={form.sshPublicKey || ''} onChange={(event) => updateForm('sshPublicKey', event.target.value)} spellCheck="false" />
            </label>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" onClick={runReview} disabled={loading || options.loading || !profilesReady || !templateSelection.ok} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
            검토 시작
          </button>
          <StatusPill tone="slate">실제 생성 전</StatusPill>
          <StatusPill tone="slate">승인 필요</StatusPill>
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {options.error && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
          {options.error}
        </div>
      )}

      {model && (
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
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <SummaryTile label="프로필" value={model.review.profileId} />
                <SummaryTile label="VM 이름" value={model.review.vmName} icon={Server} />
                <SummaryTile label="VMID" value={model.review.vmid} />
                <SummaryTile label="생성 노드" value={model.review.targetNode} icon={Server} />
                <SummaryTile label="IP" value={reviewedIpSummary} icon={Network} />
                <SummaryTile label="사양" value={`${model.review.hardware.cpu} CPU / ${model.review.hardware.memoryMb} MB / ${model.review.hardware.diskGb} GB`} />
                <SummaryTile label="스토리지" value={model.review.storage} />
                <SummaryTile label="템플릿" value={model.review.template} />
                <SummaryTile label="네트워크" value={`${selectedIpModeLabel} / ${model.review.network.bridge_id || model.review.network.bridgeId || form.bridgeId || ''}`} icon={Network} />
                <SummaryTile label="접속 사용자" value={reviewedAccess.username || reviewedAccess.cloudInitUser || form.cloudInitUser} icon={KeyRound} />
                <SummaryTile label="SSH 키" value={reviewedSshKeySummary} icon={KeyRound} />
                <SummaryTile label="첫 부팅" value={model.review.firstPowerOnIncluded ? '포함' : '별도 단계'} />
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-950">확인 항목</h3>
                <StatusPill tone={toneForRiskLevel(model.preflight.level)}>{riskLabel(model.preflight.level)}</StatusPill>
              </div>
              <div className="grid max-h-[28rem] gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                {model.preflight.checks.map((check) => (
                  <div key={check.code} className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 p-2 text-sm">
                    <span className="font-medium text-slate-800">{checkLabel(check.code)}</span>
                    <StatusPill tone={statusToneFromCheck(check)}>{checkStatusLabel(check)}</StatusPill>
                  </div>
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
              <DetailRow label="실행 조건" value={model.review.canCreateProxmox ? '승인 후 생성 가능' : '검토 항목 확인 필요'} />
              <DetailRow label="첫 부팅" value="생성 후 별도 시작" />
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="mb-3 font-semibold text-slate-950">다음 작업</h3>
              {model.review.riskLevel === 'yellow' && (
                <label className="mb-3 flex items-start gap-2 rounded-lg border border-yellow-200 bg-yellow-50 p-2 text-sm text-yellow-800">
                  <input type="checkbox" className="mt-1" checked={yellowRiskAcknowledged} onChange={(event) => setYellowRiskAcknowledged(event.target.checked)} />
                  확인 필요 항목을 검토했습니다.
                </label>
              )}
              <button type="button" onClick={approveReview} disabled={!model.review.canApprove || approving} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                검토 내용 승인
              </button>
              <label className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-800">
                <input type="checkbox" className="mt-1" checked={proxmoxMutationAcknowledged} onChange={(event) => setProxmoxMutationAcknowledged(event.target.checked)} />
                Proxmox에 꺼진 상태의 VM을 실제로 만드는 것을 승인합니다.
              </label>
              <button type="button" onClick={createWithProxmox} disabled={!approval?.canApprove || !model.review.canCreateProxmox || !proxmoxMutationAcknowledged || creating} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                Proxmox native create
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

      {model?.review?.riskLevel === 'red' && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          차단 항목이 있어 승인할 수 없습니다.
        </div>
      )}
    </div>
  )
}

export default CreateInstanceWizard
