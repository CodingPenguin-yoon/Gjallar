import {
  Activity,
  AlertTriangle,
  ClipboardCheck,
  Clock3,
  LayoutDashboard,
  List,
  Network,
  Plus,
  Settings as SettingsIcon,
  Terminal,
  UserCircle,
  UserCog,
} from 'lucide-react'

export const APP_SHELL_CLASS = 'mx-auto w-full max-w-7xl px-8'

export const primaryNavItems = Object.freeze([
  { label: 'Overview', path: '/', icon: LayoutDashboard },
  { label: 'Workloads', path: '/instances', icon: List, activePrefixes: ['/instances'], aliasPaths: ['/infra', '/create', '/networks'], requiresProxmox: true },
  { label: 'DRS Advisor', path: '/drs', icon: Activity, activePrefixes: ['/drs'], requiresProxmox: true },
  { label: 'Operations', path: '/operations', icon: Clock3, activePrefixes: ['/operations'], aliasPaths: ['/jobs', '/risks'] },
  { label: 'Settings', path: '/settings/account', icon: SettingsIcon, activePrefixes: ['/settings'], aliasPaths: ['/account', '/admin/users'] },
])

export const workloadNavItems = Object.freeze([
  { label: 'Inventory', path: '/instances', icon: List, aliasPaths: ['/infra'] },
  { label: 'DRS Policies', path: '/instances/drs-policies', icon: ClipboardCheck },
  { label: 'Create VM', path: '/instances/create', icon: Plus, aliasPaths: ['/create'] },
  { label: 'Network readiness', path: '/instances/networks', icon: Network, aliasPaths: ['/networks'] },
])

export const operationsNavItems = Object.freeze([
  { label: 'Operations', path: '/operations', icon: List },
  { label: 'Jobs', path: '/operations/jobs', icon: Clock3, aliasPaths: ['/jobs'] },
  { label: 'Risks', path: '/operations/risks', icon: AlertTriangle, aliasPaths: ['/risks'] },
  { label: 'Guided qm', path: '/operations/guided-qm/vm-unlock', icon: Terminal, requiresOperator: true },
])

export const accountNavItem = { label: 'Account', path: '/settings/account', icon: UserCircle, aliasPaths: ['/account'] }
export const adminNavItem = { label: 'Admin Users', path: '/settings/admin/users', icon: UserCog, aliasPaths: ['/admin/users'] }

export function navClass({ isActive }) {
  return `flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
    isActive
      ? 'text-slate-900 border-slate-900 bg-slate-50'
      : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
  }`
}

function normalizePathname(pathname) {
  const normalized = String(pathname || '/').replace(/\/+$/, '')
  return normalized || '/'
}

export function navItemActive(item, pathname) {
  const current = normalizePathname(pathname)
  const itemPath = normalizePathname(item.path)
  if (itemPath === '/') return current === '/'
  if (current === itemPath) return true
  if ((item.aliasPaths || []).map(normalizePathname).includes(current)) return true
  return (item.activePrefixes || []).some((prefix) => {
    const normalizedPrefix = normalizePathname(prefix)
    return current === normalizedPrefix || current.startsWith(`${normalizedPrefix}/`)
  })
}
