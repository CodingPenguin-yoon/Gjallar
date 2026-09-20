import {
  Activity,
  AlertTriangle,
  ClipboardCheck,
  Clock3,
  LayoutDashboard,
  List,
  Network,
  Plus,
  Layers,
  Settings as SettingsIcon,
  UserCircle,
  UserCog,
} from 'lucide-react'

export const APP_SHELL_CLASS = 'mx-auto w-full max-w-[1680px] px-3 sm:px-5'

export const primaryNavItems = Object.freeze([
  { label: '전체 현황', path: '/', icon: LayoutDashboard, aliasPaths: ['/nodes'] },
  { label: 'VM 관리', path: '/instances', icon: List, activePrefixes: ['/instances'], aliasPaths: ['/infra', '/create', '/networks'] },
  { label: '템플릿', path: '/instances/templates/build', icon: Layers, activePrefixes: ['/instances/templates'] },
  { label: '모니터링', path: '/insights/metrics', icon: Activity, activePrefixes: ['/insights'] },
  { label: '인프라', path: '/insights/maintenance', icon: Network, aliasPaths: ['/settings/proxmox', '/settings/host-storage', '/settings/host-network'] },
  { label: '작업 이력', path: '/operations', icon: Clock3, activePrefixes: ['/operations'], aliasPaths: ['/jobs', '/risks'] },
])

export const overviewNavItems = Object.freeze([
  { label: '클러스터 전체', path: '/', icon: LayoutDashboard },
  { label: '노드 상세', path: '/nodes', icon: Activity },
])

export const workloadNavItems = Object.freeze([
  { label: 'VM 목록', path: '/instances', icon: List, activePrefixes: ['/instances'], aliasPaths: ['/infra'] },
  { label: 'VM 생성', path: '/instances/create', icon: Plus, aliasPaths: ['/create'] },
])

export const templateNavItems = Object.freeze([
  { label: '공식 이미지 제작', path: '/instances/templates/build', icon: Layers, activePrefixes: ['/instances/templates'] },
  { label: '제작 자원 정리', path: '/instances/templates/cleanup', icon: ClipboardCheck },
])

export const maintenanceNavItem = { label: '노드 유지보수', path: '/insights/maintenance', icon: ClipboardCheck, group: '운영' }

export const operationsNavItems = Object.freeze([
  { label: '실행 작업', path: '/operations', icon: List, activePrefixes: ['/operations'], aliasPaths: ['/risks'] },
  { label: '생성 이력', path: '/operations/jobs', icon: Clock3, aliasPaths: ['/jobs'] },
])

export const insightsNavItems = Object.freeze([
  { label: '상태 요약', path: '/insights', icon: Activity, group: '관찰' },
  { label: '사용량·추이', path: '/insights/metrics', icon: Activity, group: '관찰' },
  { label: '알림 이력', path: '/insights/alerts', icon: AlertTriangle, group: '관찰' },
  { label: '위험 진단', path: '/insights/risks', icon: AlertTriangle, group: '진단' },
  { label: 'VM 준비 상태', path: '/insights/readiness', icon: ClipboardCheck, group: '진단' },
  { label: '가용 용량', path: '/insights/capacity', icon: Clock3, group: '진단' },
  { label: '배치 진단', path: '/insights/placement', icon: Network, group: '진단' },
])

export const accountNavItem = { label: '내 계정', path: '/settings/account', icon: UserCircle, aliasPaths: ['/account'], group: '계정' }
export const adminNavItem = { label: '사용자·세션', path: '/settings/admin/users', icon: UserCog, aliasPaths: ['/admin/users'], group: '계정' }
export const proxmoxSetupNavItem = { label: 'Proxmox 연결', path: '/settings/proxmox', icon: Network, group: '인프라' }
export const hostStorageNavItem = { label: '스토리지 설정', path: '/settings/host-storage', icon: SettingsIcon, group: '인프라' }

export function navClass({ isActive }) {
  return `gj-primary-link flex min-w-0 flex-1 flex-col items-center justify-center gap-1 border-b-2 px-1 py-2.5 text-[11px] font-semibold transition-colors sm:flex-row sm:gap-2 sm:px-3 sm:text-sm lg:flex-none lg:px-4 ${
    isActive
      ? 'text-teal-800 border-teal-600 bg-teal-50/60'
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
  return navItemPrefixLength(item, current) > 0
}

function navItemPrefixLength(item, pathname) {
  const current = normalizePathname(pathname)
  return Math.max(0, ...(item?.activePrefixes || []).map((prefix) => {
    const normalizedPrefix = normalizePathname(prefix)
    return current === normalizedPrefix || current.startsWith(`${normalizedPrefix}/`) ? normalizedPrefix.length : 0
  }))
}

export function resolveSectionNavItems(items, pathname) {
  const activeItem = items.find((item) => navItemExact(item, pathname))
    || items.reduce((best, item) => navItemPrefixLength(item, pathname) > navItemPrefixLength(best, pathname) ? item : best, null)
  return items.map((item) => ({ ...item, isActive: item === activeItem }))
}

export const hostNetworkNavItem = { label: '브리지 설정', path: '/settings/host-network', icon: SettingsIcon, group: '인프라' }
