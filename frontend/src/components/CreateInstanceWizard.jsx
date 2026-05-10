import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ClipboardCheck, FileText, FolderGit2, Loader2, Network, Rocket, Server, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { apiV1Client } from '../services/apiV1'
import { buildCreateVmDefaults } from '../utils/createVmDefaults'
import { buildNetworkPolicyModel } from '../utils/networkPolicy'
import {
  approveCreateVmReview,
  applyCreateVmTerraformPlan,
  buildCreateVmInputFromConfig,
  commitCreateVmManifest,
  loadCreateVmReviewModel,
  prepareCreateVmTerraformPlan,
} from '../utils/createVmFlow'

const CHECK_LABELS = {
  profile_schema: '프로필',
  template_available: '템플릿',
  template_matches_profile: '템플릿 프로필',
  template_cloud_init_ready: 'Cloud-init',
  template_guest_agent_ready: 'Guest agent',
  target_node_online: '노드 상태',
  storage_available: '스토리지',
  bridge_mapping: '네트워크 매핑',
  bridge_exists: '브리지',
  network_policy_registered: '네트워크 정책',
  static_ip_range_configured: '고정 IP 범위',
  static_ip_in_policy_range: 'IP 범위 확인',
  vmid_available: 'VMID',
  name_available: 'VM 이름',
  static_ip_available: '고정 IP',
  shared_root_available: '공유 폴더',
  iac_root_available: '코드 저장소',
  iac_root_writable: '코드 저장소 쓰기',
  iac_git_repo_available: 'Git 저장소',
  iac_write_allowlist_ready: '쓰기 경로',
  terraform_state_root_available: '상태 저장소',
  terraform_state_root_writable: '상태 저장소 쓰기',
  terraform_state_lock_available: '상태 잠금',
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

function StepIndicator({ model, approval, terraformPlanResult, commitResult, applyResult }) {
  const steps = [
    { label: '요청 입력', done: true, active: !model },
    { label: '검토', done: Boolean(model), active: Boolean(model) && !approval },
    { label: '승인', done: Boolean(approval?.canApprove), active: Boolean(approval) && !terraformPlanResult && !commitResult && !applyResult },
    { label: '생성 준비', done: Boolean(terraformPlanResult || commitResult), active: Boolean(terraformPlanResult || commitResult) && !applyResult },
    { label: '생성 실행', done: Boolean(applyResult), active: Boolean(applyResult) },
  ]
  return (
    <div className="grid gap-2 sm:grid-cols-5">
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

function manifestPhaseLabel(phase) {
  if (phase === 'pending') return '대기'
  if (phase === 'planned') return '검토됨'
  if (phase === 'applying') return '생성 중'
  if (phase === 'apply_failed') return '생성 실패'
  if (phase === 'applied') return '생성 완료'
  if (phase === 'archived') return '보관됨'
  return phase || '대기'
}

function toneForManifestPhase(phase) {
  if (phase === 'applied') return 'green'
  if (phase === 'apply_failed') return 'red'
  if (phase === 'applying' || phase === 'planned') return 'blue'
  if (phase === 'archived') return 'slate'
  return 'yellow'
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

function normalizeTemplateOptions(templates = []) {
  return Array.isArray(templates)
    ? templates
      .map((template) => {
        const vmid = template.vmid ?? template.template_vmid
        const nodeId = template.node_id || template.nodeId || ''
        const templateId = template.template_id || template.templateId || template.name || ''
        return {
          key: nodeId && vmid ? `${nodeId}/${vmid}` : templateId,
          templateId,
          vmid,
          nodeId,
          name: template.name || templateId,
          family: template.family || '',
          ready: template.cloud_init_ready !== false && template.guest_agent_ready !== false,
        }
      })
      .filter((template) => template.key)
      .sort((left, right) => `${left.nodeId}/${left.vmid}`.localeCompare(`${right.nodeId}/${right.vmid}`, undefined, { numeric: true }))
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

function storageLabel(storage) {
  const free = Number.isFinite(storage.freeGb) ? `${storage.freeGb} GB free` : ''
  return [storage.id, storage.type, free].filter(Boolean).join(' · ')
}

function selectPreferredStorage(storages, nodeId, currentStorageId = '') {
  const candidates = (storages || []).filter((storage) => storage.nodeId === nodeId && storage.content.includes('images') && storage.freeGb > 0)
  if (!candidates.length) return null
  return candidates.find((storage) => storage.id === currentStorageId)
    || candidates.find((storage) => storage.type === 'nfs')
    || candidates[0]
}

function bridgeLabel(bridge) {
  const status = bridge.registered ? '등록됨' : '미등록'
  const name = bridge.displayName || bridge.networkId || ''
  const parts = [name, bridge.bridgeId, bridge.subnet, status].filter(Boolean)
  return parts.join(' · ')
}

function selectPreferredBridge(model, nodeId, currentBridgeId = '') {
  const bridges = (model?.bridges || []).filter((bridge) => bridge.nodeId === nodeId && bridge.active)
  if (!bridges.length) return null
  return bridges.find((bridge) => bridge.bridgeId === currentBridgeId)
    || bridges.find((bridge) => bridge.registered)
    || bridges[0]
}

function firstRangeStart(bridge) {
  const range = bridge?.staticIpRanges?.find((item) => item?.start)
  return range?.start || '192.168.2.149'
}

function buildInitialForm(config) {
  const defaults = buildCreateVmDefaults()
  const now = new Date()
  const datePart = now.toISOString().slice(0, 10).replaceAll('-', '')
  const timePart = now.toTimeString().slice(0, 8).replaceAll(':', '')
  const input = buildCreateVmInputFromConfig(config, {
    operatorId: 'ui-operator',
    jobId: `ui-${datePart}-${timePart}`,
    targetNodeId: 'yoonmanserver2',
    networkId: defaults.network.networkId,
    bridgeId: defaults.network.nodeBridges.yoonmanserver2,
    storageId: '',
    staticIp: '',
    ipMode: defaults.network.ipMode,
  })
  return {
    ...input,
    profileId: defaults.profileId,
    hardware: defaults.hardware,
    storageId: input.storageId || '',
    networkId: input.networkId || defaults.network.networkId,
    bridgeId: input.bridgeId || defaults.network.nodeBridges[input.targetNodeId] || '',
  }
}

function CreateInstanceWizard({ config = {}, onConfigChange = () => {} }) {
  const navigate = useNavigate()
  const [form, setForm] = useState(() => buildInitialForm(config))
  const [model, setModel] = useState(null)
  const [approval, setApproval] = useState(null)
  const [terraformPlanResult, setTerraformPlanResult] = useState(null)
  const [commitResult, setCommitResult] = useState(null)
  const [applyResult, setApplyResult] = useState(null)
  const [yellowRiskAcknowledged, setYellowRiskAcknowledged] = useState(false)
  const [terraformPlanRunAcknowledged, setTerraformPlanRunAcknowledged] = useState(false)
  const [terraformApplyAcknowledged, setTerraformApplyAcknowledged] = useState(false)
  const [loading, setLoading] = useState(false)
  const [approving, setApproving] = useState(false)
  const [preparingTerraform, setPreparingTerraform] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState(null)
  const [options, setOptions] = useState({ nodes: [], templates: [], storages: [], networkPolicy: null, loading: true, error: null })

  const reviewRiskTone = useMemo(() => {
    const level = model?.review?.riskLevel || model?.preflight?.level
    return toneForRiskLevel(level)
  }, [model])

  const nodeOptions = useMemo(() => normalizeNodeOptions(options.nodes), [options.nodes])
  const templateOptions = useMemo(() => normalizeTemplateOptions(options.templates), [options.templates])
  const storageOptions = useMemo(() => normalizeStorageOptions(options.storages), [options.storages])
  const networkPolicyModel = useMemo(() => buildNetworkPolicyModel(options.networkPolicy || {}), [options.networkPolicy])
  const nodeStorageOptions = useMemo(
    () => storageOptions.filter((storage) => storage.nodeId === form.targetNodeId && storage.content.includes('images') && storage.freeGb > 0),
    [storageOptions, form.targetNodeId],
  )
  const bridgeOptions = useMemo(
    () => (networkPolicyModel.bridges || []).filter((bridge) => bridge.nodeId === form.targetNodeId && bridge.active),
    [networkPolicyModel, form.targetNodeId],
  )
  const selectedTemplateKey = form.templateKey || (form.templateNodeId && form.templateVmid ? `${form.templateNodeId}/${form.templateVmid}` : form.templateId)
  const selectedBridge = bridgeOptions.find((bridge) => bridge.bridgeId === form.bridgeId) || null
  const selectedIpModeLabel = form.ipMode === 'dhcp' ? 'DHCP' : '고정 IP'
  const hardware = form.hardware || {}
  const memoryMb = hardware.memoryMb || hardware.memory_mb || 4096
  const diskGb = hardware.diskGb || hardware.disk_gb || 40
  const staticIpPlaceholder = firstRangeStart(selectedBridge)

  useEffect(() => {
    let cancelled = false
    async function loadOptions() {
      try {
        const [nodes, templates, storages, networkPolicy] = await Promise.all([
          apiV1Client.listNodes(),
          apiV1Client.listTemplates(),
          apiV1Client.listStorage(),
          apiV1Client.getNetworkPolicy(),
        ])
        if (!cancelled) {
          setOptions({ nodes, templates, storages, networkPolicy, loading: false, error: null })
        }
      } catch (err) {
        if (!cancelled) {
          setOptions((current) => ({
            ...current,
            loading: false,
            error: err?.message || '생성 옵션을 불러오지 못했습니다.',
          }))
        }
      }
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
    setTerraformPlanResult(null)
    setCommitResult(null)
    setApplyResult(null)
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
      const template = templateOptions.find((item) => item.key === (next.templateKey || selectedTemplateKey)) || templateOptions[0]
      if (template && !next.templateKey && !next.templateVmid && !next.templateId) {
        next.templateKey = template.key
        next.templateId = template.templateId
        next.templateVmid = template.vmid
        next.templateNodeId = template.nodeId
        changed = true
      }
      const storage = selectPreferredStorage(storageOptions, next.targetNodeId, next.storageId)
      if (storage && (!next.storageId || next.storageId !== storage.id)) {
        next.storageId = storage.id
        changed = true
      }
      const bridge = selectPreferredBridge(networkPolicyModel, next.targetNodeId, next.bridgeId)
      if (bridge && (!next.bridgeId || next.bridgeId !== bridge.bridgeId || !next.networkId)) {
        next.bridgeId = bridge.bridgeId
        next.networkId = bridge.networkId || next.networkId || 'server-net'
        changed = true
      }
      if (bridge && next.ipMode === 'static' && !next.staticIp) {
        next.staticIp = firstRangeStart(bridge)
        changed = true
      }
      if (changed) onConfigChange(next)
      return changed ? next : current
    })
  }, [nodeOptions, templateOptions, storageOptions, networkPolicyModel, options.loading, onConfigChange, selectedTemplateKey])

  const handleNodeChange = (nodeId) => {
    const bridge = selectPreferredBridge(networkPolicyModel, nodeId)
    const storage = selectPreferredStorage(storageOptions, nodeId)
    applyFormPatch({
      targetNodeId: nodeId,
      storageId: storage?.id || '',
      bridgeId: bridge?.bridgeId || '',
      networkId: bridge?.networkId || form.networkId || 'server-net',
      staticIp: form.ipMode === 'static' && !form.staticIp ? firstRangeStart(bridge) : form.staticIp,
    })
  }

  const handleTemplateChange = (templateKey) => {
    const template = templateOptions.find((item) => item.key === templateKey)
    applyFormPatch({
      templateKey,
      templateId: template?.templateId || '',
      templateVmid: template?.vmid || '',
      templateNodeId: template?.nodeId || '',
    })
  }

  const handleBridgeChange = (bridgeId) => {
    const bridge = bridgeOptions.find((item) => item.bridgeId === bridgeId)
    applyFormPatch({
      bridgeId,
      networkId: bridge?.networkId || form.networkId || 'server-net',
      staticIp: form.ipMode === 'static' && !form.staticIp ? firstRangeStart(bridge) : form.staticIp,
    })
  }

  const runReview = async () => {
    setLoading(true)
    setError(null)
    setApproval(null)
    setTerraformPlanResult(null)
    setCommitResult(null)
    setApplyResult(null)
    setTerraformPlanRunAcknowledged(false)
    setTerraformApplyAcknowledged(false)
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

  const prepareTerraformPlan = async ({ runPlan = false } = {}) => {
    if (!approval?.canApprove || !model?.review?.canPrepareTerraformPlan) return
    setPreparingTerraform(true)
    setError(null)
    try {
      const result = await prepareCreateVmTerraformPlan(apiV1Client, model, {
        yellowRiskAcknowledged,
        runTerraformPlan: runPlan,
        terraformPlanAcknowledged: runPlan && terraformPlanRunAcknowledged,
      })
      setTerraformPlanResult(result)
    } catch (err) {
      setError(err?.message || 'Terraform 파일 준비에 실패했습니다.')
      setTerraformPlanResult(null)
    } finally {
      setPreparingTerraform(false)
    }
  }

  const commitManifest = async () => {
    if (!approval?.canApprove || !model?.review?.canCommitManifest) return
    setCommitting(true)
    setError(null)
    try {
      const result = await commitCreateVmManifest(apiV1Client, model, { yellowRiskAcknowledged })
      setCommitResult(result)
    } catch (err) {
      setError(err?.message || '생성 요청 커밋에 실패했습니다.')
      setCommitResult(null)
    } finally {
      setCommitting(false)
    }
  }

  const applyTerraformPlan = async () => {
    if (!approval?.canApprove || !model?.review?.canApplyTerraform || !terraformPlanResult?.planRan || !commitResult?.commitSha) return
    setApplying(true)
    setError(null)
    const jobId = model?.draft?.jobId || form.jobId
    const applyPromise = applyCreateVmTerraformPlan(apiV1Client, model, {
      yellowRiskAcknowledged,
      manifestCommitSha: commitResult.commitSha,
      expectedPlanPath: terraformPlanResult.planPath,
      terraformPlanAcknowledged: terraformPlanResult.planRan === true,
      terraformApplyAcknowledged,
      proxmoxMutationAcknowledged: terraformApplyAcknowledged,
    })
    navigate(`/jobs?job=${encodeURIComponent(jobId)}`)
    try {
      const result = await applyPromise
      setApplyResult(result)
    } catch (err) {
      setError(err?.message || 'VM 생성 apply에 실패했습니다.')
      const status = err?.details?.manifest_status
      setApplyResult(status ? {
        status: status.phase || 'apply_failed',
        tone: 'red',
        statePath: '',
        manifestStatus: status,
        operatorMessage: 'VM 생성 실패 상태가 IaC에 기록되었습니다.',
      } : null)
    } finally {
      setApplying(false)
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
              <StatusPill tone="slate">general-vm</StatusPill>
              <StatusPill tone="slate">{hardware.cpu || 2} CPU</StatusPill>
              <StatusPill tone="slate">{memoryMb} MB</StatusPill>
              <StatusPill tone="slate">{diskGb} GB</StatusPill>
            </div>
          </div>
          <StatusPill tone="blue">생성 전 검토</StatusPill>
        </div>

        <div className="mt-5">
          <StepIndicator model={model} approval={approval} terraformPlanResult={terraformPlanResult} commitResult={commitResult} applyResult={applyResult} />
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
              {templateOptions.map((template) => (
                <option key={template.key} value={template.key}>
                  {template.name} · {template.nodeId}/{template.vmid}
                </option>
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
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" onClick={runReview} disabled={loading || options.loading} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
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
                <SummaryTile label="VM 이름" value={model.review.vmName} icon={Server} />
                <SummaryTile label="VMID" value={model.review.vmid} />
                <SummaryTile label="생성 노드" value={model.review.targetNode} icon={Server} />
                <SummaryTile label="IP" value={model.review.network.ip_address || model.review.network.ipAddress || form.staticIp || selectedIpModeLabel} icon={Network} />
                <SummaryTile label="사양" value={`${model.review.hardware.cpu} CPU / ${model.review.hardware.memoryMb} MB / ${model.review.hardware.diskGb} GB`} />
                <SummaryTile label="스토리지" value={model.review.storage} />
                <SummaryTile label="템플릿" value={model.review.template} />
                <SummaryTile label="네트워크" value={`${selectedIpModeLabel} / ${model.review.network.bridge_id || model.review.network.bridgeId || 'vmbr0'}`} icon={Network} />
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
                  <FolderGit2 className="h-5 w-5 text-slate-600" />
                  <h3 className="font-semibold text-slate-950">생성 준비 상태</h3>
                </div>
                <StatusPill tone={toneForRiskLevel(model.readiness?.riskLevel)}>{riskLabel(model.readiness?.riskLevel)}</StatusPill>
              </div>
              <DetailRow label="코드 저장소" value={model.readiness?.readyForExecute ? '준비됨' : '확인 필요'} />
              <DetailRow label="Terraform 준비" value={model.readiness?.readyForPlan ? '가능' : '차단'} />
              <DetailRow label="상태 저장소" value={model.review.terraformStateRoot} />
              <DetailRow label="요청 저장 위치" value={model.review.iacRoot} />
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
              <button type="button" onClick={() => prepareTerraformPlan()} disabled={!approval?.canApprove || !model.review.canPrepareTerraformPlan || preparingTerraform} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {preparingTerraform ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                실행 준비 파일 만들기
              </button>
              <label className="mt-3 flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 p-2 text-sm text-blue-800">
                <input type="checkbox" className="mt-1" checked={terraformPlanRunAcknowledged} onChange={(event) => setTerraformPlanRunAcknowledged(event.target.checked)} />
                Proxmox 현재 상태를 읽어 생성 변경 미리보기를 만드는 것을 승인합니다.
              </label>
              <button type="button" onClick={() => prepareTerraformPlan({ runPlan: true })} disabled={!approval?.canApprove || !model.review.canPrepareTerraformPlan || !terraformPlanRunAcknowledged || preparingTerraform} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {preparingTerraform ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                생성 변경 미리보기
              </button>
              <button type="button" onClick={commitManifest} disabled={!approval?.canApprove || !model.review.canCommitManifest || committing} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {committing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderGit2 className="h-4 w-4" />}
                생성 요청 저장
              </button>
              <label className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-800">
                <input type="checkbox" className="mt-1" checked={terraformApplyAcknowledged} onChange={(event) => setTerraformApplyAcknowledged(event.target.checked)} />
                Proxmox에 꺼진 상태의 VM을 실제로 만드는 것을 승인합니다.
              </label>
              <button type="button" onClick={applyTerraformPlan} disabled={!approval?.canApprove || !model.review.canApplyTerraform || !terraformPlanResult?.planRan || !commitResult?.commitSha || !terraformApplyAcknowledged || applying} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                꺼진 상태로 VM 만들기
              </button>
              {approval && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${approvalToneClass(approval)}`}>
                  {approval.operatorMessage}
                </div>
              )}
              {terraformPlanResult && (
                <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
                  <div>{terraformPlanResult.operatorMessage}</div>
                  <div className="mt-1 break-all text-xs text-blue-600">{terraformPlanResult.terraformDir}</div>
                  {terraformPlanResult.planRan && (
                    <div className="mt-1 text-xs font-medium text-blue-700">plan 파일: {terraformPlanResult.planPath}</div>
                  )}
                </div>
              )}
              {commitResult && (
                <div className="mt-3 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
                  <div>{commitResult.operatorMessage}</div>
                  {commitResult.manifestStatus?.phase && (
                    <div className="mt-2"><StatusPill tone={toneForManifestPhase(commitResult.manifestStatus.phase)}>상태: {manifestPhaseLabel(commitResult.manifestStatus.phase)}</StatusPill></div>
                  )}
                  <div className="mt-1 break-all text-xs text-green-600">{commitResult.commitSha}</div>
                </div>
              )}
              {applyResult && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${applyResult.status === 'applied' ? 'border-green-200 bg-green-50 text-green-700' : 'border-red-200 bg-red-50 text-red-700'}`}>
                  <div>{applyResult.operatorMessage}</div>
                  {applyResult.manifestStatus?.phase && (
                    <div className="mt-2"><StatusPill tone={toneForManifestPhase(applyResult.manifestStatus.phase)}>상태: {manifestPhaseLabel(applyResult.manifestStatus.phase)}</StatusPill></div>
                  )}
                  <div className={`mt-1 break-all text-xs ${applyResult.status === 'applied' ? 'text-green-600' : 'text-red-600'}`}>{applyResult.statePath}</div>
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
