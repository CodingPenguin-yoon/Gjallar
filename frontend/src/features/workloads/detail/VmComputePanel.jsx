import { useState } from 'react'
import { useVmChange } from './useVmChange'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../../shared/api/apiV1'

const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'

export default function VmComputePanel({ vm, onUpdated }) {
  const [cores, setCores] = useState('')
  const [memory, setMemory] = useState('')
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute} = useVmChange({
    operationType: 'vm_compute',
    vm, onUpdated, read: apiV1Client.getVmCompute, mutate: apiV1Client.setVmCompute,
    onReview: before => { setCores(String(before.cores)); setMemory(String(before.memory_mib)) },
  })

  function prepare(event) {
    event.preventDefault()
    const nextCores = Number(cores), nextMemory = Number(memory)
    if (!Number.isInteger(nextCores) || nextCores < 1 || nextCores > 128 || !Number.isInteger(nextMemory) || nextMemory < 128 || nextMemory > 1048576) {
      setError('CPU는 1~128 코어, 메모리는 128~1048576 MiB의 정수로 입력하세요.'); return
    }
    if (nextCores === review.observed_before.cores && nextMemory === review.observed_before.memory_mib) {
      setError('현재 설정과 같습니다. 변경할 값을 입력하세요.'); return
    }
    setError('')
    setPlan({idempotency_key: crypto.randomUUID(), expected_digest: review.observed_before.digest,
      expected_name: review.observed_before.name, cores: nextCores, memory_mib: nextMemory})
  }

  return <div className="mt-4 space-y-3 border-t border-slate-200 pt-4">
    <h4 className="font-semibold">CPU·메모리</h4>
    {!review && <button type="button" className={button} disabled={busy || vm.status !== 'stopped'} onClick={load}>CPU·메모리 변경 준비</button>}
    {vm.status !== 'stopped' && <p className="text-sm text-slate-600">VM을 정상 종료한 후 변경할 수 있습니다.</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">연결 권한 확인</Link></p>}
    {review && !submitted && <form onSubmit={prepare} className="space-y-3">
      <p className="text-sm">{vm.nodeId} / VM {vm.vmid} · {review.observed_before.name} · 정지 상태</p>
      <div className="flex flex-wrap gap-4">
        <label className="text-sm">CPU 코어 수<input className="ml-2 w-28 rounded border border-slate-300 p-2" type="number" min="1" max="128" step="1" required value={cores} onChange={event => { setCores(event.target.value); setPlan(null) }} /></label>
        <label className="text-sm">메모리 (MiB)<input className="ml-2 w-32 rounded border border-slate-300 p-2" type="number" min="128" max="1048576" step="1" required value={memory} onChange={event => { setMemory(event.target.value); setPlan(null) }} /></label>
      </div>
      <p className="text-xs text-slate-600">1024 MiB = 1 GiB. 단일 socket의 코어 수와 메모리만 변경하며 balloon·디스크·네트워크는 유지합니다.</p>
      <button className={button} disabled={busy}>변경 내용 검토</button>
      <button type="button" className={`${button} ml-2`} disabled={busy} onClick={load}>현재 설정 다시 조회</button>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-medium">CPU {review.observed_before.cores} → {plan.cores} 코어 · 메모리 {review.observed_before.memory_mib} → {plan.memory_mib} MiB</p>
      <p className="text-sm">서버에서 정지 상태·설정 변경 여부를 다시 확인하고 적용합니다. 실행 후 실제 설정을 재조회하며 게스트 성능은 별도 확인이 필요합니다.</p>
      <button type="button" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={execute}>이 내용으로 변경 실행</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '변경 결과 확인 중…' : result?.verified ? 'CPU·메모리 변경과 실제 설정을 확인했습니다.' : '결과 확인이 필요합니다. 새 변경 전에 작업 이력을 확인하세요.'}</p>
      {result?.observed_after && <p>관찰된 값: {result.observed_after.cores} 코어 · {result.observed_after.memory_mib} MiB · {result.observed_after.status}</p>}
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vm.vmid}`}>작업 결과·복구 확인</Link>
    </div>}
  </div>
}
