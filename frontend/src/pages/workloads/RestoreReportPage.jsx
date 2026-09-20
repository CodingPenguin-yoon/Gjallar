import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'

const names = {restore_task: '복원 완료 기록', source_preserved: '원본 보존', archive_preserved: '백업 보존', restored_configuration: '복원 VM 설정·disk', network_isolation: 'NIC 격리', power: 'QEMU 전원', guest_agent: 'Guest agent 응답'}
const statuses = {passed: '확인', not_verified: '불일치·미확인', unavailable: '조회 불가', not_run: '미실행', running: '실행 중', stopped: '정지'}

export default function RestoreReportPage() {
  const { operationId } = useParams()
  return <Report key={operationId} operationId={operationId} />
}

function Report({ operationId }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [revision, setRevision] = useState(0)
  const pending = useRef(false)
  useEffect(() => {
    let alive = true
    apiV1Client.getRestoreReport(operationId).then(value => {
      if (!alive) return
      if (value.operation_id !== operationId || value.read_only !== true) throw new Error('검사 보고서의 복원 작업이 다릅니다.')
      setReport(value)
    }).catch(failure => {if (alive) setError(failure.message)})
      .finally(() => {if (alive) {setBusy(false); pending.current = false}})
    return () => {alive = false}
  }, [operationId, revision])
  function refresh() {
    if (busy || pending.current) return
    pending.current = true; setBusy(true); setReport(null); setError(''); setRevision(value => value + 1)
  }
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">별도 VM 복원 검사</h1><p className="mt-2 text-sm text-slate-600">복원 완료 기록과 현재 조회를 구분합니다. 이 화면은 VM을 시작하거나 네트워크를 연결하지 않습니다.</p></header>
    <button type="button" disabled={busy} onClick={refresh} className="rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-50">현재 검사 다시 조회</button>
    {busy && <p role="status">복원 VM·원본·백업 상태 조회 중…</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
    {report && <>
      <div className="rounded-lg bg-slate-50 p-4 text-sm"><p>원본 {report.source.node_id} / {report.source.vmid} → 복원 {report.target.vmid}/{report.target.name}</p><p className="mt-2 text-xs">조회: {report.observed_at}</p><p className="mt-2">외부 접속 미검증 · 자동 부팅·정리 없음</p></div>
      <ul className="grid gap-3 sm:grid-cols-2">{report.checks.map(check => <li className="rounded-lg border p-4" key={check.name}><p className="font-semibold">{names[check.name] || check.name} · {statuses[check.status] || check.status}</p><p className="mt-2 text-sm text-slate-600">{check.limitation}</p></li>)}</ul>
      <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm"><h2 className="font-semibold">부팅 검사·정리</h2>{report.instructions.map(text => <p key={text}>{text}</p>)}<Link className="block font-semibold underline" to={`/instances/${report.target.vmid}`}>복원 VM 현재 상태·명시적 시작/정상 종료</Link></div>
    </>}
    <Link className="block text-sm font-semibold underline" to={`/operations/${encodeURIComponent(operationId)}`}>복원 작업 기록·복구 확인</Link>
  </section>
}
