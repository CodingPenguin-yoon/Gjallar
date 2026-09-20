import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { assertBridgeResult, normalizeVlanIds, sameConfiguration } from '../../features/hostConfiguration/result'

const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'
const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'
const enabled = value => value ? '사용' : '해제'

export default function HostNetworkPage() {
  const [node, setNode] = useState('')
  const [bridge, setBridge] = useState('')
  const [mode, setMode] = useState('create')
  const [autostart, setAutostart] = useState(true)
  const [vlanAware, setVlanAware] = useState(false)
  const [vlanIds, setVlanIds] = useState('')
  const [review, setReview] = useState(null)
  const [reviewInput, setReviewInput] = useState(null)
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const [plan, setPlan] = useState(null)
  const [result, setResult] = useState(null)
  const [operationId, setOperationId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const target = {node_id: node, bridge_id: bridge}

  function reset() {
    setReview(null); setReviewInput(null); setPlan(null); setConfirmation(''); setAck(false); setError('')
  }
  async function load(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const change = {mode, autostart, vlan_aware: vlanAware, vlan_ids: vlanAware ? normalizeVlanIds(vlanIds) : null}
      const value = await apiV1Client.reviewHostNetwork(node, bridge, change)
      if (!sameConfiguration(value.target, target) || value.mode !== mode || !/^sha256:[a-f0-9]{64}$/.test(value.review_digest)
          || value.confirmation !== `${node}/${bridge}/${mode}`
          || ['autostart', 'vlan_aware', 'vlan_ids'].some(key => value.desired?.[key] !== change[key])) {
        throw new Error('서버가 반환한 bridge 검토 대상과 변경 내용이 다릅니다.')
      }
      setReview(value); setReviewInput(change)
    } catch (failure) {setError(failure.message)} finally {setBusy(false)}
  }
  function prepare(event) {
    event.preventDefault()
    if (!ack || confirmation !== review.confirmation) {setError('대상 확인 문구와 노드 전체 반영 영향을 확인하세요.'); return}
    setError(''); setPlan({...reviewInput, idempotency_key: crypto.randomUUID(), expected_review_digest: review.review_digest,
      confirmation, acknowledge_node_reload: true})
  }
  async function execute() {
    if (busy || submitted || !plan) return
    setBusy(true); setSubmitted(true); setError('')
    try {
      const value = await apiV1Client.configureHostNetwork(node, bridge, plan)
      const id = value.operation_id
      if (!id) throw new Error('실행 응답에 Operation ID가 없습니다.')
      setOperationId(id)
      setResult(assertBridgeResult(await apiV1Client.getOperation(id), id, target, plan))
    } catch (failure) {
      setError(`실행 결과를 확정하지 못했습니다. 자동 재전송하지 않았습니다. 요청 ID ${plan.idempotency_key}를 보존하고 Operations에서 확인하세요. ${failure.message}`)
    } finally {setBusy(false)}
  }
  const observed = result?.details?.observed_after
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">호스트 bridge 설정</h1>
      <p className="mt-2 text-sm text-slate-600">VM용 Linux bridge의 자동 시작·VLAN 설정을 변경합니다. 새 bridge는 물리 port 없는 내부 연결용이며 기존 bridge의 port·주소는 변경하지 않습니다.</p></header>
    <Link to="/settings/proxmox" className="text-sm font-semibold underline">호스트 network 연결 권한 갱신</Link>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 break-all">{error}</p>}
    <form onSubmit={load} className="space-y-4">
      <fieldset disabled={busy || submitted || Boolean(review)} className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">설정을 변경할 노드<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={node} onChange={e => setNode(e.target.value)} /></label>
        <label className="text-sm">Bridge 이름<input required pattern="vmbr[0-9]{1,4}" placeholder="vmbr40" className={input} value={bridge} onChange={e => setBridge(e.target.value)} /></label>
        <label className="text-sm">작업<select className={input} value={mode} onChange={e => setMode(e.target.value)}><option value="create">내부 VM bridge 새 생성</option><option value="update">기존 VM bridge 수정</option></select></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={autostart} onChange={e => setAutostart(e.target.checked)} />호스트 부팅 시 자동 시작</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={vlanAware} onChange={e => setVlanAware(e.target.checked)} />VLAN-aware 사용</label>
        {vlanAware && <label className="text-sm">허용 VLAN (공백 구분 ID·범위)<input required placeholder="10 20-30" className={input} value={vlanIds} onChange={e => setVlanIds(e.target.value)} /></label>}
      </fieldset>
      {!review && <button className={button} disabled={busy || submitted}>{busy ? '설정 확인 중…' : '변경 내용 조회·검토'}</button>}
      {review && !submitted && <button className={button} type="button" disabled={busy} onClick={reset}>입력 다시 선택</button>}
    </form>
    {review && <div className="space-y-3 border-t pt-4">
      <h2 className="font-semibold">{node} / {bridge} · {mode === 'create' ? '새 생성' : '설정 수정'}</h2>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="text-slate-500">보존할 bridge port</dt><dd>{review.desired.ports.join(', ') || '없음 · 내부 VM 연결'}</dd></div>
        <div><dt className="text-slate-500">자동 시작</dt><dd>{review.observed_before ? enabled(review.observed_before.autostart) : '미등록'} → {enabled(review.desired.autostart)}</dd></div>
        <div><dt className="text-slate-500">VLAN-aware</dt><dd>{review.observed_before ? enabled(review.observed_before.vlan_aware) : '미등록'} → {enabled(review.desired.vlan_aware)}</dd></div>
        <div><dt className="text-slate-500">허용 VLAN</dt><dd>{review.observed_before?.vlan_ids || '미사용'} → {review.desired.vlan_ids || '미사용'}</dd></div>
      </dl>
      <div className="space-y-2 rounded-lg bg-amber-50 p-3">{review.warnings.map(warning => <p key={warning} className="text-sm text-amber-900">{warning}</p>)}</div>
      {!submitted && <form onSubmit={prepare} className="space-y-3"><fieldset disabled={busy} className="space-y-3">
        <label className="block text-sm break-all">대상 확인: {review.confirmation}<input required autoComplete="off" className={input} value={confirmation} onChange={e => {setConfirmation(e.target.value); setPlan(null)}} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => {setAck(e.target.checked); setPlan(null)}} />노드 전체 네트워크 반영·PVE SDN 설정 생성과 접속 단절 가능성을 확인했습니다. 외부 동시 변경을 중지했고 저장·반영에 동의합니다.</label>
        <button className={button}>최종 실행 내용 확인</button>
      </fieldset></form>}
    </div>}
    {plan && !submitted && <div className="space-y-3 rounded-lg bg-amber-50 p-4">
      <p className="font-semibold">{review.confirmation} 설정을 저장하고 노드 전체 네트워크에 반영합니다.</p>
      <p className="text-sm">저장된 변경이 검토와 일치할 때 한 번 반영합니다. 중단·응답 유실 시 자동 재실행하지 않습니다.</p>
      <button type="button" className={button} disabled={busy} onClick={execute}>확인한 bridge 저장·노드 전체 반영</button>
    </div>}
    {result && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4">
      <h2 className="font-semibold">{result.verified ? '설정 반영 결과 확인 완료' : '설정 반영 결과 확인 필요'}</h2>
      <p className="text-sm">{result.verified ? 'PVE 반영 task·대기 변경 없음·설정 보존을 확인했습니다.' : '저장·반영이 일부만 끝났거나 결과가 미확정입니다. Operation에서 각 단계와 복구 관찰을 확인하세요.'}</p>
      {observed && <p className="text-sm">현재 bridge 활성: {observed.configuration.active ? '확인' : '미확인'}. 자동 시작 해제는 즉시 down 완료를 뜻하지 않습니다.</p>}
      <p className="text-sm">VM 접속·VLAN 통신과 커널 VLAN table은 별도 검사입니다.</p>
    </div>}
    {operationId && <Link className="inline-block text-sm font-semibold underline" to={`/operations/${encodeURIComponent(operationId)}`}>Operation·단계별 결과·복구 관찰</Link>}
  </section>
}
