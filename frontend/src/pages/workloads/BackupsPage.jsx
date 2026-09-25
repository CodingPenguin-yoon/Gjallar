import { randomUUID } from '../../shared/requestId.js'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { useVmChange } from '../../features/workloads/detail/useVmChange'

const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'
const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'
const gib = value => Number.isFinite(value) ? `${(value / 1024 ** 3).toFixed(2)} GiB` : '확인 불가'

export default function BackupsPage({ canOperate }) {
  const { vmid } = useParams()
  const [search] = useSearchParams()
  return <BackupForm key={`${vmid}:${search}`} vmid={Number(vmid)} initial={search} canOperate={canOperate} />
}

function BackupForm({ vmid, initial, canOperate }) {
  const [node, setNode] = useState(initial.get('node') || '')
  const [storage, setStorage] = useState(initial.get('storage') || '')
  const [listing, setListing] = useState(null)
  const [listingBusy, setListingBusy] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const listGeneration = useRef(0)
  const listPending = useRef(false)
  useEffect(() => () => { listGeneration.current += 1 }, [])
  const {review, plan, setPlan, result, error, setError, busy, submitted, load, execute, resetReview} = useVmChange({
    vm: {nodeId: node, vmid}, operationType: 'vm_backup',
    onUpdated: updated => setListing(current => ({...current, archives: updated.observed_after.archives, available_bytes: updated.observed_after.available_bytes})),
    read: async (nodeId, id) => {
      const data = await apiV1Client.reviewVmBackup(nodeId, id, storage)
      if (data.observed_before?.storage_id !== storage) throw new Error('백업 storage가 선택한 대상과 다릅니다.')
      return data
    }, mutate: apiV1Client.createVmBackup,
    onReview: () => { setConfirmation(''); setAck(false) },
  })
  const locked = busy || listingBusy || submitted
  async function list(event) {
    event.preventDefault()
    if (listPending.current || locked) return
    listPending.current = true
    const generation = ++listGeneration.current
    setListingBusy(true); setListing(null); setError(''); resetReview()
    try {
      const data = await apiV1Client.listVmBackups(node, vmid, storage)
      if (generation !== listGeneration.current) return
      if (data.target.node_id !== node || data.target.vmid !== vmid || data.target.storage_id !== storage) throw new Error('백업 목록의 대상이 다릅니다.')
      setListing(data)
    } catch (failure) {
      if (generation === listGeneration.current) setError(failure.message)
    } finally {
      if (generation === listGeneration.current) { setListingBusy(false); listPending.current = false }
    }
  }
  function prepare(event) {
    event.preventDefault()
    const before = review.observed_before
    if (!ack || confirmation !== `${vmid}/${before.name}`) { setError('VMID/이름과 공간·IO 영향을 확인하세요.'); return }
    setError('')
    setPlan({storage_id: storage, idempotency_key: randomUUID(), expected_name: before.name,
      expected_review_digest: before.review_digest, confirmation, backup_acknowledged: true})
  }
  const change = setter => event => {setter(event.target.value); setListing(null); resetReview()}
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">VM {vmid} 백업</h1><p className="mt-2 text-sm text-slate-600">선택 NFS storage의 백업을 확인하고 정지 VM의 새 백업을 만듭니다. 실제 복원·부팅 검사는 별도 단계입니다.</p></header>
    <Link className="text-sm font-semibold underline" to={`/instances/${vmid}`}>현재 VM 상태·전원 관리</Link>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">백업 연결 권한 확인</Link></p>}
    <form onSubmit={list} className="grid gap-4 sm:grid-cols-2">
      <fieldset disabled={locked || Boolean(review)} className="contents">
        <label className="text-sm">노드 이름<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={node} onChange={change(setNode)} /></label>
        <label className="text-sm">NFS backup storage ID<input required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" className={input} value={storage} onChange={change(setStorage)} /></label>
      </fieldset>
      <button className={`${button} justify-self-start`} disabled={locked || !Number.isInteger(vmid) || vmid < 100}>{listingBusy ? '백업 읽는 중…' : '백업 목록 조회'}</button>
    </form>
    {listing && (!submitted || result?.verified) && <div className="space-y-3">
      <p className="text-sm">{node} / VM {vmid} / {storage} · 조회 당시 가용 {gib(listing.available_bytes)}</p>
      <p className="text-sm text-slate-600">{listing.limitation}</p>
      {listing.archives.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>백업 시점</th><th>파일·형식</th><th>압축 파일 크기</th><th>복원 검사</th></tr></thead><tbody>{listing.archives.map(archive => <tr key={archive.volume_id} className="border-t align-top"><td className="py-3 pr-3 whitespace-nowrap">{new Date(archive.created_at * 1000).toLocaleString()}</td><td className="break-all py-3 pr-3">{archive.volume_id}<p className="text-xs text-slate-500">{archive.format}</p></td><td className="whitespace-nowrap py-3">{gib(archive.size_bytes)}</td><td className="py-3 pl-3">{canOperate ? <Link className="whitespace-nowrap font-semibold underline" to={`/instances/${vmid}/restore?${new URLSearchParams({node, archive: archive.volume_id})}`}>별도 VM으로 복원</Link> : 'operator 권한 필요'}</td></tr>)}</tbody></table></div> : <p className="rounded-lg bg-slate-50 p-3 text-sm">이 VM의 백업이 없습니다.</p>}
      {canOperate && !review && !submitted && <button className={button} type="button" disabled={locked} onClick={load}>새 백업 조건·영향 확인</button>}
      {!canOperate && <p className="text-sm text-slate-600">새 백업 생성에는 operator 이상 권한이 필요합니다.</p>}
    </div>}
    {review && !submitted && <form onSubmit={prepare} className="space-y-3 border-t pt-4">
      <h2 className="font-semibold">{review.observed_before.name} → {storage} 새 백업</h2>
      <p className="text-sm">검토 당시 가용 {gib(review.observed_before.available_bytes)} · 보수적 필요 공간 {gib(review.observed_before.required_free_bytes)} · 기존 백업 {review.observed_before.archives.length}개 보존</p>
      {review.warnings.map(warning => <p className="text-sm text-amber-900" key={warning}>{warning}</p>)}
      <fieldset disabled={locked} className="space-y-3">
        <label className="block text-sm">대상 확인: {vmid}/{review.observed_before.name}<input required autoComplete="off" className={input} value={confirmation} onChange={event => { setConfirmation(event.target.value); setPlan(null) }} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => { setAck(event.target.checked); setPlan(null) }} />백업의 공간·IO 영향과 외부 동시 변경 중지를 확인했습니다.</label>
        <button className={button}>백업 내용 검토</button>
      </fieldset>
    </form>}
    {plan && !submitted && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-semibold">{plan.confirmation} → {plan.storage_id} · 새 zstd 백업 1개</p>
      <p className="text-sm">기존 백업은 보존하고 PVE task와 새 archive·원본 상태를 확인합니다.</p>
      <button type="button" disabled={locked} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={execute}>확인한 백업 생성</button>
    </div>}
    {submitted && <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
      <p>{busy ? '백업 task·archive 확인 중…' : result?.verified ? '새 백업과 원본·기존 백업 보존을 확인했습니다.' : '백업 결과가 미확정입니다. 작업에서 상태를 확인하고 자동 재백업하지 마세요.'}</p>
      {result?.verified && <><p className="break-all">{result.observed_after.created_archive.volume_id} · {gib(result.observed_after.created_archive.size_bytes)}</p><p>백업 파일 확인 완료 · 복원·부팅 검사 미실행</p></>}
      <p className="break-all text-xs">요청 ID: {plan?.idempotency_key}</p>
      <Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${vmid}`}>작업 결과·복구 확인</Link>
    </div>}
  </section>
}
