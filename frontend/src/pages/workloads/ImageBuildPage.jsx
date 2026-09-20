import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client } from '../../shared/api/apiV1'
import { assertChangeResult } from '../../features/workloads/detail/changeResult'

const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50'
const input = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 disabled:bg-slate-100'
const fields = [ ['node_id', '노드 이름'], ['vmid', '새 템플릿 VMID'], ['name', '템플릿 이름'],
  ['staging_storage_id', '이미지 업로드 storage (import)'], ['storage_id', '템플릿 disk storage (NFS images)'], ['bridge_id', 'Linux bridge'] ]
const stageLabels = { download: '이미지 무결성 확인', upload: '이미지 업로드', create: 'VM 구성', template: '템플릿 전환' }

export default function ImageBuildPage({ canOperate }) {
  return canOperate ? <ImageBuildForm /> : <p className="rounded-xl border bg-white p-6">템플릿 제작은 operator 이상 권한이 필요합니다.</p>
}

function ImageBuildForm() {
  const [images, setImages] = useState([])
  const [review, setReview] = useState(null)
  const [plan, setPlan] = useState(null)
  const [result, setResult] = useState(null)
  const [confirmation, setConfirmation] = useState('')
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const generation = useRef(0)
  useEffect(() => {
    let cancelled = false
    apiV1Client.listCloudImages().then(data => { if (!cancelled) setImages(data.images) })
      .catch(failure => { if (!cancelled) setError(failure.message) })
    return () => { cancelled = true; generation.current += 1 }
  }, [])

  async function prepare(event) {
    event.preventDefault()
    if (inFlight.current || submitted) return
    const values = Object.fromEntries(new FormData(event.currentTarget))
    const {node_id: nodeId, vmid: rawVmid, ...configuration} = values
    const vmid = Number(rawVmid)
    if (!Number.isInteger(vmid) || vmid < 100 || vmid > 999999999) { setError('VMID는 100~999999999 정수로 입력하세요.'); return }
    inFlight.current = true
    const current = ++generation.current
    setBusy(true); setError('')
    try {
      const data = await apiV1Client.reviewImageBuild(nodeId, vmid, configuration)
      if (current !== generation.current) return
      if (data.target.node_id !== nodeId || data.target.vmid !== vmid || data.target.name !== configuration.name) throw new Error('조회한 제작 대상이 입력과 다릅니다.')
      setReview(data)
      setPlan({...configuration, idempotency_key: crypto.randomUUID(), expected_review_digest: data.review_digest})
      setConfirmation(''); setAck(false)
    } catch (failure) {
      if (current === generation.current) setError(failure.message)
    } finally {
      if (current === generation.current) { inFlight.current = false; setBusy(false) }
    }
  }

  async function execute(event) {
    event.preventDefault()
    if (inFlight.current || submitted || !review) return
    const target = review.target
    if (confirmation !== `${target.vmid}/${target.name}` || !ack) { setError('새 VMID/이름과 제작 영향을 확인하세요.'); return }
    inFlight.current = true
    const current = ++generation.current
    setSubmitted(true); setBusy(true); setError('')
    try {
      const requested = {...plan, confirmation, image_build_acknowledged: true}
      const response = await apiV1Client.buildImageTemplate(target.node_id, target.vmid, requested)
      if (current !== generation.current) return
      setResult({...response, verified: false})
      const observed = await apiV1Client.getOperation(response.operation_id)
      if (current !== generation.current) return
      const operation = assertChangeResult(observed, response.operation_id, {
        type: 'vm_image_build', node: target.node_id, vmid: target.vmid, requested,
      })
      setResult({...response, ...operation.details, status: operation.status,
        verified: operation.status === 'succeeded' && !operation.coordination_incomplete && !observed.coordination_incomplete})
    } catch (failure) {
      if (current === generation.current) setError(`${failure.message} 요청 ID를 보존하고 작업 이력을 확인하세요. 자동 재전송하지 않았습니다.`)
    } finally {
      if (current === generation.current) { inFlight.current = false; setBusy(false) }
    }
  }

  return <section className="gj-workflow space-y-3">
    <div className="text-right text-sm"><Link className="underline" to="/instances/templates/cleanup">제작한 자원 정리</Link></div>
    <header><h1 className="text-xl font-bold text-slate-900">공식 이미지로 템플릿 제작</h1>
      <p className="mt-2 text-sm text-slate-600">공식 이미지를 확인하고 새 VMID에 템플릿을 만듭니다. 완성 후 별도 테스트 배포로 부팅·cloud-init·guest agent를 확인하세요.</p></header>
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">연결 권한 확인</Link></p>}
    {!submitted && <form onSubmit={prepare} className="grid gap-4 sm:grid-cols-2">
      <fieldset disabled={busy || Boolean(review)} className="contents">
        <label className="text-sm sm:col-span-2">공식 이미지<select required name="image_id" className={input} defaultValue=""><option value="" disabled>지원 이미지 선택</option>{images.map(image => <option key={image.image_id} value={image.image_id}>{image.label}</option>)}</select></label>
        {fields.map(([key, label]) => <label key={key} className="text-sm">{label}<input required name={key} className={input} type={key === 'vmid' ? 'number' : 'text'} min={key === 'vmid' ? 100 : undefined} max={key === 'vmid' ? 999999999 : undefined} autoComplete="off" /></label>)}
      </fieldset>
      {!review && <><p className="text-sm text-slate-600 sm:col-span-2">관리형 연결에 제작할 새 VMID·storage·bridge와 image_build 권한이 필요합니다. staging storage는 import content를 미리 지원해야 합니다. 기존 VMID를 덮어쓰지 않습니다.</p><button className={button} disabled={busy || !images.length}>{busy ? '제작 조건 확인 중…' : '제작 조건과 영향 확인'}</button></>}
    </form>}
    {review && !submitted && <form onSubmit={execute} className="space-y-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <h2 className="font-semibold">{review.target.node_id} · {review.target.vmid}/{review.target.name}</h2>
      <p className="text-sm">CPU 2 cores · 메모리 2048 MiB · disk 10 GiB · DHCP cloud-init · guest agent 설정 · 전원 꺼짐</p>
      <details className="break-all text-sm"><summary className="cursor-pointer font-medium">이미지 출처·무결성 정보</summary><dl className="mt-2 space-y-2"><dt>공식 이미지</dt><dd>{review.observed_before.image.url}</dd><dt>SHA-256</dt><dd>{review.observed_before.image.sha256}</dd><dt>배포 파일 크기</dt><dd>{review.observed_before.image.download_bytes.toLocaleString()} bytes</dd></dl></details>
      <ul className="list-disc space-y-2 pl-5 text-sm text-amber-950">{review.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
      <label className="block text-sm">대상 확인: {review.target.vmid}/{review.target.name}<input required autoComplete="off" className={input} value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)} />업로드·공간 소모·새 VM 생성과 전환, 부분 실패 시 자원 보존, 외부 동시 변경 중지 조건을 확인했습니다.</label>
      <div className="flex flex-wrap gap-3"><button disabled={busy} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">확인한 내용으로 템플릿 제작</button><button type="button" className={button} onClick={() => { setReview(null); setPlan(null); setError('') }}>입력 수정·다시 검토</button></div>
    </form>}
    {submitted && <div role="status" className="space-y-3 rounded-lg bg-slate-50 p-4">
      <h2 className="font-semibold">{busy ? '이미지 확인·업로드·템플릿 제작 중…' : result?.verified ? '실제 템플릿과 base volume을 확인했습니다.' : '제작 결과 확인이 필요합니다.'}</h2>
      <p className="text-sm">{review.target.node_id} · {review.target.vmid}/{review.target.name}</p>
      {!result?.verified && <p className="text-sm">수 분이 걸릴 수 있습니다. 화면을 닫거나 연결이 끊겨도 새 요청으로 제작을 반복하지 마세요. 부분 자원과 작업 기록을 먼저 확인하세요.</p>}
      {result?.build_stage && <p className="text-sm">마지막 기록 단계: {stageLabels[result.build_stage] || result.build_stage} · {result.status}</p>}
      {result?.observed_after?.volumes?.map(volume => <p key={volume.volume_id} className="break-all text-sm">{volume.slot} · {volume.volume_id} · {(volume.size_bytes / 1024 ** 2).toLocaleString()} MiB</p>)}
      {result?.staging && <p className="break-all text-sm">보존된 업로드 원본: {result.staging.volume_id}</p>}
      {result?.verified && <p className="text-sm text-amber-900">게스트 배포는 아직 검증하지 않았습니다. 제작된 템플릿을 생성 원본 범위로 등록·검증·전환하고 별도 테스트 배포를 진행하세요.</p>}
      <p className="break-all text-xs text-slate-500">요청 ID: {plan.idempotency_key}</p>
      <div className="flex flex-wrap gap-4 text-sm"><Link className="font-semibold underline" to={result?.operation_id ? `/operations/${encodeURIComponent(result.operation_id)}` : `/operations?target_type=proxmox_vm&target_id=vmid%3A${review.target.vmid}`}>작업 결과·복구 확인</Link>
        {result?.verified && <><Link className="underline" to="/settings/proxmox">원본 템플릿 권한 등록</Link><Link className="underline" to={`/instances/create?${new URLSearchParams({template_node: review.target.node_id, template_vmid: review.target.vmid})}`}>테스트 VM 생성</Link><Link className="underline" to={`/instances/templates/cleanup?${new URLSearchParams({node: review.target.node_id, vmid: review.target.vmid, build: result.operation_id})}`}>소유 자원 정리</Link></>}</div>
    </div>}
  </section>
}
