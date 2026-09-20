import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { useVmChange } from '../../features/workloads/detail/useVmChange'

const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'
const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'

export default function ImageCleanupPage({ canOperate }) {
  const [search] = useSearchParams()
  return canOperate ? <CleanupForm key={search.toString()} initial={search} /> : <p className="rounded-xl border bg-white p-6">소유 자원 정리는 operator 이상 권한이 필요합니다.</p>
}

function CleanupForm({ initial }) {
  const [node, setNode] = useState(initial.get('node') || '')
  const [vmid, setVmid] = useState(initial.get('vmid') || '')
  const [parent, setParent] = useState(initial.get('build') || '')
  const [resource, setResource] = useState(initial.get('resource') === 'source' ? 'source' : 'template')
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute, resetReview} = useVmChange({
    operationType: 'vm_image_cleanup',
    vm: {nodeId: node, vmid: Number(vmid)}, onUpdated: () => {},
    read: (nodeId, id) => apiV1Client.reviewImageCleanup(nodeId, id, parent, resource), mutate: apiV1Client.cleanupImageResource,
    onReview: () => { setConfirmation(''); setAck(false) },
  })
  function prepare(event) {
    event.preventDefault()
    const before = review.observed_before
    if (!ack || confirmation !== `${vmid}/${before.name}/${resource}`) { setError('VMID/이름/정리 종류와 영구 삭제 영향을 확인하세요.'); return }
    setError('')
    setPlan({parent_operation_id: parent, resource, expected_name: before.name, expected_review_digest: before.review_digest,
      idempotency_key: crypto.randomUUID(), confirmation, cleanup_acknowledged: true})
  }
  const otherResource = resource === 'template' ? 'source' : 'template'
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">제작한 자원 정리</h1><p className="mt-2 text-sm text-slate-600">완료된 공식 이미지 제작 기록으로 소유권을 확인합니다. 템플릿과 업로드 원본은 각각 검토한 뒤 삭제합니다.</p></header>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">정리 권한 확인</Link></p>}
    {!review && <form onSubmit={event => {event.preventDefault(); load()}} className="grid gap-4 sm:grid-cols-2">
      <fieldset disabled={busy || submitted} className="contents">
        <label className="text-sm">노드 이름<input required className={input} value={node} onChange={event => setNode(event.target.value)} /></label>
        <label className="text-sm">제작한 템플릿 VMID<input required type="number" min="100" max="999999999" className={input} value={vmid} onChange={event => setVmid(event.target.value)} /></label>
        <label className="text-sm sm:col-span-2">제작 Operation ID<input required className={input} value={parent} onChange={event => setParent(event.target.value)} /></label>
        <label className="text-sm sm:col-span-2">정리할 자원<select className={input} value={resource} onChange={event => setResource(event.target.value)}><option value="template">템플릿과 연결 disk</option><option value="source">업로드 원본 파일만</option></select></label>
      </fieldset>
      <p className="text-sm text-slate-600 sm:col-span-2">제작 VMID를 기존 관리 VM 범위로 등록하고 명시적 정리 storage와 image_cleanup 권한을 선택하세요. Datastore.Allocate는 PVE에서 넓은 storage 권한이므로 필요한 범위만 검토합니다.</p>
      <button disabled={busy || submitted} className={button}>{busy ? '소유 자원 확인 중…' : '삭제·보존 자원 확인'}</button>
    </form>}
    {review && !submitted && <form onSubmit={prepare} className="space-y-3">
      <h2 className="font-semibold">{node} · {vmid}/{review.observed_before.name} · {resource === 'template' ? '템플릿 삭제' : '업로드 원본 삭제'}</h2>
      <ul className="space-y-1 break-all text-sm">{review.observed_before.deleted_volumes.map(row => <li key={row.volume_id}>삭제: {row.volume_id} · {(row.size_bytes / 1024 ** 2).toLocaleString()} MiB</li>)}{review.observed_before.preserved_volumes.map(row => <li key={row.volume_id}>보존: {row.volume_id}</li>)}</ul>
      {review.warnings.map(warning => <p key={warning} className="text-sm text-amber-900">{warning}</p>)}
      <label className="block text-sm">대상 확인: {vmid}/{review.observed_before.name}/{resource}<input required autoComplete="off" className={input} value={confirmation} onChange={event => {setConfirmation(event.target.value); setPlan(null)}} /></label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => {setAck(event.target.checked); setPlan(null)}} />표시된 자원을 영구 삭제하며 자동 복구하지 않음을 확인했습니다.</label>
      <div className="flex gap-3"><button disabled={busy} className={button}>삭제 내용 검토</button><button type="button" className={button} onClick={resetReview}>대상 수정·다시 조회</button></div>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4"><p className="font-semibold">{plan.confirmation} 영구 삭제</p><p className="text-sm">외부 동시 변경을 중지한 상태에서 실행하세요.</p><button type="button" disabled={busy} className="rounded-lg bg-red-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={execute}>확인한 소유 자원을 영구 삭제</button></div>}
    {submitted && <div role="status" className="space-y-3 rounded-lg bg-slate-50 p-4 text-sm">
      <h2 className="font-semibold">{busy ? '삭제 작업과 실제 자원 부재 확인 중…' : result?.verified ? '선택한 자원 부재와 보존 조건을 확인했습니다.' : '삭제 결과 확인이 필요합니다. 새 요청으로 반복하지 마세요.'}</h2>
      <p>{plan.confirmation}</p><p className="break-all text-xs text-slate-500">요청 ID: {plan.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vmid}`}>정리 결과·복구 확인</Link>
      {result?.verified && <p><Link className="underline" to={`/instances/templates/cleanup?${new URLSearchParams({node, vmid, build: parent, resource: otherResource})}`}>{otherResource === 'source' ? '업로드 원본' : '템플릿'}도 별도로 검토</Link></p>}
    </div>}
  </section>
}
