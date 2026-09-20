import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { operationTypeLabel } from '../../entities/operation/model'

const stateLabels = { open: '실패 기록', needs_observation: '결과 재확인 필요', cleared: '이후 성공 확인' }

export default function AlertsPage() {
  const [limit, setLimit] = useState(20)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const load = useCallback(async () => {
    const current = ++generation.current
    setBusy(true); setError(''); setReport(null)
    try {
      const data = await apiV1Client.getOperationAlerts(limit)
      if (current === generation.current) setReport(data)
    } catch (failure) {
      if (current === generation.current) setError(failure.message)
    } finally {
      if (current === generation.current) setBusy(false)
    }
  }, [limit])
  useEffect(() => { load(); return () => { generation.current += 1 } }, [load])
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">이상 상태·알림 이력</h1><p className="mt-2 text-sm text-slate-600">기록된 작업 실패와 이후 성공을 확인합니다. 임계 초과 이력은 대상별 PVE 평균 표본에서 확인하세요. 외부 알림 발송과 자동 복구는 실행하지 않습니다.</p></header>
    <Link className="inline-block text-sm font-semibold underline" to="/insights/metrics">자원별 현재 임계 상태·초과/해제 이력</Link>
    <div className="flex flex-wrap items-end gap-3"><label className="text-sm">최신 작업 조회 범위<select disabled={busy} className="ml-2 rounded-lg border p-2" value={limit} onChange={event => setLimit(Number(event.target.value))}><option value={20}>20개</option><option value={50}>50개</option></select></label><button type="button" disabled={busy} onClick={load} className="rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-50">{busy ? '읽는 중…' : '기록 다시 조회'}</button></div>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
    {report && <>
      <p className="text-sm">최신 {report.inspected_operations}개 작업 확인 · 실패 구간 {report.alerts.length}개</p>
      {report.alerts_truncated && <p className="text-sm text-amber-900">실패 구간 {report.alert_count}개 중 최근 100개만 표시합니다. 전체 기록은 각 작업에서 확인하세요.</p>}
      <p className="text-sm text-slate-600">{report.limitation}</p>
      {report.possibly_truncated && <p className="text-sm text-amber-900">조회 한도에 도달했습니다. 이전 실패가 빠져 있을 수 있습니다. <Link className="underline" to="/operations">전체 작업에서 확인</Link></p>}
      {report.unavailable_operations.length > 0 && <p role="status" className="text-sm text-amber-900">{report.unavailable_operations.length}개 작업의 기록을 읽지 못했습니다. 해당 작업의 정상 여부는 알 수 없습니다.</p>}
      {!report.alerts.length && <p className="rounded-lg bg-slate-50 p-4 text-sm">읽은 기록 안에서 실행 실패를 찾지 못했습니다.</p>}
      <ul className="space-y-3">{report.alerts.map(alert => <li key={alert.id} className="rounded-lg border border-slate-200 p-4 text-sm">
        <p className="font-semibold">{operationTypeLabel(alert.operation_type)} · {stateLabels[alert.state] || alert.state}</p>
        <p className="mt-1">대상: {alert.target_id} · {alert.status}</p>
        <p className="mt-1 text-slate-600">실패 관찰: {new Date(alert.first_observed_at).toLocaleString()} · 이후 성공: {alert.cleared_observed_at ? new Date(alert.cleared_observed_at).toLocaleString() : '미확인'}</p>
        <Link className="mt-2 inline-block break-all font-semibold underline" to={`/operations/${encodeURIComponent(alert.operation_id)}`}>{alert.operation_id} · 결과·복구 확인</Link>
      </li>)}</ul>
    </>}
  </section>
}
