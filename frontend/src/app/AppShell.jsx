import { NavLink } from 'react-router-dom'
import { LogOut, Server, UserCircle } from 'lucide-react'
import middlepiaStackLogo from '../assets/middlepia-stack.svg'
import { APP_SHELL_CLASS, navClass, navItemActive } from './navigationModel'

const badgeTones = Object.freeze({
  green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  red: 'border-red-200 bg-red-50 text-red-700',
  slate: 'border-slate-200 bg-slate-50 text-slate-700',
})

export default function AppShell({ currentUser, connectionBadge, navItems, pathname, onLogout, children }) {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white shadow-sm">
        <div className={`${APP_SHELL_CLASS} py-5`}>
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <Server className="h-8 w-8 shrink-0 text-slate-700" />
              <div className="min-w-0">
                <h1 className="truncate text-xl font-semibold text-gray-900 sm:text-2xl">Gjallar Operations Console</h1>
                <p className="text-sm text-gray-500">Proxmox VM 운영 관리</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-4">
              <span className={`hidden rounded-full border px-2.5 py-1 text-xs font-semibold sm:inline-flex ${badgeTones[connectionBadge.tone] || badgeTones.slate}`}>
                Proxmox {connectionBadge.label}
              </span>
              <div className="hidden items-center gap-2 text-sm text-slate-600 sm:flex">
                <UserCircle className="h-4 w-4" />
                <span className="font-medium text-slate-900">{currentUser?.username}</span>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold uppercase text-slate-600">{currentUser?.role}</span>
              </div>
              <button type="button" onClick={onLogout} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                <LogOut className="h-4 w-4" /> Logout
              </button>
              <img src={middlepiaStackLogo} alt="MiddlePia Stack" className="h-12 w-auto shrink-0 sm:h-14 md:h-16" />
            </div>
          </div>
        </div>
      </header>

      <nav className="border-b border-gray-200 bg-white shadow-sm" aria-label="Gjallar primary navigation">
        <div className={APP_SHELL_CLASS}>
          <div className="flex overflow-x-auto">
            {navItems.map(({ label, path, icon: Icon, activePrefixes, aliasPaths }) => (
              <NavLink key={path} to={path} className={() => navClass({ isActive: navItemActive({ path, activePrefixes, aliasPaths }, pathname) })}>
                <Icon className="h-5 w-5" /> {label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      <main className={`${APP_SHELL_CLASS} py-8`}>{children}</main>
    </div>
  )
}
