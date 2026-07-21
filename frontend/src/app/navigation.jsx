import { NavLink, useLocation } from 'react-router-dom'
import { accountNavItem, adminNavItem, insightsNavItems, navItemActive, operationsNavItems, workloadNavItems } from './navigationModel'

function subnavClass({ isActive }) {
  return `inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-slate-950 text-white'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
  }`
}

function SectionSubnav({ items, ariaLabel }) {
  const location = useLocation()
  return (
    <nav className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 shadow-sm" aria-label={ariaLabel}>
      <div className="flex gap-1">
        {items.map(({ label, path, icon: Icon, aliasPaths }) => (
          <NavLink key={path} to={path} className={() => subnavClass({ isActive: navItemActive({ path, aliasPaths }, location.pathname) })}>
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

export function WorkloadsShell({ children }) {
  return <section className="space-y-4"><SectionSubnav items={workloadNavItems} ariaLabel="Workloads navigation" />{children}</section>
}

export function OperationsShell({ canExecute = false, children }) {
  const visibleItems = operationsNavItems.filter((item) => !item.requiresOperator || canExecute)
  return <section className="space-y-4"><SectionSubnav items={visibleItems} ariaLabel="Operations navigation" />{children}</section>
}

export function InsightsShell({ children }) {
  return <section className="space-y-4"><SectionSubnav items={insightsNavItems} ariaLabel="Insights navigation" />{children}</section>
}

export function SettingsShell({ isAdmin, children }) {
  return <section className="space-y-4"><SectionSubnav items={isAdmin ? [accountNavItem, adminNavItem] : [accountNavItem]} ariaLabel="Settings navigation" />{children}</section>
}
