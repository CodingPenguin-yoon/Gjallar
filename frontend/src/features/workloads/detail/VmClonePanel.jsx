import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../../shared/api/apiV1'
import { useVmChange } from './useVmChange'

const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'
const input = 'mt-1 block w-full rounded border border-slate-300 p-2'

export default function VmClonePanel({vm, onUpdated}) {
  const [newId, setNewId] = useState('')
  const [name, setName] = useState('')
  const [storage, setStorage] = useState('')
  const [ack, setAck] = useState(false)
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute} = useVmChange({
    operationType: 'vm_clone', operationVmidFromPlan: value => value.new_vmid,
    vm, onUpdated, mutate: apiV1Client.cloneVm,
    read: (node, vmid) => {
      if (!Number.isInteger(Number(newId)) || Number(newId) < 100 || Number(newId) > 999999999 || Number(newId) === Number(vmid) || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(storage)) throw new Error('서로 다른 새 VMID와 NFS storage ID를 입력하세요.')
      return apiV1Client.getVmClone(node, vmid, Number(newId), storage)
    },
    onReview: () => setAck(false),
  })
  const currentReview = review?.observed_before?.destination?.vmid === Number(newId) && review?.observed_before?.destination?.storage_id === storage
  function prepare(event) {
    event.preventDefault()
    if (!currentReview || !/^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$/.test(name) || !ack) {setError('현재 복제 범위를 조회하고 새 이름·guest identity 복사 위험을 확인하세요.'); return}
    const source = review.observed_before.source
    setError('')
    setPlan({idempotency_key:crypto.randomUUID(), expected_digest:source.digest, expected_name:source.name,
      expected_volume:source.volume_id, expected_size_bytes:source.size_bytes, new_vmid:Number(newId),
      name, storage_id:storage, guest_identity_acknowledged:true})
  }
  return <div className="mt-4 space-y-3 border-t border-slate-200 pt-4">
    <h4 className="font-semibold">VM full clone</h4>
    <p className="text-sm text-slate-600">원본 {vm.nodeId} / VM {vm.vmid}를 보존하고 같은 노드에 정지된 복제본을 만듭니다. 원본은 정지·자동 시작 꺼짐 상태여야 합니다.</p>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">연결 권한 확인</Link></p>}
    {!submitted && <form className="space-y-3" onSubmit={prepare}>
      <fieldset className="grid gap-3 sm:grid-cols-3" disabled={busy || vm.status !== 'stopped'}>
        <label className="text-sm">새 VMID<input className={input} type="number" min="100" max="999999999" step="1" required value={newId} onChange={event=>{setNewId(event.target.value);setPlan(null);setAck(false)}} /></label>
        <label className="text-sm">복제본 이름<input className={input} required maxLength="63" value={name} onChange={event=>{setName(event.target.value);setPlan(null)}} /></label>
        <label className="text-sm">대상 NFS storage ID<input className={input} required value={storage} onChange={event=>{setStorage(event.target.value);setPlan(null);setAck(false)}} /></label>
      </fieldset>
      <button type="button" className={button} disabled={busy || vm.status !== 'stopped'} onClick={load}>복제 원본·대상 확인</button>
      {currentReview && <div className="space-y-3">
        <p className="break-all text-sm">원본 {review.observed_before.source.name} · {review.observed_before.source.volume_id} · {review.observed_before.source.size_bytes / 1024**3} GiB → 새 VM {newId} / {storage}</p>
        {review.warnings?.map(warning=><p key={warning} className="text-xs text-slate-600">{warning}</p>)}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event=>{setAck(event.target.checked);setPlan(null)}} />게스트 IP·hostname·SSH host key가 복사되는 것을 확인했습니다. 충돌을 정리하기 전에 원본과 함께 시작하지 않겠습니다.</label>
        <button className={button} disabled={busy || !ack}>복제 내용 검토</button>
      </div>}
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-medium">VM {vm.vmid} → 새 VM {plan.new_vmid} · {plan.name} · {plan.storage_id}</p>
      <p className="text-sm">full clone으로 독립 디스크를 만듭니다. 새 MAC·UUID와 정지 상태를 확인하며 자동으로 시작하지 않습니다.</p>
      <button type="button" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={execute}>이 내용으로 VM 복제</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '복제 작업·원본 보존·새 VM 확인 중…' : result?.verified ? '원본 보존과 정지된 복제본을 확인했습니다. 시작 전에 guest identity·IP를 정리하세요.' : '복제 결과 확인이 필요합니다. 새 요청이나 잔여 자원 삭제 전에 Operation을 확인하세요.'}</p>
      {result?.observed_after?.destination && <p>새 VM {result.observed_after.destination.vmid} · {result.observed_after.destination.name} · {result.observed_after.destination.status} · MAC {result.observed_after.destination.mac}</p>}
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      {result?.verified && <Link className="mr-3 font-semibold underline" to={`/instances/${plan.new_vmid}`}>복제본 상세</Link>}
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${plan?.new_vmid}`}>복제 결과·복구 확인</Link>
    </div>}
  </div>
}
