import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../../shared/api/apiV1'
import { useVmChange } from './useVmChange'

const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'

export default function VmDeletePanel({ vm, onDeleted }) {
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute} = useVmChange({
    operationType: 'vm_delete',
    vm, onUpdated: onDeleted, read: apiV1Client.getVmDeletion, mutate: apiV1Client.deleteVm,
    onReview: () => {setConfirmation(''); setAck(false)},
  })
  function prepare(event) {
    event.preventDefault()
    const before = review.observed_before
    if (confirmation !== `${vm.vmid}/${before.name}` || !ack) {
      setError('VMID/이름을 그대로 입력하고 영구 삭제 영향을 확인하세요.'); return
    }
    setError('')
    setPlan({idempotency_key: crypto.randomUUID(), expected_digest: before.digest, expected_name: before.name,
      expected_resources_digest: before.resources_digest, confirmation, delete_acknowledged: true})
  }
  return <div className="mt-4 space-y-3 border-t border-red-200 pt-4">
    <h4 className="font-semibold text-red-900">VM 영구 삭제</h4>
    {!review && <button type="button" className={button} disabled={busy || vm.status !== 'stopped'} onClick={load}>삭제할 자원 확인</button>}
    {vm.status !== 'stopped' && <p className="text-sm text-slate-600">VM을 정상 종료한 후 삭제할 수 있습니다.</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link to="/settings/proxmox" className="underline">연결 권한 확인</Link></p>}
    {review && !submitted && <form className="space-y-3" onSubmit={prepare}>
      <p className="text-sm">{vm.nodeId} / VM {vm.vmid} · {review.observed_before.name}</p>
      <p className="text-sm font-semibold">삭제: VM 설정·전용 ACL·방화벽과 아래 연결 disk</p>
      <ul className="space-y-1 break-all text-sm">{review.observed_before.deleted_volumes.map(row => <li key={row.volume_id}>{row.slot} · {row.volume_id} · {row.size_bytes / 1024 ** 3} GiB</li>)}</ul>
      <p className="text-sm font-semibold">보존: 기존 backup·외부 backup job 설정과 검토된 미참조 volume</p>
      <ul className="space-y-1 break-all text-sm">{review.observed_before.preserved_volumes.map(row => <li key={row.volume_id}>{row.volume_id}</li>)}</ul>
      {!review.observed_before.preserved_volumes.length && <p className="text-xs text-slate-600">해당 storage에서 관찰된 미참조 volume 없음</p>}
      {review.warnings.map(warning => <p key={warning} className="text-sm text-red-900">{warning}</p>)}
      <label className="block text-sm">대상 확인: {vm.vmid}/{review.observed_before.name}
        <input required autoComplete="off" value={confirmation} className="mt-1 block w-full rounded border border-slate-300 p-2" onChange={event => {setConfirmation(event.target.value); setPlan(null)}} />
      </label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => {setAck(event.target.checked); setPlan(null)}} />위 자원을 영구 삭제하며 자동 복구할 수 없음을 확인했습니다.</label>
      <button className={button} disabled={busy}>삭제 내용 검토</button>
      <button type="button" className={`${button} ml-2`} disabled={busy} onClick={load}>자원 다시 조회</button>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4">
      <p className="font-semibold text-red-900">{plan.confirmation} 영구 삭제</p>
      <p className="text-sm">외부 관리자의 동시 변경을 중지하세요. 설정과 자원을 다시 확인한 뒤 한 번만 삭제하고, PVE 작업·VMID·volume 부재를 확인합니다.</p>
      <button type="button" className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={execute}>확인한 VM과 연결 disk 영구 삭제</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '삭제 작업·VMID·volume 부재 확인 중…' : '삭제 결과 확인이 필요합니다. 새 요청 전에 작업 이력과 실제 잔여 자원을 확인하세요.'}</p>
      {result?.observed_after && <p>남은 삭제 대상 volume: {result.observed_after.remaining_volumes?.join(', ') || '없음'} · 보존 미확인: {result.observed_after.preservation_unconfirmed?.join(', ') || '없음'}</p>}
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vm.vmid}`}>삭제 결과·복구 확인</Link>
    </div>}
  </div>
}
