import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { useVmChange } from '../../features/workloads/detail/useVmChange'

const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'
const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'
const gib = value => Number.isFinite(value) ? `${(value / 1024 ** 3).toFixed(2)} GiB` : '확인 불가'

export default function RestorePage({ canOperate }) {
  const { vmid } = useParams()
  const [search] = useSearchParams()
  return <RestoreForm key={`${vmid}:${search}`} vmid={Number(vmid)} initial={search} canOperate={canOperate} />
}

function RestoreForm({ vmid, initial, canOperate }) {
  const [node, setNode] = useState(initial.get('node') || '')
  const [archive, setArchive] = useState(initial.get('archive') || '')
  const [newVmid, setNewVmid] = useState('')
  const [storage, setStorage] = useState('')
  const [bridge, setBridge] = useState('')
  const [name, setName] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const { review, plan, setPlan, result, error, setError, busy, submitted, load, execute, resetReview } = useVmChange({
    vm: {nodeId: node, vmid}, operationType: 'vm_restore', operationVmidFromPlan: value => value.new_vmid,
    onUpdated: () => {}, onReview: () => {setConfirmation(''); setAck(false)},
    read: async (nodeId, id) => {
      const data = await apiV1Client.reviewVmRestore(nodeId, id, {archive, new_vmid: Number(newVmid), storage_id: storage, bridge_id: bridge})
      const before = data.observed_before
      if (before?.archive?.file?.volume_id !== archive || before?.destination?.vmid !== Number(newVmid)
          || before.destination.storage_id !== storage || before.destination.bridge_id !== bridge) throw new Error('조회한 archive·복원 대상이 다릅니다.')
      return data
    }, mutate: apiV1Client.restoreVmBackup,
  })
  function prepare(event) {
    event.preventDefault()
    if (!ack || confirmation !== `${vmid}/${newVmid}/${name}`) {setError('원본/새 VMID/이름과 격리 복원 영향을 확인하세요.'); return}
    setError('')
    setPlan({archive, new_vmid: Number(newVmid), name, storage_id: storage, bridge_id: bridge,
      idempotency_key: crypto.randomUUID(), expected_name: review.observed_before.name,
      expected_review_digest: review.observed_before.review_digest, confirmation, isolation_acknowledged: true})
  }
  const change = setter => event => {setter(event.target.value); resetReview()}
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">백업을 별도 VM으로 복원</h1><p className="mt-2 text-sm text-slate-600">원본 VM {vmid}와 백업은 보존합니다. 새 VM은 정지·자동 시작 해제·NIC 링크가 끊어진 상태로 복원합니다.</p></header>
    <Link className="text-sm font-semibold underline" to={`/instances/${vmid}/backups?${new URLSearchParams({node, storage: archive.split(':')[0]})}`}>원본 백업 목록</Link>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">복원 연결 권한 확인</Link></p>}
    {!canOperate ? <p>복원 검토·실행에는 operator 이상 권한이 필요합니다.</p> : <>
      <form onSubmit={event => {event.preventDefault(); load()}} className="space-y-4">
        <fieldset disabled={busy || submitted || Boolean(review)} className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">노드 이름<input required className={input} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={node} onChange={change(setNode)} /></label>
          <label className="text-sm">새 VMID<input required type="number" min="100" max="999999999" className={input} value={newVmid} onChange={change(setNewVmid)} /></label>
          <label className="text-sm sm:col-span-2">원본 백업 volume ID<input required maxLength="255" className={input} value={archive} onChange={change(setArchive)} /></label>
          <label className="text-sm">복원 대상 NFS images storage<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={storage} onChange={change(setStorage)} /></label>
          <label className="text-sm">Linux bridge (NIC 링크 끊김 유지)<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={bridge} onChange={change(setBridge)} /></label>
        </fieldset>
        {!review && <button disabled={busy || submitted} className={button}>{busy ? '복원 조건 확인 중…' : '복원 조건·영향 확인'}</button>}
        {review && !submitted && <button type="button" disabled={busy} onClick={resetReview} className={button}>대상 다시 선택</button>}
      </form>
      {review && !submitted && <form onSubmit={prepare} className="space-y-3 border-t pt-4">
        <h2 className="font-semibold">{vmid}/{review.observed_before.name} → 새 VM {newVmid}</h2>
        <p className="text-sm">백업 disk {gib(review.observed_before.archive.configuration.size_bytes)} · 필요 공간 {gib(review.observed_before.archive.configuration.required_free_bytes)} · 조회 당시 가용 {gib(review.observed_before.available_bytes)}</p>
        <p className="text-sm">{storage} / {bridge} · 새 MAC {review.observed_before.destination.mac} · NIC 링크 끊김</p>
        {review.warnings.map(warning => <p className="text-sm text-amber-900" key={warning}>{warning}</p>)}
        <fieldset disabled={busy} className="space-y-3">
          <label className="block text-sm">새 VM 이름<input required pattern="[A-Za-z0-9][A-Za-z0-9.-]{0,62}" className={input} value={name} onChange={event => {setName(event.target.value); setPlan(null)}} /></label>
          <label className="block text-sm">대상 확인: {vmid}/{newVmid}/{name || '새 이름'}<input required autoComplete="off" className={input} value={confirmation} onChange={event => {setConfirmation(event.target.value); setPlan(null)}} /></label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => {setAck(event.target.checked); setPlan(null)}} />원본 identity가 복사됨을 이해했고, NIC 격리·공간·IO 영향과 외부 동시 변경 중지를 확인했습니다.</label>
          <button className={button}>복원 내용 검토</button>
        </fieldset>
      </form>}
      {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
        <p className="font-semibold">{plan.confirmation} · {plan.storage_id} · {plan.bridge_id}</p><p className="text-sm">기존 VM 덮어쓰기 없이 새 VM을 복원합니다. 자동 시작·NIC 연결·자동 정리는 하지 않습니다.</p>
        <button type="button" disabled={busy} onClick={execute} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">확인한 격리 복원 실행</button>
      </div>}
      {submitted && <div role="status" className="space-y-3 rounded-lg bg-slate-50 p-4 text-sm">
        <p>{busy ? '복원 task·disk·원본 보존 확인 중…' : result?.verified ? '별도 VM 복원·NIC 격리·원본과 백업 보존을 확인했습니다. 부팅 검사는 아직 하지 않았습니다.' : '복원 결과가 미확정입니다. 작업을 확인하고 자동 재복원·삭제하지 마세요.'}</p>
        <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
        {result?.verified && <Link className="block font-semibold underline" to={`/instances/restore-tests/${encodeURIComponent(result.operation_id)}`}>복원 검사·명시적 부팅·정리 안내</Link>}
        <Link className="block font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${newVmid}`}>작업 결과·복구 확인</Link>
      </div>}
    </>}
  </section>
}
