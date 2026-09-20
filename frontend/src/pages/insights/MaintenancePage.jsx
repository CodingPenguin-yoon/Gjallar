import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'

const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2'
const status = {ready: '이동 조건 확인', recent_archive: '최근 백업 파일 확인', old_archive: '오래된 백업', missing: '백업 없음',
  unavailable: '확인 불가', blocked: '준비 필요', unsupported: '별도 확인 필요', not_checked: '미검사'}
const stamp = value => value ? new Date(value).toLocaleString() : '관찰 없음'

export default function MaintenancePage({ canOperate }) {
  const [node, setNode] = useState('')
  const [destination, setDestination] = useState('')
  const [storage, setStorage] = useState('')
  const [hours, setHours] = useState('24')
  const [limit, setLimit] = useState('10')
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const pending = useRef(false)
  useEffect(() => () => {generation.current += 1}, [])
  const change = setter => event => {setter(event.target.value); setReport(null); setError('')}
  async function load(event) {
    event.preventDefault()
    if (pending.current) return
    if (node === destination) {setError('서로 다른 원본·목적 노드를 선택하세요.'); return}
    pending.current = true; setBusy(true); setReport(null); setError('')
    const current = ++generation.current
    try {
      const data = await apiV1Client.getNodeMaintenance(node, {backup_max_age_hours: Number(hours), check_limit: Number(limit),
        ...(destination ? {destination_node: destination} : {}), ...(storage ? {backup_storage: storage} : {})})
      if (current !== generation.current) return
      if (data.node_id !== node || data.destination_node !== (destination || null) || data.backup_storage !== (storage || null)
        || data.backup_max_age_hours !== Number(hours) || data.check_limit !== Number(limit) || data.read_only !== true || data.node_shutdown_safe !== false) throw new Error('조회된 보고서의 대상·범위가 선택과 다릅니다.')
      setReport(data)
    } catch (failure) {
      if (current === generation.current) setError(failure.message)
    } finally {
      if (current === generation.current) {pending.current = false; setBusy(false)}
    }
  }
  return <section className="gj-workflow space-y-3">
    <header><h1 className="text-xl font-bold">노드 유지보수 준비</h1><p className="mt-2 text-sm text-slate-600">영향 VM·자원을 읽고 대상별 백업·정지 이동 조건을 확인합니다. 이 화면에서 VM이나 노드를 변경하지 않습니다.</p></header>
    {!canOperate ? <p>백업·이동 준비 검토에는 operator 이상 권한이 필요합니다.</p> : <form onSubmit={load}>
      <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">유지보수할 노드<input className={input} required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={node} onChange={change(setNode)} /></label>
        <label className="text-sm">이동 목적 노드 (선택)<input className={input} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={destination} onChange={change(setDestination)} /></label>
        <label className="text-sm">NFS 백업 storage (선택)<input className={input} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={storage} onChange={change(setStorage)} /></label>
        <label className="text-sm">최근 백업 기준 (시간)<input className={input} required type="number" min="1" max="720" value={hours} onChange={change(setHours)} /></label>
        <label className="text-sm">추가 검사 VM 한도<input className={input} required type="number" min="1" max="20" value={limit} onChange={change(setLimit)} /></label>
        <button className="self-end rounded-lg bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50">{busy ? '준비 상태 조회 중…' : '영향·준비 상태 조회'}</button>
      </fieldset>
    </form>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">연결 권한 확인</Link></p>}
    {report && <div className="space-y-3">
      <div role="status" className="space-y-2 rounded-lg bg-slate-50 p-4 text-sm">
        <h2 className="font-semibold">{report.node_id} · {report.checks_complete ? '조회 범위의 수동 이동 준비 확인' : report.status === 'no_visible_targets' ? '현재 연결에 보이는 대상 없음' : report.status === 'unavailable' ? '관찰 불충분' : '준비·확인이 필요한 대상 있음'}</h2>
        <p>노드 종료 안전성은 확인하지 않았습니다. 원본 노드의 VM 이동·정상 종료는 별도 실행해야 합니다.</p>
        <p>관찰: {stamp(report.observed_at)} · 조회: {stamp(report.received_at)}</p>
        <p>관찰 대상 {report.total_observed_targets}개 · 수동 이동 준비 확인 {report.prepared_target_count || 0}개 · 추가 검사 {report.checked_target_count || 0}개</p>
        {report.truncated && <p className="font-semibold text-amber-900">영향 목록은 200개까지만 표시합니다. 나머지 대상도 별도로 확인하세요.</p>}
        {report.limitations.map(value => <p key={value} className="text-slate-600">{value}</p>)}
      </div>
      {report.resources.status && <div className="space-y-2 text-sm">
        <h2 className="font-semibold">관찰한 노드 자원</h2>
        <p>{report.resources.status} · CPU {report.resources.cpu_total} · 메모리 {report.resources.memory_total_mb} MiB</p>
        <p>storage: {report.resources.storages.map(row => `${row.storage_id} (${row.type}, 가용 ${row.free_gb} GiB)`).join(' / ') || '관찰 없음'}</p>
        <p>bridge: {report.resources.bridges.map(row => `${row.bridge_id} (${row.active ? '활성' : '비활성'})`).join(' / ') || '관찰 없음'}</p>
        <details><summary className="cursor-pointer">관찰 누락 확인</summary><ul>{Object.entries(report.availability?.sources || {}).map(([key, value]) => <li key={key}>{key}: {value.complete ? '조회 범위 관찰 완료' : '누락 있음'}</li>)}</ul></details>
      </div>}
      <div className="space-y-4">{report.targets.map((vm, index) => <article key={`${vm.vmid}:${index}`} className="space-y-3 rounded-lg border border-slate-200 p-4">
        <h3 className="font-semibold">{vm.vmid} / {vm.name} · {vm.power_state} · {vm.preparation === 'ready_for_manual_migration' ? '수동 이동 준비 확인' : '미완료'}</h3>
        <p className="text-sm">관찰 당시 {vm.node_id}에 있음 · storage {vm.storage_ids.join(', ') || '미확인'} · bridge {vm.bridges.join(', ') || '미확인'}</p>
        {['migration','backup'].map(key => <div key={key} className="text-sm"><p className="font-semibold">{key === 'migration' ? '이동' : '백업'}: {status[vm[key].status] || '확인 불가'}</p><p>{vm[key].message}</p>
          {vm[key].latest_archive && <p className="break-all text-slate-600">{vm[key].latest_archive.volume_id} · {stamp(vm[key].latest_archive.created_at * 1000)} · {vm[key].age_hours}시간 전 · 복원 미검증</p>}
        </div>)}
        <div className="flex flex-wrap gap-4 text-sm font-semibold underline"><Link to={`/instances/${vm.vmid}`}>VM 상세·전원</Link>
          {!vm.template && <><Link to={`/instances/${vm.vmid}/backups?${new URLSearchParams({node: report.node_id, storage: report.backup_storage || ''})}`}>백업 확인·생성</Link><Link to={`/instances/${vm.vmid}/migrate?${new URLSearchParams({node: report.node_id, ...(report.destination_node ? {destination_node: report.destination_node} : {})})}`}>정지 VM 이동 검토</Link></>}
        </div>
      </article>)}</div>
    </div>}
  </section>
}
