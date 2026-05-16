import { buildJobsViewModel } from './apiV1ViewModels.js'

const READ_ONLY_ACTIONS = Object.freeze([])

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asText(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function firstValue(...values) {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return '-'
}

function normalizeArtifact(source = {}) {
  const storageBackend = asText(source.storage_backend ?? source.storageBackend, 'db')
  return {
    id: asText(source.artifact_id ?? source.id ?? source.name, 'unknown'),
    kind: asText(source.kind ?? source.type, 'artifact'),
    path: asText(source.path ?? source.href ?? source.url, '-'),
    storageBackend,
    sizeBytes: asNumber(source.size_bytes ?? source.sizeBytes, 0),
    checksum: source.sha256 ?? source.checksum ?? null,
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    raw: source,
  }
}

function normalizeSelectedJob(job) {
  if (!job) return null
  return buildJobsViewModel([job]).items[0] || null
}

function valueFromConfigString(configValue, key) {
  const text = String(configValue ?? '')
  const match = text.match(new RegExp(`(?:^|,)${key}=([^,]+)`))
  return match?.[1] || ''
}

function bridgeFromNet0(net0) {
  return valueFromConfigString(net0, 'bridge')
}

function ipDetailsFromConfig(ipconfig0) {
  const ip = valueFromConfigString(ipconfig0, 'ip')
  const gateway = valueFromConfigString(ipconfig0, 'gw')
  if (!ip || ip.toLowerCase() === 'dhcp') {
    return {
      mode: ip.toLowerCase() === 'dhcp' ? 'DHCP' : '-',
      requestedIp: ip.toLowerCase() === 'dhcp' ? 'DHCP 요청' : '-',
      gateway: gateway || 'DHCP에서 수신',
    }
  }
  const [address, prefix = ''] = ip.split('/')
  return {
    mode: '고정 IP',
    requestedIp: prefix ? `${address}/${prefix}` : address,
    gateway: gateway || '-',
  }
}

function formatMb(value) {
  const mb = asNumber(value, 0)
  if (!mb) return '-'
  if (mb % 1024 === 0) return `${mb / 1024} GB`
  return `${mb} MB`
}

function formatGb(value) {
  const gb = asNumber(value, 0)
  return gb ? `${gb} GB` : '-'
}

function yesNo(value) {
  if (value === true) return '예'
  if (value === false) return '아니오'
  return '-'
}

function agentLabel(value) {
  const text = String(value ?? '')
  if (!text) return '-'
  if (text.includes('enabled=1') || text === '1' || text.toLowerCase() === 'true') return '활성화 요청'
  return text
}

function observedAgentLabel(guestAgent = {}) {
  if (guestAgent.available === true) {
    const ips = asArray(guestAgent.ip_addresses ?? guestAgent.ipAddresses).filter(Boolean)
    return ips.length ? `확인됨 (${ips.join(', ')})` : '확인됨'
  }
  if (guestAgent.available === false) return '미확인'
  return '-'
}

function cloudInitLabel(cloudInit = {}) {
  if (cloudInit.success === true) return '완료'
  if (cloudInit.success === false) return asText(cloudInit.status, '미확인')
  return '-'
}

function createStatePolicyLabel(value) {
  const text = String(value ?? '').trim()
  if (text === 'boot_and_verify') return '부팅 후 확인'
  if (text === 'stopped') return '꺼진 상태로 생성'
  return text || '-'
}

function resizeLabel(resize = {}) {
  const action = String(resize.action ?? '').trim()
  if (!action) return '-'
  if (action === 'resized') return `완료 (${formatGb(resize.requested_disk_gb)})`
  if (action === 'not_needed') return '불필요'
  if (action === 'resize_required') return `필요 (${formatGb(resize.requested_disk_gb)})`
  if (action === 'failed') return '실패'
  if (action === 'skipped') return asText(resize.reason, '건너뜀')
  return action
}

function shortHash(value) {
  const text = String(value ?? '').trim()
  if (!text) return '-'
  if (text.startsWith('sha256:') && text.length > 18) return `${text.slice(0, 18)}...`
  return text
}

function parseTarget(targetId) {
  const [node = '', name = ''] = String(targetId ?? '').split(':')
  return { node, name }
}

function firstIpAddress(...sources) {
  for (const source of sources) {
    if (!source) continue
    const direct = source.primary_ip ?? source.primaryIp ?? source.ip ?? source.ip_address ?? source.ipAddress
    if (direct) return String(direct)
    const addresses = source.ip_addresses ?? source.ipAddresses ?? source.guest_agent?.ip_addresses ?? source.guestAgent?.ipAddresses
    const first = asArray(addresses).find(Boolean)
    if (first) return String(first)
  }
  return ''
}

function actualIpLabel({ observed, create, requestedMode }) {
  const statusCurrent = asObject(observed.status_current ?? observed.statusCurrent)
  const guestAgent = asObject(observed.guest_agent ?? observed.guestAgent)
  const actualIp = firstIpAddress(observed, statusCurrent, guestAgent, create)
  if (actualIp) return actualIp
  const status = String(create.status ?? observed.post_check_status ?? '').toLowerCase()
  if (status === 'failed' || status === 'apply_failed') return '생성 실패로 미확인'
  if (String(requestedMode).toLowerCase().includes('dhcp')) return '부팅 후 guest-agent로 확인'
  return '아직 관찰되지 않음'
}

function storageUnavailableAdvice({ create, clone }) {
  const task = asObject(create.task)
  const message = firstValue(
    asObject(task.response_json).message,
    task.reason,
    task.response_text,
    create.message
  )
  const match = String(message).match(/storage '([^']+)' is not available on node '([^']+)'/)
  if (!match) return null
  const storage = match[1]
  const sourceNode = match[2]
  const targetNode = firstValue(clone.target, create.target_node_id)
  return {
    title: '스토리지 조합 확인 필요',
    message: `선택한 스토리지 ${storage}를 템플릿 노드 ${sourceNode}에서 사용할 수 없어 clone이 시작되지 않았습니다.`,
    actions: [
      `${sourceNode}에서도 접근 가능한 shared storage를 선택합니다.`,
      `또는 ${targetNode}에 있는 템플릿을 선택합니다.`,
      `Proxmox storage 설정에서 ${storage}의 nodes 제한과 활성 상태를 확인합니다.`,
    ],
  }
}

function buildCreateAdvice({ create, clone }) {
  return storageUnavailableAdvice({ create, clone })
}

function buildCreateVmSummary(job, artifacts = []) {
  if (!job || !String(job.type ?? '').startsWith('vm_create')) return null

  const details = asObject(job.raw?.details)
  const draft = asObject(details.draft)
  const preflight = asObject(details.preflight)
  const preview = asObject(details.proxmox_preview)
  const create = asObject(details.proxmox_create)
  const observed = asObject(create.observed_after ?? details.observed_after)
  const observedConfig = asObject(observed.config)
  const config = asObject(preview.config ?? create.config ?? observedConfig)
  const clone = asObject(preview.clone ?? create.clone)
  const network = asObject(details.network ?? draft.network)
  const hardware = asObject(details.hardware ?? draft.hardware)
  const access = asObject(details.access ?? draft.access ?? preflight.access)
  const target = parseTarget(job.targetId)
  const ipConfig = ipDetailsFromConfig(config.ipconfig0)
  const resize = asObject(create.resize)
  const advice = buildCreateAdvice({ create, clone })
  const guestAgent = asObject(observed.guest_agent ?? observed.guestAgent ?? create.guest_agent ?? create.guestAgent)
  const cloudInit = asObject(observed.cloud_init ?? observed.cloudInit ?? create.cloud_init ?? create.cloudInit)
  const bootVerification = asObject(observed.boot_verification ?? observed.bootVerification ?? create.boot_verification ?? create.bootVerification)
  const startTask = asObject(create.start_task ?? create.startTask ?? observed.start_task ?? observed.startTask)

  const vmName = firstValue(details.vm_name, preview.vm_name, observed.vm_name, draft.vm_name, target.name)
  const vmid = firstValue(details.vmid, preview.vmid, create.vmid, observed.vmid, draft.proposed_vmid)
  const targetNode = firstValue(details.target_node_id, preview.target_node_id, create.target_node_id, observed.target_node_id, draft.target_node_id, target.node)
  const bridge = firstValue(network.bridge_id, preflight.selected_bridge_id, bridgeFromNet0(config.net0))
  const ipMode = firstValue(network.ip_mode === 'static' ? '고정 IP' : network.ip_mode === 'dhcp' ? 'DHCP' : network.ip_mode, ipConfig.mode)
  const requestedIp = firstValue(
    network.static_ip && network.prefix ? `${network.static_ip}/${network.prefix}` : network.static_ip,
    ipConfig.requestedIp
  )
  const gateway = firstValue(network.gateway, ipConfig.gateway)
  const actualIp = actualIpLabel({ observed, create, requestedMode: ipMode })
  const diskGb = firstValue(hardware.disk_gb, hardware.diskGb, resize.requested_disk_gb)
  const status = firstValue(observed.status, create.status, job.status)
  const createStatePolicy = firstValue(observed.power_policy, create.power_policy, details.power_policy, preview.power_policy)
  const cloudInitUser = firstValue(access.cloud_init_user, access.cloudInitUser, config.ciuser)
  const sshConfigured = Boolean(config.sshkeys || access.ssh_key_fingerprint || access.sshKeyFingerprint || access.ssh_public_key_source)
  const passwordLoginDisabled = access.password_login_disabled ?? access.passwordLoginDisabled
  const fingerprint = asObject(observed.fingerprint)

  return {
    title: vmName !== '-' ? `${vmName} 생성 요약` : '생성 VM 요약',
    subtitle: `VMID ${vmid} · ${targetNode}`,
    status,
    advice,
    artifactCount: artifacts.length,
    sections: [
      {
        title: 'VM',
        items: [
          { label: '이름', value: vmName },
          { label: 'VMID', value: vmid },
          { label: '노드', value: targetNode },
          { label: '현재 상태', value: status },
        ],
      },
      {
        title: '리소스',
        items: [
          { label: 'CPU', value: firstValue(config.cores, hardware.cpu_cores, hardware.cpuCores) },
          { label: '메모리', value: formatMb(firstValue(config.memory, hardware.memory_mb, hardware.memoryMb)) },
          { label: '디스크', value: formatGb(diskGb) },
          { label: '스토리지', value: firstValue(clone.storage, details.storage_id, draft.storage_id) },
          { label: '템플릿', value: firstValue(details.template_id, draft.template_id, clone.template_vmid) },
        ],
      },
      {
        title: '네트워크',
        items: [
          { label: '브릿지', value: bridge },
          { label: '주소 방식', value: ipMode },
          { label: '요청 IP', value: requestedIp },
          { label: '관찰 IP', value: actualIp },
          { label: '게이트웨이', value: gateway },
        ],
      },
      {
        title: 'Cloud-init / Agent',
        items: [
          { label: '접속 사용자', value: cloudInitUser },
          { label: 'SSH 키', value: sshConfigured ? '주입됨' : '-' },
          { label: '비밀번호 로그인', value: passwordLoginDisabled === true ? '비활성화' : yesNo(passwordLoginDisabled) },
          { label: 'QEMU agent', value: agentLabel(config.agent) },
          { label: 'Agent 관찰', value: observedAgentLabel(guestAgent) },
          { label: 'Cloud-init 확인', value: cloudInitLabel(cloudInit) },
        ],
      },
      {
        title: '생성 확인',
        items: [
          { label: '생성 후 상태', value: createStatePolicyLabel(createStatePolicy) },
          { label: 'Clone task', value: firstValue(create.task?.exitstatus, create.task?.status) },
          { label: 'Start task', value: firstValue(startTask.exitstatus, startTask.status) },
          { label: '디스크 resize', value: resizeLabel(resize) },
          { label: 'Post-check', value: firstValue(bootVerification.success === true ? '부팅 확인 완료' : '', observed.post_check_status, create.status) },
          { label: 'Fingerprint', value: shortHash(fingerprint.hash) },
        ],
      },
    ],
  }
}

function firstJobId(model) {
  return model.items[0]?.id && model.items[0].id !== 'unknown' ? model.items[0].id : null
}

export async function loadJobsScreenModel(client, { selectedJobId = null } = {}) {
  if (!client || typeof client.listJobs !== 'function') {
    throw new Error('Jobs screen requires an /api/v1 client with listJobs()')
  }

  const jobs = await client.listJobs()
  const jobsModel = buildJobsViewModel(jobs)
  const jobId = selectedJobId || firstJobId(jobsModel)

  let selectedJob = null
  let artifacts = []
  if (jobId) {
    const detail = typeof client.getJob === 'function'
      ? await client.getJob(jobId)
      : asArray(jobs).find((job) => String(job.job_id ?? job.id) === String(jobId))
    selectedJob = normalizeSelectedJob(detail)

    if (typeof client.listJobArtifacts === 'function') {
      artifacts = asArray(await client.listJobArtifacts(jobId)).map(normalizeArtifact)
    }
  }

  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    summary: jobsModel.summary,
    jobs: jobsModel.items,
    selectedJob: selectedJob
      ? {
        ...selectedJob,
        vmSummary: buildCreateVmSummary(selectedJob, artifacts),
      }
      : null,
    artifacts,
  }
}

export function formatJobTimestamp(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

export function statusToneClass(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'green' || normalized === 'completed' || normalized === 'success') return 'bg-green-50 text-green-700 border-green-200'
  if (normalized === 'yellow' || normalized === 'running' || normalized === 'pending' || normalized === 'in_progress') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (normalized === 'red' || normalized === 'failed' || normalized === 'error' || normalized === 'blocked') return 'bg-red-50 text-red-700 border-red-200'
  return 'bg-slate-50 text-slate-700 border-slate-200'
}
