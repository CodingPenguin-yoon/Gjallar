import { Link } from 'react-router-dom'
import { LogOut, Server } from 'lucide-react'
import middlepiaStackLogo from '../assets/middlepia-stack.svg'
import { APP_SHELL_CLASS, navClass, resolveSectionNavItems } from './navigationModel'
import AccountMenu from './AccountMenu'

const badgeTones = Object.freeze({
  green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  red: 'border-red-200 bg-red-50 text-red-700',
  slate: 'border-slate-200 bg-slate-50 text-slate-700',
})

export default function AppShell({ currentUser, connectionBadge, navItems, pathname, onLogout, children }) {
  return (
    <div className="gj-app min-h-screen bg-slate-100 text-slate-900">
      <a href="#main-content" className="sr-only z-50 rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        본문으로 바로가기
      </a>
      <header className="gj-topbar border-b border-slate-700 bg-slate-900 text-slate-200">
        <div className={`${APP_SHELL_CLASS} py-2`}>
          <div className="flex items-center justify-between gap-2 sm:gap-3">
            <Link to="/" aria-label="Gjallar 대시보드" className="flex min-w-0 items-center gap-3">
              <Server className="h-8 w-8 shrink-0 rounded-md bg-slate-800 p-1.5 text-teal-300" />
              <div className="min-w-0">
                <span className="text-lg font-bold tracking-tight text-white">Gjallar</span>
                <p className="hidden text-[10px] font-medium tracking-widest text-slate-400 sm:block">PROXMOX OPERATIONS</p>
              </div>
            </Link>
            <div className="flex shrink-0 items-center gap-2 sm:gap-3">
              <span className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-semibold ${badgeTones[connectionBadge.tone] || badgeTones.slate}`}>
                <span className="hidden lg:inline">Proxmox&nbsp;</span>{connectionBadge.label}
              </span>
              {connectionBadge.observation && (
                <span className={`hidden rounded-full border px-2.5 py-1 text-xs font-semibold md:inline-flex ${badgeTones[connectionBadge.observationTone] || badgeTones.slate}`}>
                  {connectionBadge.observation}
                </span>
              )}
              <AccountMenu currentUser={currentUser} />
              <button type="button" onClick={onLogout} aria-label="로그아웃" className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-800 p-2 text-xs font-medium text-slate-200 hover:bg-slate-700 sm:px-3">
                <LogOut className="h-4 w-4" /> <span className="hidden sm:inline">로그아웃</span>
              </button>
              <img src={middlepiaStackLogo} alt="MiddlePia Stack" className="hidden h-6 w-auto shrink-0 rounded bg-white px-1 xl:block" />
            </div>
          </div>
        </div>
      </header>

      <nav className="border-b border-slate-200 bg-white" aria-label="주 메뉴">
        <div className={APP_SHELL_CLASS}>
          <div className="flex">
            {resolveSectionNavItems(navItems, pathname).map(({ label, path, icon: Icon, isActive }) => (
              <Link
                key={path}
                to={path}
                aria-label={label}
                aria-current={isActive ? 'page' : undefined}
                className={navClass({ isActive })}
              >
                <Icon aria-hidden="true" className="h-[18px] w-[18px] shrink-0" /> <span className="whitespace-nowrap">{label}</span>
              </Link>
            ))}
          </div>
        </div>
      </nav>

      <main id="main-content" tabIndex={-1} className={`${APP_SHELL_CLASS} gj-content py-3 sm:py-4`}>{children}</main>
    </div>
  )
}
