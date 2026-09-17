import { useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { accountNavItem, adminNavItem, proxmoxSetupNavItem, insightsNavItems, operationsNavItems, resolveSectionNavItems, workloadNavItems } from './navigationModel'

function subnavClass({ isActive }) {
  return `inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-slate-950 text-white'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
  }`
}

function SectionSubnav({ items, ariaLabel }) {
  const location = useLocation()
  const activeItemRef = useRef(null)
  const resolvedItems = resolveSectionNavItems(items, location.pathname)

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [location.pathname])

  if (items.length < 2) return null

  return (
    <nav className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 shadow-sm" aria-label={ariaLabel}>
      <div className="flex gap-1">
        {resolvedItems.map(({ label, path, icon: Icon, isActive }) => (
          <Link ref={isActive ? activeItemRef : null} key={path} to={path} aria-current={isActive ? 'page' : undefined} className={subnavClass({ isActive })}>
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </div>
    </nav>
  )
}

export function WorkloadsShell({ children }) {
  return <section className="space-y-4"><SectionSubnav items={workloadNavItems} ariaLabel="Workloads navigation" />{children}</section>
}

export function OperationsShell({ children }) {
  return <section className="space-y-4"><SectionSubnav items={operationsNavItems} ariaLabel="Operations navigation" />{children}</section>
}

export function InsightsShell({ children }) {
  return <section className="space-y-4"><SectionSubnav items={insightsNavItems} ariaLabel="Insights navigation" />{children}</section>
}

export function SettingsShell({ isAdmin, children }) {
  return <section className="space-y-4"><SectionSubnav items={isAdmin ? [accountNavItem, adminNavItem, proxmoxSetupNavItem] : [accountNavItem]} ariaLabel="Settings navigation" />{children}</section>
}
