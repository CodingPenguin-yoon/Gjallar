import { randomUUID } from '../../../shared/requestId.js'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../../shared/api/apiV1'
import { useVmChange } from './useVmChange'

const GIB = 1024 ** 3
const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'

export default function VmDiskPanel({ vm, onUpdated }) {
  const [size, setSize] = useState('')
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute} = useVmChange({
    operationType: 'vm_disk_resize',
    vm, onUpdated, read: apiV1Client.getVmDisk, mutate: apiV1Client.resizeVmDisk,
    onReview: before => setSize(String(Math.floor(before.size_bytes / GIB) + 1)),
  })
  function prepare(event) {
    event.preventDefault()
    const value = Number(size), before = review.observed_before
    if (!Number.isInteger(value) || value < 1 || value > 65536 || value * GIB <= before.size_bytes) {
      setError('현재 실제 용량보다 큰 1~65536 GiB 정수를 입력하세요. 축소는 지원하지 않습니다.'); return
    }
    setError('')
    setPlan({idempotency_key: randomUUID(), expected_digest: before.digest, expected_name: before.name,
      expected_volume: before.volume_id, expected_size_bytes: before.size_bytes, size_gib: value})
  }
  return <div className="mt-4 space-y-3 border-t border-slate-200 pt-4">
    <h4 className="font-semibold">디스크 확장</h4>
    {!review && <button type="button" className={button} disabled={busy || vm.status !== 'stopped'} onClick={load}>디스크 확장 준비</button>}
    {vm.status !== 'stopped' && <p className="text-sm text-slate-600">VM을 정상 종료한 후 확장할 수 있습니다.</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link to="/settings/proxmox" className="underline">연결 권한 확인</Link></p>}
    {review && !submitted && <form className="space-y-3" onSubmit={prepare}>
      <p className="text-sm">{vm.nodeId} / VM {vm.vmid} · {review.observed_before.name} · scsi0 · 정지 상태</p>
      <p className="break-all text-sm">{review.observed_before.volume_id} · 실제 용량 {review.observed_before.size_bytes / GIB} GiB</p>
      <label className="text-sm">확장 후 전체 용량 (GiB)<input type="number" required min="1" max="65536" step="1" value={size}
        className="ml-2 w-32 rounded border border-slate-300 p-2" onChange={event => {setSize(event.target.value); setPlan(null)}} /></label>
      <p className="text-xs text-slate-600">추가할 용량이 아닌 전체 용량입니다. NFS의 scsi0 raw/qcow2만 지원합니다. 확장 후 축소할 수 없고 게스트 partition·filesystem 확장은 별도입니다.</p>
      <button className={button} disabled={busy}>확장 내용 검토</button>
      <button type="button" className={`${button} ml-2`} disabled={busy} onClick={load}>현재 디스크 다시 조회</button>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-medium">scsi0: {review.observed_before.size_bytes / GIB} → {plan.size_gib} GiB</p>
      <p className="text-sm">정지 상태와 설정을 다시 확인하고 확장합니다. PVE 작업 완료와 실제 volume 용량을 모두 확인합니다.</p>
      <button type="button" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={execute}>이 내용으로 디스크 확장</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '확장 작업·실제 용량 확인 중…' : result?.verified ? '디스크 확장과 실제 용량을 확인했습니다. 게스트 filesystem은 별도로 확장하세요.' : '확장 결과 확인이 필요합니다. 새 요청 전에 작업 이력을 확인하세요.'}</p>
      {result?.observed_after && <p>관찰된 실제 용량: {result.observed_after.size_bytes / GIB} GiB · {result.observed_after.status}</p>}
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vm.vmid}`}>확장 결과·복구 확인</Link>
    </div>}
  </div>
}
