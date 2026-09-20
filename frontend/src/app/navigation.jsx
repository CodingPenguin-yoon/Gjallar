import { Link, useLocation, useNavigate } from 'react-router-dom'
import { overviewNavItems, accountNavItem, adminNavItem, proxmoxSetupNavItem, hostStorageNavItem, hostNetworkNavItem, insightsNavItems, operationsNavItems, resolveSectionNavItems, workloadNavItems, templateNavItems, maintenanceNavItem } from './navigationModel'

function subnavClass({ isActive }) {
  return `inline-flex min-h-9 items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
    isActive ? 'bg-white text-teal-800 shadow-sm ring-1 ring-slate-200' : 'text-slate-600 hover:bg-white/70 hover:text-slate-950'
  }`
}

function SectionSubnav({ items, ariaLabel, grouped = false }) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const resolvedItems = resolveSectionNavItems(items, pathname)
  const active = resolvedItems.find(item => item.isActive)
  const groups = [...new Set(items.map(item => item.group))]

  if (items.length < 2) return null
  const links = entries => entries.map(({ label, path, icon: Icon, isActive }) => (
    <Link key={path} to={path} aria-current={isActive ? 'page' : undefined} className={subnavClass({ isActive })}>
      <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />{label}
    </Link>
  ))

  if (!grouped) return <nav aria-label={ariaLabel} className="flex flex-wrap gap-1 rounded-md border border-slate-200 bg-white p-1">{links(resolvedItems)}</nav>

  return <nav aria-label={ariaLabel} className="min-w-0">
    <label className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm font-semibold lg:hidden">
      <span className="shrink-0 text-slate-500">화면 선택</span>
      <select aria-label={ariaLabel} className="min-w-0 flex-1 rounded-md border border-slate-200 bg-slate-50 p-2" value={active?.path || ''} onChange={event => navigate(event.target.value)}>
        {!active && <option value="" disabled>화면을 선택하세요</option>}
        {groups.map(group => <optgroup key={group} label={group}>{items.filter(item => item.group === group).map(item => <option key={item.path} value={item.path}>{item.label}</option>)}</optgroup>)}
      </select>
    </label>
    <div className="hidden space-y-4 lg:block">
      {groups.map(group => <div key={group}>
        <p className="mb-2 px-3 text-xs font-semibold tracking-wide text-slate-500">{group}</p>
        <div className="flex flex-col gap-1">{links(resolvedItems.filter(item => item.group === group))}</div>
      </div>)}
    </div>
  </nav>
}

function SectionLayout({ items, ariaLabel, grouped = false, children }) {
  return <div className={grouped && items.length > 1 ? 'grid items-start gap-3 lg:grid-cols-[148px_minmax(0,1fr)] lg:gap-4' : 'space-y-3'}>
    <SectionSubnav items={items} ariaLabel={ariaLabel} grouped={grouped} />
    <div className="min-w-0">{children}</div>
  </div>
}

export function WorkloadsShell({ children }) {
  return <SectionLayout items={workloadNavItems} ariaLabel="가상머신 메뉴">{children}</SectionLayout>
}
export function OperationsShell({ children }) {
  return <SectionLayout items={operationsNavItems} ariaLabel="작업 이력 메뉴">{children}</SectionLayout>
}
export function InsightsShell({ children }) {
  return <SectionLayout items={insightsNavItems} ariaLabel="모니터링 메뉴" grouped>{children}</SectionLayout>
}
export function SettingsShell({ isAdmin, children }) {
  return <SectionLayout items={isAdmin ? [accountNavItem, adminNavItem] : [accountNavItem]} ariaLabel="계정 관리 메뉴">{children}</SectionLayout>
}
export function TemplatesShell({ children }) {
  return <SectionLayout items={templateNavItems} ariaLabel="템플릿 메뉴">{children}</SectionLayout>
}
export function InfrastructureShell({ isAdmin, children }) {
  return <SectionLayout items={isAdmin ? [maintenanceNavItem, proxmoxSetupNavItem, hostStorageNavItem, hostNetworkNavItem] : [maintenanceNavItem]} ariaLabel="인프라 메뉴" grouped>{children}</SectionLayout>
}

export function OverviewShell({ children }) {
  return <SectionLayout items={overviewNavItems} ariaLabel="전체 현황 메뉴">{children}</SectionLayout>
}
