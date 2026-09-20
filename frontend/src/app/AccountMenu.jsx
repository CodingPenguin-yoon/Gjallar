import { useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronDown, UserCircle } from 'lucide-react'
import { canAdmin } from '../shared/auth/permissions'
import { accountNavItem, adminNavItem, resolveSectionNavItems } from './navigationModel'

export default function AccountMenu({ currentUser }) {
  const { pathname } = useLocation()
  const menu = useRef(null)
  const trigger = useRef(null)
  const items = resolveSectionNavItems(canAdmin(currentUser) ? [accountNavItem, adminNavItem] : [accountNavItem], pathname)
  const active = items.some(item => item.isActive)

  useEffect(() => { menu.current.open = false }, [pathname])

  useEffect(() => {
    const closeOutside = event => {
      if (menu.current && !menu.current.contains(event.target)) menu.current.open = false
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [])

  return <details ref={menu} className="relative" onKeyDown={event => {
    if (event.key === 'Escape') { menu.current.open = false; trigger.current.focus() }
  }}>
    <summary ref={trigger} className={`flex min-h-9 cursor-pointer list-none items-center gap-1.5 rounded-lg border px-2 text-xs font-semibold [&::-webkit-details-marker]:hidden ${active ? 'border-teal-300 bg-teal-50 text-teal-800' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700'}`}>
      <UserCircle aria-hidden="true" className="h-4 w-4" /><span>계정</span><ChevronDown aria-hidden="true" className="hidden h-3 w-3 sm:block" />
    </summary>
    <div className="absolute right-0 z-40 mt-2 w-60 rounded-lg border border-slate-200 bg-white text-slate-900 p-2 shadow-lg">
      <div className="mb-2 border-b border-slate-100 px-3 py-2">
        <p className="break-all text-sm font-semibold text-slate-900">{currentUser?.username}</p>
        <p className="mt-1 text-xs uppercase text-slate-500">{currentUser?.role}</p>
      </div>
      <nav aria-label="계정 메뉴" className="space-y-1">
        {items.map(({ path, label, icon: Icon, isActive }) => <Link key={path} to={path} aria-current={isActive ? 'page' : undefined}
          onClick={() => { menu.current.open = false }}
          className={`flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm ${isActive ? 'bg-teal-50 font-semibold text-teal-800' : 'text-slate-700 hover:bg-slate-50'}`}>
          <Icon aria-hidden="true" className="h-4 w-4" />{label}
        </Link>)}
      </nav>
    </div>
  </details>
}
