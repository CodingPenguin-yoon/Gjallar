import { randomUUID } from '../../shared/requestId.js'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { useVmChange } from '../../features/workloads/detail/useVmChange'

const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'
const size = bytes => bytes < 1024 ** 3 ? `${(bytes / 1024 ** 2).toFixed(2)} MiB` : `${(bytes / 1024 ** 3).toFixed(2)} GiB`
const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'

export default function MigratePage({ canOperate }) {
  const { vmid } = useParams()
  const [search] = useSearchParams()
  return <MigrateForm key={`${vmid}:${search}`} vmid={Number(vmid)} initialNode={search.get('node') || ''} initialDestination={search.get('destination_node') || ''} canOperate={canOperate} />
}

function MigrateForm({ vmid, initialNode, initialDestination, canOperate }) {
  const [node, setNode] = useState(initialNode)
  const [destination, setDestination] = useState(initialDestination)
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const { review, plan, setPlan, result, error, setError, busy, submitted, load, execute, resetReview } = useVmChange({
    vm: {nodeId: node, vmid}, operationType: 'vm_migrate', onUpdated: () => {},
    onReview: () => {setConfirmation(''); setAck(false)},
    read: async (nodeId, id) => {
      if (nodeId === destination) throw new Error('서로 다른 원본·목적 노드를 선택하세요.')
      const value = await apiV1Client.reviewVmMigration(nodeId, id, destination)
      if (value.observed_before?.destination?.node_id !== destination) throw new Error('조회한 목적 노드가 선택과 다릅니다.')
      return value
    }, mutate: apiV1Client.migrateVm,
  })
  const expected = review ? `${vmid}/${review.observed_before.name}/${node}->${destination}` : ''
  function prepare(event) {
    event.preventDefault()
    if (!ack || confirmation !== expected) {setError('VMID/이름/원본->목적 노드와 이동 영향을 확인하세요.'); return}
    setError('')
    setPlan({destination_node: destination, idempotency_key: randomUUID(),
      expected_name: review.observed_before.name, expected_review_digest: review.observed_before.review_digest,
      confirmation, migration_acknowledged: true})
  }
  const change = setter => event => {setter(event.target.value); resetReview()}
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">정지 VM 노드 이동</h1><p className="mt-2 text-sm text-slate-600">VM {vmid}의 위치를 같은 클러스터의 다른 노드로 옮깁니다. shared NFS 디스크와 게스트 설정은 유지합니다.</p></header>
    <Link className="text-sm font-semibold underline" to={`/instances/${vmid}`}>VM 상세·현재 위치</Link>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">이동 연결 권한 확인</Link></p>}
    {!canOperate ? <p>이동 검토·실행에는 operator 이상 권한이 필요합니다.</p> : <>
      <form onSubmit={event => {event.preventDefault(); load()}} className="space-y-4">
        <fieldset disabled={busy || submitted || Boolean(review)} className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">현재 원본 노드<input required className={input} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={node} onChange={change(setNode)} /></label>
          <label className="text-sm">목적 노드<input required className={input} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={destination} onChange={change(setDestination)} /></label>
        </fieldset>
        {!review && <button disabled={busy || submitted} className={button}>{busy ? '이동 조건 확인 중…' : '양쪽 노드·공유 자원 확인'}</button>}
        {review && !submitted && <button type="button" disabled={busy} onClick={resetReview} className={button}>대상 다시 선택</button>}
      </form>
      {review && !submitted && <form onSubmit={prepare} className="space-y-3 border-t pt-4">
        <h2 className="font-semibold">{vmid}/{review.observed_before.name} · {node} → {destination}</h2>
        <p className="text-sm">정지 · 자동 시작 꺼짐 · HA 비관리 · {review.observed_before.destination.pve_version}</p>
        <p className="text-sm">CPU {review.observed_before.destination.cpu_model} · bridge {review.observed_before.destination.bridge_id}</p>
        <ul className="space-y-1 text-sm">{review.observed_before.vm.volumes.map(volume => <li className="break-all" key={volume.slot}>{volume.slot}: {volume.volume_id} · {size(volume.size_bytes)}</li>)}</ul>
        {review.warnings.map(warning => <p className="text-sm text-amber-900" key={warning}>{warning}</p>)}
        <fieldset disabled={busy} className="space-y-3">
          <label className="block text-sm break-all">대상 확인: {expected}<input required autoComplete="off" className={input} value={confirmation} onChange={event => {setConfirmation(event.target.value); setPlan(null)}} /></label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => {setAck(event.target.checked); setPlan(null)}} />필요한 백업·목적 네트워크·부팅 호환성을 확인했고 외부 동시 변경을 중지했습니다. 이동 후 부팅·접속 검사는 별도로 진행합니다.</label>
          <button className={button}>이동 내용 검토</button>
        </fieldset>
      </form>}
      {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
        <p className="break-all font-semibold">{plan.confirmation}</p>
        <p className="text-sm">공유 디스크를 복사하지 않고 노드 위치를 이동합니다. 자동 시작·강제 이동은 하지 않습니다.</p>
        <button type="button" disabled={busy} onClick={execute} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">확인한 정지 VM 이동 실행</button>
      </div>}
      {submitted && <div role="status" className="space-y-3 rounded-lg bg-slate-50 p-4 text-sm">
        <p>{busy ? '이동 task·목적 위치·설정 보존 확인 중…' : result?.verified ? '목적 노드의 정지 VM과 설정·공유 디스크 보존을 확인했습니다. 부팅·접속은 아직 검증하지 않았습니다.' : '이동 결과가 미확정입니다. 원래 작업과 현재 VM 위치를 확인하세요. 자동 재이동·역이동하지 않았습니다.'}</p>
        {result?.verified && <p>확인한 위치: {result.observed_after?.node_id} / VM {vmid}</p>}
        <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
        {result?.verified && <Link className="block font-semibold underline" to={`/instances/${vmid}`}>이동된 VM 상세·별도 부팅 검사</Link>}
        <Link className="block font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vmid}`}>작업 결과·복구 확인</Link>
      </div>}
    </>}
  </section>
}
