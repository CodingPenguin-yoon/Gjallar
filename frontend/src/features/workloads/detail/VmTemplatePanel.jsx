import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../../shared/api/apiV1'
import { useVmChange } from './useVmChange'

const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'

export default function VmTemplatePanel({ vm, onConverted }) {
  const [confirmation, setConfirmation] = useState('')
  const [prepared, setPrepared] = useState(false)
  const [ack, setAck] = useState(false)
  const { review, plan, setPlan, result, error, setError, busy, submitted, load, execute } = useVmChange({
    operationType: 'vm_template',
    vm, onUpdated: onConverted, read: apiV1Client.getVmTemplateConversion, mutate: apiV1Client.convertVmToTemplate,
    onReview: () => { setConfirmation(''); setPrepared(false); setAck(false) },
  })
  function prepare(event) {
    event.preventDefault()
    const before = review.observed_before
    if (confirmation !== `${vm.vmid}/${before.name}` || !ack || !prepared) {
      setError('VMID/이름과 게스트 준비·전환 영향을 모두 확인하세요.'); return
    }
    setError('')
    setPlan({ idempotency_key: crypto.randomUUID(), expected_digest: before.digest, expected_name: before.name,
      expected_resources_digest: before.resources_digest, confirmation, guest_prepared: true, conversion_acknowledged: true })
  }
  return <div className="mt-4 space-y-3 border-t border-slate-200 pt-4">
    <h4 className="font-semibold text-slate-900">준비된 VM을 템플릿으로 전환</h4>
    {!review && <button type="button" className={button} disabled={busy || vm.status !== 'stopped'} onClick={load}>전환 조건 확인</button>}
    {vm.status !== 'stopped' && <p className="text-sm text-slate-600">게스트 배포 준비를 마치고 VM을 정상 종료하세요.</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link to="/settings/proxmox" className="underline">연결 권한 확인</Link></p>}
    {review && !submitted && <form className="space-y-3" onSubmit={prepare}>
      <p className="text-sm">{vm.nodeId} / VM {vm.vmid} · {review.observed_before.name}</p>
      <ul className="space-y-1 break-all text-sm">{review.observed_before.volumes.map(row => <li key={row.volume_id}>{row.slot} · {row.volume_id} · {row.size_bytes / 1024 ** 3} GiB · {row.slot === 'scsi0' ? 'base image로 전환' : 'cloud-init 유지'}</li>)}</ul>
      {review.warnings.map(warning => <p key={warning} className="text-sm text-amber-900">{warning}</p>)}
      <label className="block text-sm">대상 확인: {vm.vmid}/{review.observed_before.name}
        <input required autoComplete="off" value={confirmation} className="mt-1 block w-full rounded border border-slate-300 p-2" onChange={event => { setConfirmation(event.target.value); setPlan(null) }} />
      </label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={prepared} onChange={event => { setPrepared(event.target.checked); setPlan(null) }} />계정·키·machine-id·SSH host key 재생성, cloud-init과 네트워크를 배포용으로 준비했습니다. 별도 테스트 배포가 필요함을 확인했습니다.</label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => { setAck(event.target.checked); setPlan(null) }} />원본 VM의 직접 부팅이 불가능해지며 자동 역변환하지 않음을 확인했습니다.</label>
      <button className={button} disabled={busy}>전환 내용 검토</button>
      <button type="button" className={`${button} ml-2`} disabled={busy} onClick={load}>조건 다시 조회</button>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-semibold">{plan.confirmation} 템플릿 전환</p>
      <p className="text-sm">외부 동시 변경을 중지하세요. 한 번만 전환하고 PVE 작업과 실제 template·base volume을 확인합니다.</p>
      <button type="button" className="rounded-lg bg-amber-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={execute}>확인한 VM을 템플릿으로 전환</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '전환 작업·template·volume 확인 중…' : '전환 결과 확인이 필요합니다. 일부 변경됐을 수 있으므로 자동 재전송하지 마세요.'}</p>
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vm.vmid}`}>전환 결과·복구 확인</Link>
    </div>}
  </div>
}
