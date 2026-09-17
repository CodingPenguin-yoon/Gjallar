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
  UserCircle,
  UserCog,
} from 'lucide-react'

export const APP_SHELL_CLASS = 'mx-auto w-full max-w-7xl px-4 sm:px-8'

export const primaryNavItems = Object.freeze([
  { label: 'Overview', path: '/', icon: LayoutDashboard },
  { label: 'Workloads', path: '/instances', icon: List, activePrefixes: ['/instances'], aliasPaths: ['/infra', '/create', '/networks'], requiresProxmox: true },
  { label: 'Insights', path: '/insights', icon: Activity, activePrefixes: ['/insights'] },
  { label: 'Operations', path: '/operations', icon: Clock3, activePrefixes: ['/operations'], aliasPaths: ['/jobs', '/risks'] },
  { label: 'Settings', path: '/settings/account', icon: SettingsIcon, activePrefixes: ['/settings'], aliasPaths: ['/account', '/admin/users'] },
])

export const workloadNavItems = Object.freeze([
  { label: 'Inventory', path: '/instances', icon: List, activePrefixes: ['/instances'], aliasPaths: ['/infra'] },
  { label: 'Create VM', path: '/instances/create', icon: Plus, aliasPaths: ['/create'] },
])

export const operationsNavItems = Object.freeze([
  { label: 'All operations', path: '/operations', icon: List, activePrefixes: ['/operations'], aliasPaths: ['/risks'] },
  { label: 'Job history', path: '/operations/jobs', icon: Clock3, aliasPaths: ['/jobs'] },
])

export const insightsNavItems = Object.freeze([
  { label: 'Summary', path: '/insights', icon: Activity },
  { label: 'Risks', path: '/insights/risks', icon: AlertTriangle },
  { label: 'VM readiness', path: '/insights/readiness', icon: ClipboardCheck },
  { label: 'Capacity', path: '/insights/capacity', icon: Clock3 },
  { label: 'Placement', path: '/insights/placement', icon: Network },
])

export const accountNavItem = { label: 'Account', path: '/settings/account', icon: UserCircle, aliasPaths: ['/account'] }
export const adminNavItem = { label: 'Users & sessions', path: '/settings/admin/users', icon: UserCog, aliasPaths: ['/admin/users'] }
export const proxmoxSetupNavItem = { label: 'Proxmox 연결', path: '/settings/proxmox', icon: Network }

export function navClass({ isActive }) {
  return `flex shrink-0 items-center justify-center gap-2 border-b-2 px-4 py-3 font-medium transition-colors sm:px-6 sm:py-4 ${
    isActive
      ? 'text-slate-900 border-slate-900 bg-slate-50'
      : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
  }`
}

function normalizePathname(pathname) {
  const normalized = String(pathname || '/').replace(/\/+$/, '')
  return normalized || '/'
}

function navItemExact(item, pathname) {
  const current = normalizePathname(pathname)
  if (current === normalizePathname(item.path)) return true
  return (item.aliasPaths || []).map(normalizePathname).includes(current)
}

export function navItemActive(item, pathname) {
  const current = normalizePathname(pathname)
  const itemPath = normalizePathname(item.path)
  if (itemPath === '/') return current === '/'
  if (navItemExact(item, current)) return true
  return (item.activePrefixes || []).some((prefix) => {
    const normalizedPrefix = normalizePathname(prefix)
    return current === normalizedPrefix || current.startsWith(`${normalizedPrefix}/`)
  })
}

export function resolveSectionNavItems(items, pathname) {
  const activeItem = items.find((item) => navItemExact(item, pathname))
    || items.find((item) => navItemActive(item, pathname))
  return items.map((item) => ({ ...item, isActive: item === activeItem }))
}
