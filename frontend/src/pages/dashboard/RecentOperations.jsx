import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { normalizeOperation, operationTypeLabel, formatOperationTime } from '../../entities/operation/model'
import OperationStatusBadge from '../../entities/operation/ui/OperationStatusBadge'

export default function RecentOperations({ refreshKey }) {
  const [state, setState] = useState({ loading: true, error: '', items: [] })
  useEffect(() => {
    let cancelled = false
    setState({ loading: true, error: '', items: [] })
    apiV1Client.listOperations({ limit: 4 }).then(items => {
      if (!cancelled) setState({ loading: false, error: '', items: items.map(normalizeOperation) })
    }).catch(error => {
      if (!cancelled) setState({ loading: false, error: error.message, items: [] })
    })
    return () => { cancelled = true }
  }, [refreshKey])
  return <section className="gj-panel h-full" aria-label="최근 실행 작업">
    <header className="gj-panel-heading flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">최근 실행 작업</h2><Link className="text-xs text-teal-700 hover:underline" to="/operations">전체 보기 →</Link></header>
    {state.loading ? <p className="p-4 text-xs text-slate-500" role="status">작업 조회 중…</p> : state.error ? <p className="p-4 text-xs text-amber-800" role="alert">작업 조회 불가 · {state.error}</p> : state.items.length === 0 ? <p className="p-4 text-xs text-slate-500">기록된 실행 작업이 없습니다.</p> : <ul className="divide-y divide-slate-100">{state.items.map(item => <li key={item.id}>
      <Link to={`/operations/${encodeURIComponent(item.id)}`} className="block space-y-1 px-3 py-2.5 hover:bg-slate-50">
        <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-semibold">{operationTypeLabel(item.type)}</span><OperationStatusBadge status={item.status} /></div>
        <p className="break-all font-mono text-xs text-slate-600">{item.type === 'proxmox_registration' ? '관리형 Proxmox 연결' : item.targetId}</p><p className="text-[11px] text-slate-400">{formatOperationTime(item.updatedAt)}</p>
      </Link>
    </li>)}</ul>}
    <p className="border-t border-slate-100 px-3 py-2 text-[11px] text-slate-500">최근 4개 · 각 작업에서 실행 결과와 복구 상태 확인</p>
  </section>
}
