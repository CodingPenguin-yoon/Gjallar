import { randomUUID } from '../../../shared/requestId.js'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../../shared/api/apiV1'
import { useVmChange } from './useVmChange'

const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'
const tagLabel = value => value == null ? 'untagged' : `VLAN ${value}`

export default function VmNetworkPanel({ vm, onUpdated }) {
  const [bridge, setBridge] = useState('')
  const [tag, setTag] = useState('')
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute} = useVmChange({
    operationType: 'vm_network',
    vm, onUpdated, read: apiV1Client.getVmNetwork, mutate: apiV1Client.setVmNetwork,
    onReview: before => {setBridge(before.bridge_id); setTag(before.vlan_tag == null ? '' : String(before.vlan_tag))},
  })
  function prepare(event) {
    event.preventDefault()
    const before = review.observed_before, value = tag === '' ? null : Number(tag)
    const selected = before.bridges.find(row => row.bridge_id === bridge)
    if (!selected || (value !== null && (!Number.isInteger(value) || value < 1 || value > 4094 || !selected.vlan_aware))) {
      setError('사용 가능한 bridge를 선택하세요. VLAN tag는 VLAN-aware bridge에서 1~4094로 지정할 수 있습니다.'); return
    }
    if (bridge === before.bridge_id && value === before.vlan_tag) {setError('현재 설정과 같습니다. 변경할 값이 없습니다.'); return}
    setError('')
    setPlan({idempotency_key: randomUUID(), expected_digest: before.digest, expected_name: before.name,
      expected_net0: before.net0, bridge_id: bridge, vlan_tag: value})
  }
  return <div className="mt-4 space-y-3 border-t border-slate-200 pt-4">
    <h4 className="font-semibold">네트워크 변경</h4>
    {!review && <button type="button" className={button} disabled={busy || vm.status !== 'stopped'} onClick={load}>네트워크 변경 준비</button>}
    {vm.status !== 'stopped' && <p className="text-sm text-slate-600">VM을 정상 종료한 후 변경할 수 있습니다.</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link to="/settings/proxmox" className="underline">연결 권한 확인</Link></p>}
    {review && !submitted && <form className="space-y-3" onSubmit={prepare}>
      <p className="text-sm">{vm.nodeId} / VM {vm.vmid} · {review.observed_before.name} · net0 · 정지 상태</p>
      <p className="text-sm">현재 {review.observed_before.bridge_id} / {tagLabel(review.observed_before.vlan_tag)} · {review.observed_before.model} / {review.observed_before.mac}</p>
      <div className="flex flex-wrap gap-4">
        <label className="text-sm">Bridge<select className="ml-2 rounded border border-slate-300 p-2" value={bridge}
          onChange={event => {setBridge(event.target.value); setPlan(null)}}>
          {review.observed_before.bridges.map(row => <option key={row.bridge_id} value={row.bridge_id}>{row.bridge_id}{row.vlan_aware ? ' · VLAN-aware' : ''}</option>)}
        </select></label>
        <label className="text-sm">VLAN tag<input type="number" min="1" max="4094" step="1" value={tag} placeholder="untagged"
          className="ml-2 w-32 rounded border border-slate-300 p-2" onChange={event => {setTag(event.target.value); setPlan(null)}} /></label>
      </div>
      <p className="text-xs text-slate-600">빈 tag는 untagged입니다. MAC·모델·나머지 NIC 옵션과 게스트 IP는 유지합니다. 다른 망으로 옮기면 기존 IP로 접속하지 못할 수 있습니다. VLAN trunk는 지원하지 않습니다.</p>
      <button className={button} disabled={busy}>네트워크 내용 검토</button>
      <button type="button" className={`${button} ml-2`} disabled={busy} onClick={load}>현재 네트워크 다시 조회</button>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-medium">net0: {review.observed_before.bridge_id} / {tagLabel(review.observed_before.vlan_tag)} → {plan.bridge_id} / {tagLabel(plan.vlan_tag)}</p>
      <p className="text-sm">정지 상태·현재 설정·bridge를 재확인하고 변경합니다. 게스트 통신은 별도로 확인해야 합니다.</p>
      <button type="button" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={execute}>이 내용으로 네트워크 변경</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '네트워크 설정·실제 결과 확인 중…' : result?.verified ? 'PVE의 NIC 설정 변경을 확인했습니다. 게스트 통신은 별도로 확인하세요.' : '변경 결과 확인이 필요합니다. 새 요청 전에 작업 이력을 확인하세요.'}</p>
      {result?.observed_after && <p>관찰된 net0: {result.observed_after.bridge_id} / {tagLabel(result.observed_after.vlan_tag)} · MAC {result.observed_after.mac}</p>}
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vm.vmid}`}>네트워크 결과·복구 확인</Link>
    </div>}
  </div>
}
