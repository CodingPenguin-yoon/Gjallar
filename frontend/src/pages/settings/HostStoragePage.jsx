import { randomUUID } from '../../shared/requestId.js'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { assertStorageResult, sameConfiguration } from '../../features/hostConfiguration/result'

const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'
const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'
const contentKinds = ['images', 'iso', 'backup', 'import', 'snippets', 'vztmpl', 'rootdir']
const nodes = config => config.all_nodes ? '모든 노드 (클러스터 공용)' : config.nodes.join(', ')

export default function HostStoragePage() {
  const [node, setNode] = useState('')
  const [storage, setStorage] = useState('')
  const [mode, setMode] = useState('create')
  const [directory, setDirectory] = useState('')
  const [content, setContent] = useState(['images'])
  const [enabled, setEnabled] = useState(true)
  const [review, setReview] = useState(null)
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const [plan, setPlan] = useState(null)
  const [result, setResult] = useState(null)
  const [operationId, setOperationId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const target = {node_id: node, storage_id: storage}
  const change = {mode, path: mode === 'create' ? directory : null, content: [...content].sort(), enabled: mode === 'create' || enabled}
  function reset() {setReview(null); setPlan(null); setConfirmation(''); setAck(false); setError('')}
  async function load(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const value = await apiV1Client.reviewHostStorage(node, storage, change)
      if (!sameConfiguration(value.target, target) || value.mode !== mode || !/^sha256:[a-f0-9]{64}$/.test(value.review_digest)
          || value.confirmation !== `${node}/${storage}/${mode}` || !sameConfiguration(value.desired?.content, change.content)
          || value.desired?.enabled !== change.enabled || (mode === 'create' && value.desired?.path !== directory)) {
        throw new Error('서버가 반환한 storage 검토 대상과 변경 내용이 다릅니다.')
      }
      setReview(value)
    } catch (failure) {setError(failure.message)} finally {setBusy(false)}
  }
  function prepare(event) {
    event.preventDefault()
    if (!ack || confirmation !== review.confirmation) {setError('대상 확인 문구와 클러스터 영향을 확인하세요.'); return}
    setError(''); setPlan({...change, idempotency_key: randomUUID(), expected_review_digest: review.review_digest,
      confirmation, acknowledge_cluster_impact: true})
  }
  async function execute() {
    if (busy || submitted || !plan) return
    setBusy(true); setSubmitted(true); setError('')
    try {
      const value = await apiV1Client.configureHostStorage(node, storage, plan)
      const id = value.operation_id
      if (!id) throw new Error('실행 응답에 Operation ID가 없습니다.')
      setOperationId(id || '')
      const observed = await apiV1Client.getOperation(id)
      setResult(assertStorageResult(observed, id, target, plan))
    } catch (failure) {setError(`실행 결과를 확정하지 못했습니다. 자동 재전송하지 않았습니다. 요청 ID ${plan.idempotency_key}를 보존하고 Operations에서 확인하세요. ${failure.message}`)}
    finally {setBusy(false)}
  }
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">호스트 storage 설정</h1><p className="mt-2 text-sm text-slate-600">기존 디렉터리를 등록하거나 directory storage의 content·사용 여부를 변경합니다. 설정은 클러스터 공용이며 실제 활성 확인은 선택 노드에서 수행합니다.</p></header>
    <Link to="/settings/proxmox" className="text-sm font-semibold underline">호스트 storage 연결 권한 갱신</Link>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 break-all">{error}</p>}
    <form onSubmit={load} className="space-y-4">
      <fieldset disabled={busy || submitted || Boolean(review)} className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">활성 상태를 확인할 노드<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={node} onChange={e => setNode(e.target.value)} /></label>
        <label className="text-sm">Storage ID<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={storage} onChange={e => setStorage(e.target.value)} /></label>
        <label className="text-sm">작업<select className={input} value={mode} onChange={e => setMode(e.target.value)}><option value="create">기존 디렉터리 새 등록</option><option value="update">기존 storage 수정</option></select></label>
        {mode === 'create' ? <label className="text-sm">기존 디렉터리 절대 경로<input className={input} required placeholder="/mnt/existing" value={directory} onChange={e => setDirectory(e.target.value)} /></label>
          : <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />Storage 사용</label>}
        <div className="sm:col-span-2"><p className="text-sm">변경 후 허용할 content</p><div className="mt-2 flex flex-wrap gap-4">{contentKinds.map(kind => <label className="flex gap-2 text-sm" key={kind}><input type="checkbox" checked={content.includes(kind)} onChange={e => setContent(e.target.checked ? [...content, kind] : content.filter(value => value !== kind))} />{kind}</label>)}</div></div>
      </fieldset>
      {!review && <button className={button} disabled={busy || submitted || !content.length}>{busy ? '설정 확인 중…' : '변경 내용 조회·검토'}</button>}
      {review && !submitted && <button className={button} type="button" disabled={busy} onClick={reset}>입력 다시 선택</button>}
    </form>
    {review && <div className="space-y-3 border-t pt-4">
      <h2 className="font-semibold">{storage} · {mode === 'create' ? '새 등록' : '설정 수정'}</h2>
      <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="text-slate-500">보존·등록 경로</dt><dd className="break-all">{review.desired.path}</dd></div><div><dt className="text-slate-500">설정 영향 노드</dt><dd>{nodes(review.desired)}</dd></div>
        <div><dt className="text-slate-500">허용 content</dt><dd>{review.observed_before?.content.join(', ') || '미등록'} → {review.desired.content.join(', ')}</dd></div><div><dt className="text-slate-500">사용 여부</dt><dd>{review.observed_before ? (review.observed_before.enabled ? '사용' : '중지') : '미등록'} → {review.desired.enabled ? '사용' : '중지'}</dd></div></dl>
      <p className="text-sm">기본·하위 디렉터리 자동 생성: 꺼짐. 기존 경로·파일·volume을 이동하거나 삭제하지 않습니다.</p>
      {review.warnings.map(warning => <p key={warning} className="text-sm text-amber-900">{warning}</p>)}
      {!submitted && <form onSubmit={prepare} className="space-y-3"><fieldset disabled={busy} className="space-y-3">
        <label className="block text-sm break-all">대상 확인: {review.confirmation}<input required autoComplete="off" className={input} value={confirmation} onChange={e => {setConfirmation(e.target.value); setPlan(null)}} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => {setAck(e.target.checked); setPlan(null)}} />기존 directory와 설정 영향 노드를 확인했습니다. 외부 동시 변경을 중지했고 자동 디렉터리 생성 해제·content·사용 여부 변경에 동의합니다.</label>
        <button className={button}>최종 실행 내용 확인</button></fieldset></form>}
    </div>}
    {plan && !submitted && <div className="space-y-3 rounded-lg bg-amber-50 p-4"><p className="font-semibold">{review.confirmation} 설정을 한 번 변경합니다.</p><p className="text-sm">선택 노드 {node}에서 결과를 확인합니다. 다른 노드 활성·하위 content 디렉터리·실제 작성은 별도 검증입니다.</p><button type="button" className={button} disabled={busy} onClick={execute}>확인한 storage 설정 실행</button></div>}
    {result && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4"><h2 className="font-semibold">{result.verified ? '설정 결과 확인 완료' : '설정 결과 확인 필요'}</h2>
      {!result.verified && <p className="text-sm">작업 조정과 결과 확인이 끝나지 않았습니다. 새 요청으로 반복하지 말고 Operation에서 잠금·복구 상태를 확인하세요.</p>}
      <p className="text-sm">{result.details?.observed_after?.activation_checked ? `선택 노드 활성: ${result.details.observed_after.active ? '확인' : '미확인'}` : '활성 검사를 완료하지 않았습니다. 사용 중지 설정은 unmount를 뜻하지 않습니다.'}</p>
      <p className="text-sm">하위 content 디렉터리와 실제 VM·백업 작성은 별도로 확인하세요.</p></div>}
    {operationId && <Link className="inline-block text-sm font-semibold underline" to={`/operations/${encodeURIComponent(operationId)}`}>Operation·변경 결과·복구 관찰</Link>}
  </section>
}
