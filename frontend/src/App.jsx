import { useEffect, useMemo, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, AlertTriangle, CheckCircle2, Clock3, Database, HardDrive, KeyRound, LayoutDashboard, List, LogOut, Network, Plus, RefreshCw, Server, UserCircle, UserCog } from 'lucide-react'
import AdminUsersScreen from './components/AdminUsersScreen'
import CreateInstanceWizard from './components/CreateInstanceWizard'
import InstanceList from './components/InstanceList'
import NetworkReadinessScreen from './components/NetworkReadinessScreen'
import OperationalRiskDashboard from './components/OperationalRiskDashboard'
import DrsAdvisorScreen from './components/DrsAdvisorScreen'
import TaskBoard from './components/TaskBoard'
import { apiV1Client } from './services/apiV1'
import { authFailureMessage, canAdmin, canOperate } from './utils/auth'
import middlepiaStackLogo from './assets/middlepia-stack.svg'

const navItems = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard, end: true },
  { label: 'Infra Explorer', path: '/infra', icon: List },
  { label: 'Networks', path: '/networks', icon: Network },
  { label: 'Create VM', path: '/create', icon: Plus },
  { label: 'DRS Advisor', path: '/drs', icon: Activity },
  { label: 'Jobs/Runs', path: '/jobs', icon: Clock3 },
  { label: 'Risks/Alerts', path: '/risks', icon: AlertTriangle },
]
const adminNavItem = { label: 'Admin Users', path: '/admin/users', icon: UserCog }
const accountNavItem = { label: 'Account', path: '/account', icon: UserCircle }

const DASHBOARD_DATA_LABELS = ['Cluster', 'Nodes', 'VMs', 'Storage', 'Networks', 'Jobs/Runs', 'Risks/Alerts']

function navClass({ isActive }) {
  return `flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
    isActive
      ? 'text-slate-900 border-slate-900 bg-slate-50'
      : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
  }`
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function settledValue(result, fallback) {
  return result.status === 'fulfilled' ? result.value : fallback
}

function dashboardPartialError(results) {
  const failed = results
    .map((result, index) => (result.status === 'rejected' ? DASHBOARD_DATA_LABELS[index] : null))
    .filter(Boolean)
  return failed.length
    ? `일부 Dashboard 데이터를 불러오지 못했습니다: ${failed.join(', ')}. 사용 가능한 inventory 데이터는 계속 표시합니다.`
    : null
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function optionalNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function nodeIdOf(node) {
  return node.node_id || node.nodeId || node.id || node.name || 'unknown'
}

function nodeNameOf(node) {
  return node.display_name || node.displayName || node.name || nodeIdOf(node)
}

function statusTone(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'online' || normalized === 'running') return 'green'
  if (normalized === 'offline' || normalized === 'failed') return 'red'
  return 'yellow'
}

function toneClasses(tone) {
  const tones = {
    green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800',
    red: 'border-red-200 bg-red-50 text-red-700',
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return tones[tone] || tones.slate
}

function formatGb(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '-'
  return `${Math.round(number).toLocaleString()} GB`
}

function metricValueClass(tone) {
  if (tone === 'green') return 'text-emerald-600'
  if (tone === 'yellow') return 'text-yellow-700'
  if (tone === 'red') return 'text-red-600'
  return 'text-slate-950'
}

function MetricTile({ label, value, sub, tone = 'slate', icon: Icon }) {
  return (
    <div className="min-h-28 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
        {Icon && <Icon className="h-4 w-4 text-slate-400" />}
      </div>
      <div className={`mt-4 text-3xl font-bold ${metricValueClass(tone)}`}>{value}</div>
      {sub && <div className="mt-1 truncate text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

function UsageBar({ value, tone = 'blue' }) {
  const color = tone === 'green' ? 'bg-emerald-500' : tone === 'red' ? 'bg-red-500' : tone === 'yellow' ? 'bg-yellow-500' : 'bg-blue-500'
  const width = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
  return (
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
    </div>
  )
}

function buildDashboardModel({ cluster = {}, nodes = [], vms = [], storages = [], networks = [], jobs = [], risks = [] }) {
  const nodeRows = asArray(nodes).map((node) => {
    const id = nodeIdOf(node)
    const nodeVms = asArray(vms).filter((vm) => (vm.node_id || vm.nodeId || vm.node) === id)
    const nodeStorages = asArray(node.storage).length ? asArray(node.storage) : asArray(storages).filter((storage) => (storage.node_id || storage.nodeId) === id)
    const nodeNetworks = asArray(node.networks).length ? asArray(node.networks) : asArray(networks).filter((network) => (network.node_id || network.nodeId) === id)
    const memoryTotalGb = asNumber(node.memory_total_mb ?? node.memoryTotalMb) / 1024
    const cpuUsagePercent = optionalNumber(node.cpu_usage_percent ?? node.cpuUsagePercent)
    const memoryUsedGb = asNumber(node.memory_used_mb ?? node.memoryUsedMb) / 1024
    const memoryUsagePercent = optionalNumber(node.memory_usage_percent ?? node.memoryUsagePercent)
    const storageTotalGb = nodeStorages.reduce((sum, storage) => sum + Math.max(0, asNumber(storage.total_gb ?? storage.totalGb)), 0)
    const storageFreeGb = nodeStorages.reduce((sum, storage) => sum + Math.max(0, asNumber(storage.free_gb ?? storage.freeGb)), 0)
    return {
      id,
      name: nodeNameOf(node),
      status: node.status || 'unknown',
      tone: statusTone(node.status),
      vmCount: nodeVms.length,
      runningVmCount: nodeVms.filter((vm) => String(vm.status || '').toLowerCase() === 'running').length,
      cpuLabel: cpuUsagePercent !== null ? `${Math.round(cpuUsagePercent)}%` : '-',
      cpuPercent: cpuUsagePercent !== null ? cpuUsagePercent : Number.NaN,
      memoryLabel: memoryUsagePercent !== null && memoryTotalGb > 0
        ? `${Math.round(memoryUsedGb)} / ${Math.round(memoryTotalGb)} GB`
        : '-',
      memoryPercent: memoryUsagePercent !== null ? memoryUsagePercent : Number.NaN,
      storageLabel: storageTotalGb > 0 ? `${formatGb(storageFreeGb)} free` : '-',
      networks: nodeNetworks.map((network) => network.bridge_id || network.bridgeId).filter(Boolean),
    }
  })

  const onlineNodes = nodeRows.filter((node) => node.tone === 'green').length
  const runningVms = asArray(vms).filter((vm) => String(vm.status || '').toLowerCase() === 'running').length
  const storageTotalGb = asArray(storages).reduce((sum, storage) => sum + Math.max(0, asNumber(storage.total_gb ?? storage.totalGb)), 0)
  const storageFreeGb = asArray(storages).reduce((sum, storage) => sum + Math.max(0, asNumber(storage.free_gb ?? storage.freeGb)), 0)
  const hasNfs = asArray(storages).some((storage) => String(storage.type || '').toLowerCase() === 'nfs')
  const bridgeCount = new Set(asArray(networks).map((network) => `${network.node_id || network.nodeId}:${network.bridge_id || network.bridgeId}`).filter(Boolean)).size

  return {
    clusterId: cluster.cluster_id || 'gjallar-mvp',
    nodeRows,
    summary: {
      nodes: `${onlineNodes}/${nodeRows.length}`,
      quorum: onlineNodes === nodeRows.length && nodeRows.length > 0 ? 'OK' : 'Check',
      vms: String(asArray(vms).length),
      runningVms,
      storage: hasNfs ? 'NFS' : `${Math.max(0, Math.round(storageTotalGb - storageFreeGb)).toLocaleString()} GB`,
      storageSub: storageTotalGb > 0 ? `${formatGb(storageFreeGb)} free` : 'storage inventory',
      bridges: bridgeCount,
      activeJobs: asArray(jobs).filter((job) => ['running', 'pending', 'in_progress', 'processing'].includes(String(job.status || '').toLowerCase())).length,
      redRisks: asArray(risks).filter((risk) => String(risk.level || risk.risk_level || '').toLowerCase() === 'red').length,
    },
  }
}

function Dashboard() {
  const navigate = useNavigate()
  const [snapshot, setSnapshot] = useState({
    cluster: {},
    nodes: [],
    vms: [],
    storages: [],
    networks: [],
    jobs: [],
    risks: [],
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadDashboard = async () => {
    setLoading(true)
    setError(null)
    const results = await Promise.allSettled([
      apiV1Client.clusterSummary(),
      apiV1Client.listNodes(),
      apiV1Client.listVms(),
      apiV1Client.listStorage(),
      apiV1Client.listNetworks(),
      apiV1Client.listJobs(),
      apiV1Client.listRisks(),
    ])
    const [cluster, nodes, vms, storages, networks, jobs, risks] = results
    setSnapshot((previous) => ({
      cluster: settledValue(cluster, previous.cluster || {}),
      nodes: settledValue(nodes, previous.nodes || []),
      vms: settledValue(vms, previous.vms || []),
      storages: settledValue(storages, previous.storages || []),
      networks: settledValue(networks, previous.networks || []),
      jobs: settledValue(jobs, previous.jobs || []),
      risks: settledValue(risks, previous.risks || []),
    }))
    setError(dashboardPartialError(results))
    setLoading(false)
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  const model = useMemo(() => buildDashboardModel(snapshot), [snapshot])
  const healthTone = model.summary.quorum === 'OK' && model.summary.redRisks === 0 ? 'green' : 'yellow'

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${toneClasses(healthTone)}`}>
              Cluster {model.summary.quorum}
            </span>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live read-only</span>
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">Proxmox 클러스터 운영 화면</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={loadDashboard} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            새로고침
          </button>
          <button type="button" onClick={() => navigate('/infra')} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <List className="h-4 w-4" />
            Infra Explorer
          </button>
          <button type="button" onClick={() => navigate('/create')} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800">
            <Plus className="h-4 w-4" />
            Create VM
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">{error}</div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricTile label="Nodes" value={model.summary.nodes} sub={model.clusterId} tone={healthTone} icon={Server} />
        <MetricTile label="VMs" value={model.summary.vms} sub={`${model.summary.runningVms} running`} tone="slate" icon={Activity} />
        <MetricTile label="Storage" value={model.summary.storage} sub={model.summary.storageSub} tone="slate" icon={HardDrive} />
        <MetricTile label="Risks" value={model.summary.redRisks} sub={`${model.summary.activeJobs} active jobs`} tone={model.summary.redRisks > 0 ? 'red' : 'green'} icon={AlertTriangle} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Datacenter</div>
          <div className="space-y-1">
            <button type="button" onClick={() => navigate('/infra')} className="flex w-full items-center gap-3 rounded-lg bg-slate-950 px-3 py-2 text-left text-sm font-semibold text-white">
              <Database className="h-4 w-4 text-yellow-300" />
              {model.clusterId}
            </button>
            {model.nodeRows.map((node) => (
              <button key={node.id} type="button" onClick={() => navigate('/infra')} className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50">
                <span className="flex min-w-0 items-center gap-3">
                  <Server className="h-4 w-4 shrink-0 text-slate-500" />
                  <span className="truncate">{node.name}</span>
                </span>
                <span className={`h-2 w-2 shrink-0 rounded-full ${node.tone === 'green' ? 'bg-emerald-500' : node.tone === 'red' ? 'bg-red-500' : 'bg-yellow-400'}`} />
              </button>
            ))}
            <button type="button" onClick={() => navigate('/networks')} className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50">
              <span className="flex items-center gap-3">
                <Network className="h-4 w-4 text-slate-500" />
                Networks
              </span>
              <span className="text-xs font-semibold text-slate-500">{model.summary.bridges}</span>
            </button>
            <button type="button" onClick={() => navigate('/jobs')} className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50">
              <span className="flex items-center gap-3">
                <Clock3 className="h-4 w-4 text-slate-500" />
                Jobs/Runs
              </span>
              <span className="text-xs font-semibold text-slate-500">{model.summary.activeJobs}</span>
            </button>
          </div>
        </aside>

        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-2 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Cluster Summary</h3>
              <div className="mt-1 text-xs text-slate-500">노드별 VM 상태, 실시간 CPU/메모리 사용량, 스토리지 여유 공간, 브리지 상태</div>
            </div>
            <span className={`inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClasses(healthTone)}`}>
              {onlineNodeLabel(model.nodeRows)}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3 text-left font-semibold">Node</th>
                  <th className="px-5 py-3 text-left font-semibold">Status</th>
                  <th className="px-5 py-3 text-left font-semibold">VMs</th>
                  <th className="px-5 py-3 text-left font-semibold">CPU usage</th>
                  <th className="px-5 py-3 text-left font-semibold">Memory usage</th>
                  <th className="px-5 py-3 text-left font-semibold">Network</th>
                  <th className="px-5 py-3 text-left font-semibold">Storage</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {model.nodeRows.length === 0 ? (
                  <tr>
                    <td className="px-5 py-6 text-sm text-slate-500" colSpan={7}>노드 데이터가 없습니다.</td>
                  </tr>
                ) : model.nodeRows.map((node) => (
                  <tr key={node.id} className="hover:bg-slate-50">
                    <td className="px-5 py-4">
                      <div className="font-semibold text-slate-950">{node.name}</div>
                      <div className="mt-0.5 text-xs text-slate-500">{node.id}</div>
                    </td>
                    <td className="px-5 py-4">
                      <span className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClasses(node.tone)}`}>
                        <span className={`h-2 w-2 rounded-full ${node.tone === 'green' ? 'bg-emerald-500' : node.tone === 'red' ? 'bg-red-500' : 'bg-yellow-400'}`} />
                        {node.status}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <div className="font-medium text-slate-900">{node.runningVmCount}/{node.vmCount}</div>
                      <div className="text-xs text-slate-500">running / total</div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="font-medium text-slate-900">{node.cpuLabel}</div>
                      <UsageBar value={node.cpuPercent} tone={node.cpuPercent > 85 ? 'red' : node.cpuPercent > 65 ? 'yellow' : 'blue'} />
                    </td>
                    <td className="px-5 py-4">
                      <div className="font-medium text-slate-900">{node.memoryLabel}</div>
                      <UsageBar value={node.memoryPercent} tone={node.memoryPercent > 85 ? 'red' : node.memoryPercent > 65 ? 'yellow' : 'green'} />
                    </td>
                    <td className="px-5 py-4 text-slate-700">{node.networks.length ? node.networks.join(' / ') : '-'}</td>
                    <td className="px-5 py-4 text-slate-700">{node.storageLabel}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>
  )
}

function onlineNodeLabel(nodes) {
  const online = nodes.filter((node) => node.tone === 'green').length
  return `${online}/${nodes.length} online`
}

function AdminGuard({ currentUser, children }) {
  return canAdmin(currentUser) ? children : <Navigate to="/" replace />
}

function LoginPage({ onLogin }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submitLogin = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await onLogin({ username, password })
      const target = location.state?.from?.pathname || '/'
      navigate(target, { replace: true })
    } catch (err) {
      setError(authFailureMessage(err, '로그인에 실패했습니다.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6 py-10">
        <section className="w-full rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <Server className="h-7 w-7 text-slate-700" />
            <div>
              <h1 className="text-xl font-semibold text-slate-950">Gjallar Login</h1>
              <p className="mt-1 text-sm text-slate-500">Proxmox 운영 콘솔 접근</p>
            </div>
          </div>
          <form className="mt-6 space-y-4" onSubmit={submitLogin}>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Username</span>
              <input
                autoComplete="username"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Password</span>
              <input
                type="password"
                autoComplete="current-password"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
            ) : null}
            <button
              type="submit"
              disabled={submitting || !username || !password}
              className="inline-flex w-full items-center justify-center rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Logging in...' : 'Login'}
            </button>
          </form>
        </section>
      </main>
    </div>
  )
}

function AccountSettingsScreen({ currentUser, onPasswordChanged }) {
  const [form, setForm] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const submitPasswordChange = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    if (form.newPassword !== form.confirmPassword) {
      setError('새 비밀번호 확인이 일치하지 않습니다.')
      return
    }
    setSubmitting(true)
    try {
      const response = await apiV1Client.changePassword(form.currentPassword, form.newPassword)
      setForm({ currentPassword: '', newPassword: '', confirmPassword: '' })
      setNotice(`비밀번호를 변경했습니다. 다른 세션 ${response.revoked_sessions || 0}개를 해지했습니다.`)
      if (typeof onPasswordChanged === 'function') await onPasswordChanged()
    } catch (err) {
      setError(authFailureMessage(err, '비밀번호를 변경하지 못했습니다.'))
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = form.currentPassword && form.newPassword && form.confirmPassword && !submitting

  return (
    <section className="mx-auto max-w-2xl space-y-5">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          <UserCircle className="h-4 w-4" />
          Account
        </div>
        <h2 className="mt-2 text-2xl font-semibold text-slate-950">{currentUser?.username}</h2>
        <div className="mt-1 text-sm text-slate-500">{currentUser?.role}</div>
      </div>

      <form className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" onSubmit={submitPasswordChange}>
        <div className="mb-4 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-slate-600" />
          <h3 className="text-sm font-semibold text-slate-950">Change Password</h3>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium text-slate-700">Current password</span>
            <input
              aria-label="Current password"
              type="password"
              autoComplete="current-password"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.currentPassword}
              onChange={(event) => updateField('currentPassword', event.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-slate-700">New password</span>
            <input
              aria-label="New password"
              type="password"
              autoComplete="new-password"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.newPassword}
              onChange={(event) => updateField('newPassword', event.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-slate-700">Confirm new password</span>
            <input
              aria-label="Confirm new password"
              type="password"
              autoComplete="new-password"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.confirmPassword}
              onChange={(event) => updateField('confirmPassword', event.target.value)}
            />
          </label>
        </div>
        {error ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
        {notice ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{notice}</span>
          </div>
        ) : null}
        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <KeyRound className="h-4 w-4" />
          {submitting ? 'Changing...' : 'Change password'}
        </button>
      </form>
    </section>
  )
}

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [authState, setAuthState] = useState({ status: 'loading', user: null })

  useEffect(() => {
    let cancelled = false
    async function bootstrapAuth() {
      try {
        const response = await apiV1Client.me()
        if (cancelled) return
        setAuthState(response.authenticated && response.user
          ? { status: 'authenticated', user: response.user }
          : { status: 'anonymous', user: null })
      } catch {
        if (!cancelled) setAuthState({ status: 'anonymous', user: null })
      }
    }
    bootstrapAuth()
    return () => {
      cancelled = true
    }
  }, [])

  const handleLogin = async ({ username, password }) => {
    const response = await apiV1Client.login(username, password)
    setAuthState({ status: 'authenticated', user: response.user })
    return response
  }

  const refreshCurrentUser = async () => {
    try {
      const response = await apiV1Client.me()
      setAuthState(response.authenticated && response.user
        ? { status: 'authenticated', user: response.user }
        : { status: 'anonymous', user: null })
      return response
    } catch {
      setAuthState({ status: 'anonymous', user: null })
      return null
    }
  }

  const handleLogout = async () => {
    try {
      await apiV1Client.logout()
    } finally {
      setAuthState({ status: 'anonymous', user: null })
      navigate('/login', { replace: true })
    }
  }

  if (authState.status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 text-sm text-slate-600">
        Loading Gjallar session...
      </div>
    )
  }

  if (authState.status !== 'authenticated') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage onLogin={handleLogin} />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location }} />} />
      </Routes>
    )
  }

  const currentUser = authState.user
  const canMutate = canOperate(currentUser)
  const isAdmin = canAdmin(currentUser)
  const visibleNavItems = isAdmin ? [...navItems, adminNavItem, accountNavItem] : [...navItems, accountNavItem]

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="container mx-auto px-8 py-5">
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <Server className="h-8 w-8 shrink-0 text-slate-700" />
              <div className="min-w-0">
                <h1 className="truncate text-xl font-semibold text-gray-900 sm:text-2xl">Gjallar Operations Console</h1>
                <p className="text-sm text-gray-500">Proxmox VM 운영 관리</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-4">
              <div className="hidden items-center gap-2 text-sm text-slate-600 sm:flex">
                <UserCircle className="h-4 w-4" />
                <span className="font-medium text-slate-900">{currentUser?.username}</span>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold uppercase text-slate-600">{currentUser?.role}</span>
              </div>
              <button type="button" onClick={handleLogout} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                <LogOut className="h-4 w-4" />
                Logout
              </button>
              <img src={middlepiaStackLogo} alt="MiddlePia Stack" className="h-12 w-auto shrink-0 sm:h-14 md:h-16" />
            </div>
          </div>
        </div>
      </header>

      <nav className="bg-white border-b border-gray-200 shadow-sm" aria-label="Gjallar primary navigation">
        <div className="container mx-auto px-8">
          <div className="flex overflow-x-auto">
            {visibleNavItems.map(({ label, path, icon: Icon, end }) => (
              <NavLink key={path} to={path} end={end} className={navClass}>
                <Icon className="w-5 h-5" />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      <main className="container mx-auto px-8 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/infra"
            element={
              <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
                <InstanceList currentUser={currentUser} canStartVms={canMutate} canManageDrsPolicies={canMutate} />
              </div>
            }
          />
          <Route
            path="/networks"
            element={
              <div className="mx-auto max-w-7xl">
                <NetworkReadinessScreen />
              </div>
            }
          />
          <Route
            path="/create"
            element={
              <div className="mx-auto max-w-6xl">
                <CreateInstanceWizard currentUser={currentUser} canExecuteLiveMutation={canMutate} />
              </div>
            }
          />
          <Route
            path="/drs"
            element={
              <div className="mx-auto max-w-7xl">
                <DrsAdvisorScreen currentUser={currentUser} canOperate={canMutate} />
              </div>
            }
          />
          <Route path="/jobs" element={<TaskBoard />} />
          <Route
            path="/risks"
            element={
              <div className="mx-auto max-w-7xl">
                <OperationalRiskDashboard />
              </div>
            }
          />
          <Route
            path="/admin/users"
            element={
              <AdminGuard currentUser={currentUser}>
                <div className="mx-auto max-w-7xl">
                  <AdminUsersScreen currentUser={currentUser} onCurrentUserChanged={refreshCurrentUser} />
                </div>
              </AdminGuard>
            }
          />
          <Route
            path="/account"
            element={<AccountSettingsScreen currentUser={currentUser} onPasswordChanged={refreshCurrentUser} />}
          />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
