import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { assertAccessEvidence, assertRecordedAccess, assertTemplateTestReport } from '../../features/workloads/templateTestResult'

const names = { boot: '부팅', cloud_init: 'cloud-init', network: '네트워크 IP 관찰', guest_agent: 'Guest agent', access: 'SSH 접속' }
const statuses = { passed: '확인', failed: '실패', not_verified: '확인 실패', not_run: '미실행', unavailable: '증거 없음' }

export default function TemplateTestPage({ canOperate = false }) {
  const { operationId } = useParams()
  return <TemplateTestReport key={operationId} operationId={operationId} canOperate={canOperate} />
}

function TemplateTestReport({ operationId, canOperate }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [replayed, setReplayed] = useState(false)
  const [requestId] = useState(() => crypto.randomUUID())
  const inFlight = useRef(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    apiV1Client.getTemplateTest(operationId).then(data => { if (alive.current) setReport(assertTemplateTestReport(data, operationId)) })
      .catch(failure => { if (alive.current) setError(failure.message) })
    return () => { alive.current = false }
  }, [operationId])

  async function record(event) {
    event.preventDefault()
    if (inFlight.current || submitted || !ack || !status || !report?.can_record_access || !canOperate) return
    inFlight.current = true; setBusy(true); setSubmitted(true); setError('')
    try {
      const check = { name: 'access', status, observed_at: new Date().toISOString() }
      const response = await apiV1Client.recordPostCreateReadinessEvidence(report.target.node_id, report.target.vmid, {
        create_operation_id: operationId, idempotency_key: requestId,
        post_create_readiness_evidence_acknowledged: true,
        summary: '템플릿 테스트 배포의 운영자 접속 확인',
        limitations: '운영자 직접 확인. Gjallar 접속 실행 없음.',
        checks: [check],
      })
      if (!alive.current) return
      const evidence = assertAccessEvidence(response, operationId, report.target, check)
      const next = await apiV1Client.getTemplateTest(operationId)
      if (alive.current) {
        setReport(assertRecordedAccess(next, operationId, report.target, evidence.check, evidence.artifact))
        setReplayed(evidence.replayed)
      }
    } catch (failure) {
      if (alive.current) setError(`${failure.message} 요청 ID ${requestId}를 보존하고 작업 기록을 확인하세요. 자동 재전송하지 않았습니다.`)
    } finally {
      if (alive.current) { setBusy(false); inFlight.current = false }
    }
  }

  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">템플릿 테스트 배포 검사</h1>
      <p className="mt-2 text-sm text-slate-600">생성 시 관찰한 기록입니다. 현재 VM 상태와 동일 VMID의 재사용 여부는 VM 상세에서 다시 확인하세요.</p></header>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
    {!report && !error && <p role="status">배포 검사 기록을 읽는 중…</p>}
    {report && <>
      <div className="rounded-lg bg-slate-50 p-4 text-sm"><p>테스트 VM: {report.target.node_id} · {report.target.vmid}/{report.target.name}</p>
        <p>원본 템플릿: {report.template_source?.node_id && report.template_source?.vmid ? `${report.template_source.node_id} · ${report.template_source.vmid}` : '기존 작업에 원본 식별자가 기록되지 않았습니다.'}</p>
        <p className="mt-2 font-semibold">{report.all_checks_passed ? '관찰 항목과 운영자 접속 확인을 모두 기록했습니다.' : '미확인 또는 실패 항목이 있습니다.'}</p></div>
      <ul className="grid gap-3 sm:grid-cols-2">{report.checks.map(check => <li key={check.name} className="rounded-lg border border-slate-200 p-4">
        <p className="font-semibold">{names[check.name] || check.name} · {statuses[check.status] || check.status}</p>
        <p className="mt-2 text-sm text-slate-600">{check.limitation}</p>
        {check.observed_at && <p className="mt-1 text-xs text-slate-500">기록 시각: {check.observed_at}</p>}
      </li>)}</ul>
      {canOperate && report.can_record_access && !submitted && <form onSubmit={record} className="space-y-3 rounded-lg border border-slate-200 p-4">
        <h2 className="font-semibold">직접 확인한 접속 결과 기록</h2>
        <p className="text-sm text-slate-600">VM 상세에서 대상 IP와 계정을 확인하고 본인의 SSH 클라이언트로 접속하세요. 비밀번호·개인키·명령 출력은 입력하지 않습니다.</p>
        <label className="block text-sm">SSH 접속 결과<select required value={status} onChange={event => setStatus(event.target.value)} className="mt-1 block w-full rounded-lg border p-2"><option value="">선택하세요</option><option value="passed">직접 접속 성공 확인</option><option value="failed">접속 실패 확인</option><option value="not_run">아직 시도하지 않음</option><option value="unavailable">확인할 수 없음</option></select></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)} />위 테스트 VM에 대한 제 확인 결과이며 자동 검사 결과가 아님을 확인합니다.</label>
        <button disabled={!ack || !status || busy} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">접속 결과 기록</button>
      </form>}
      {submitted && <p role="status" className="text-sm">{busy ? '접속 증거 기록과 작업 연결 확인 중…' : error ? '접속 결과 기록 상태를 확인하세요.' : replayed ? '같은 요청 ID에 저장된 기존 접속 결과를 확인했습니다.' : '접속 결과를 기록했습니다.'}</p>}
      <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm"><h2 className="font-semibold">테스트 VM 정리</h2><p>{report.cleanup.instruction}</p><p>원본 템플릿과 업로드 이미지 정리는 별도 작업입니다. 검사 완료가 자동 삭제를 실행하지 않습니다.</p>
        <Link className="font-semibold underline" to={`/instances/${report.target.vmid}`}>현재 VM 확인·정상 종료·삭제 검토</Link></div>
      <Link className="inline-block text-sm underline" to={`/operations/${encodeURIComponent(operationId)}`}>생성 작업과 증거 이력</Link>
    </>}
  </section>
}
