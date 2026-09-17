import { useEffect, useRef, useState } from 'react'
import { apiV1Client } from '../../shared/api/apiV1'

const labels = {
  prepared: '로그인 대기', authenticated: '로그인 완료', mfa_required: 'TOTP 입력 필요', planned: '권한 계획 확인',
  token_dispatching: '토큰 발급 결과 확인 필요', secret_staged: '토큰 저장 완료 · 권한 설정 확인 필요',
  acl_applying: '권한 설정 결과 확인 필요', verifying: '자원 조회 검증', verified: '검증 완료 · 연결 전환 대기',
  active: '연결 저장 완료', cancelled: '취소됨', revocation_pending: '토큰 폐기 결과 확인 필요', revoked: '토큰 폐기 확인',
  import_staging: '기존 토큰 저장 재개 필요',
}
const inputClass = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm'
const buttonClass = 'rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50'
const split = (value) => String(value || '').split(',').map((item) => item.trim()).filter(Boolean)

export default function ProxmoxSetupPage() {
  const [attempt, setAttempt] = useState(null)
  const [recent, setRecent] = useState([])
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [observation, setObservation] = useState(null)
  const requestIdentity = useRef(crypto.randomUUID())
  const pendingPrepare = useRef(null)
  const generation = useRef(0)

  useEffect(() => {
    let alive = true
    apiV1Client.listProxmoxRegistrations().then((rows) => { if (alive) setRecent(rows) })
      .catch(() => { if (alive) setError('등록 이력을 조회하지 못했습니다. 서버 연결과 DB 준비 상태를 확인하세요.') })
    return () => { alive = false; generation.current += 1 }
  }, [])

  async function perform(fn) {
    if (busy) return
    const current = ++generation.current
    setBusy(true)
    setError('')
    try {
      const result = await fn()
      if (current !== generation.current) return
      setAttempt(result)
      if (result.plan) setPlan(result.plan)
      if ('token_exists' in result) setObservation(result)
      setRecent((rows) => [result, ...rows.filter((row) => row.attempt_id !== result.attempt_id)])
    } catch (failure) {
      if (current === generation.current) setError(failure.message || '요청 결과를 확인하지 못했습니다. 상태를 다시 조회하세요.')
    } finally {
      if (current === generation.current) setBusy(false)
    }
  }

  const act = (action, payload = {}) => perform(() => apiV1Client.actProxmoxRegistration(attempt.attempt_id, action, {
    expected_version: attempt.version, ...payload,
  }))

  async function prepare(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const ids = split(form.get('vmids')).map(Number)
    if (ids.some((id) => !Number.isInteger(id))) { setError('VM ID는 숫자로 입력하세요.'); return }
    const ca = form.get('ca')
    if (ca?.size > 65536) { setError('CA 인증서 파일은 64KB 이하여야 합니다.'); return }
    const caPem = ca?.size ? await ca.text() : ''
    setPlan(null)
    setObservation(null)
    const intent = {
      endpoint: form.get('endpoint'), owner: form.get('owner'), ca_pem: caPem,
      mode: form.get('mode'),
      scope: { nodes: split(form.get('nodes')), vmids: ids, storages: split(form.get('storages')), bridges: split(form.get('bridges')) },
      features: form.get('power') ? ['read', 'power'] : ['read'],
    }
    const signature = JSON.stringify(intent)
    if (!pendingPrepare.current || pendingPrepare.current.signature !== signature) {
      if (pendingPrepare.current) requestIdentity.current = crypto.randomUUID()
      pendingPrepare.current = { signature, body: {
        idempotency_key: requestIdentity.current,
        intent: { ...intent, expires_at: Math.floor(Date.now() / 1000) + 30 * 86400 },
      } }
    }
    await perform(() => apiV1Client.prepareProxmoxRegistration(pendingPrepare.current.body))
  }

  async function authenticate(event) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const payload = needsMfa
      ? { otp: data.get('otp') }
      : { password: data.get('password'), ...(data.get('otp') ? { otp: data.get('otp') } : {}) }
    form.reset()
    setPlan(null)
    await act(needsMfa ? 'mfa' : 'login', payload)
  }

  const initial = !attempt
  const canPlan = attempt && (['authenticated', 'planned'].includes(attempt.phase) || (attempt.mode === 'import_env' && attempt.phase === 'prepared'))
  const canVerify = attempt && ['secret_staged', 'verifying', 'acl_applying', 'acl_unknown', 'verified'].includes(attempt.phase)
  const canCancel = attempt && ['prepared', 'authenticated', 'mfa_required', 'planned'].includes(attempt.phase)
  const needsCleanup = attempt && attempt.mode !== 'import_env' && ['token_dispatching', 'secret_staged', 'acl_applying', 'verified', 'active', 'revocation_pending'].includes(attempt.phase)
  const needsMfa = attempt && (attempt.phase === 'mfa_required' || attempt.mfa_required) && !attempt.reauth_required

  return <div className="space-y-6 rounded-xl border border-slate-200 bg-white p-6">
    <div><h1 className="text-xl font-semibold">Proxmox 연결</h1>
      <p className="mt-2 text-sm text-slate-600">Proxmox 계정으로 로그인한 뒤 조회할 자원과 필요한 권한을 확인합니다. 비밀번호는 저장하지 않습니다.</p>
      <p className="mt-1 text-sm text-slate-600">검증 대상: Proxmox 9.0.11 · pam/pve 계정 · TOTP. 토큰 유효기간은 30일입니다.</p></div>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {attempt && ['active', 'cancelled', 'revoked'].includes(attempt.phase) && <button disabled={busy} className={buttonClass}
      onClick={() => { setAttempt(null); setPlan(null); setObservation(null); pendingPrepare.current = null; requestIdentity.current = crypto.randomUUID() }}>새 연결 등록</button>}
    {recent.length > 0 && <label className="block text-sm">기존 등록 확인
      <select className={`${inputClass} mt-1`} disabled={busy} value={attempt?.attempt_id || ''}
        onChange={(event) => { const id = event.target.value; if (id) { setPlan(null); setObservation(null); perform(() => apiV1Client.getProxmoxRegistration(id)) } }}>
        <option value="">등록 선택</option>{recent.map((row) => <option key={row.attempt_id} value={row.attempt_id}>{labels[row.phase] || row.phase} · {row.attempt_id}</option>)}
      </select></label>}
    {initial && <form onSubmit={prepare} className="grid gap-4 sm:grid-cols-2">
      <label className="text-sm sm:col-span-2">연결 방식<select name="mode" className={inputClass}><option value="issue">Proxmox 로그인으로 전용 토큰 발급</option><option value="import_env">서버의 기존 환경변수 연결 가져오기 (토큰·권한 변경 없음)</option></select></label>
      <label className="text-sm">Proxmox HTTPS 주소<input name="endpoint" required placeholder="https://pve.example.com:8006" className={inputClass} /></label>
      <label className="text-sm">Proxmox 계정<input name="owner" required autoComplete="off" placeholder="user@pam" className={inputClass} /></label>
      <label className="text-sm sm:col-span-2">공개 CA 인증서 (system CA 사용 시 생략)<input name="ca" type="file" accept=".pem,.crt" className={`${inputClass} mt-1`} /></label>
      <label className="text-sm">노드 이름 (쉼표 구분)<input name="nodes" required placeholder="pve1, pve2" className={inputClass} /></label>
      <label className="text-sm">VM·템플릿 ID (쉼표 구분)<input name="vmids" placeholder="100, 101, 9000" className={inputClass} /></label>
      <label className="text-sm">스토리지 ID (선택)<input name="storages" placeholder="local-lvm" className={inputClass} /></label>
      <label className="text-sm">브리지 이름 (선택)<input name="bridges" placeholder="vmbr0" className={inputClass} /></label>
      <label className="flex items-center gap-2 text-sm sm:col-span-2"><input name="power" type="checkbox" />선택한 VM의 시작·정상 종료 권한 포함</label>
      <button disabled={busy} className={buttonClass}>연결 등록 시작</button>
    </form>}
    {attempt && <div className="space-y-4 border-t border-slate-200 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{labels[attempt.phase] || attempt.phase}</h2>
        <p className="mt-1 break-all text-xs text-slate-500">등록 ID: {attempt.attempt_id}</p></div>
        <button className={buttonClass} disabled={busy} onClick={() => perform(() => apiV1Client.getProxmoxRegistration(attempt.attempt_id))}>상태 다시 조회</button></div>
      {attempt.mode !== 'import_env' && !['cancelled', 'revoked'].includes(attempt.phase) && <form onSubmit={authenticate} className="flex flex-wrap items-end gap-3">
        {!needsMfa && <label className="text-sm">Proxmox 비밀번호<input type="password" name="password" required autoComplete="off" className={inputClass} /></label>}
        <label className="text-sm">{needsMfa ? 'TOTP' : 'realm OTP (사용 시)'}<input type="password" name="otp" required={needsMfa} inputMode="numeric" autoComplete="off" className={inputClass} /></label>
        <button disabled={busy} className={buttonClass}>{needsMfa ? 'TOTP 확인' : '로그인·재인증'}</button>
      </form>}
      {canPlan && <button disabled={busy} className={buttonClass} onClick={() => act(attempt.mode === 'import_env' ? 'import-plan' : 'plan')}>필요 권한과 변경 내용 확인</button>}
      {plan && attempt.phase === 'planned' && <div className="space-y-3 rounded-lg bg-slate-50 p-4">
        <p className="break-all text-sm">연결 대상: {plan.endpoint}</p>
        <p className="break-all text-sm">{attempt.mode === 'import_env' ? '가져올 기존 토큰' : '발급할 토큰'}: {plan.token_id}</p>
        <p className="text-sm">노드: {plan.scope.nodes.join(', ')} · VM/템플릿: {plan.scope.vmids.join(', ') || '선택 없음'} · 스토리지: {plan.scope.storages.join(', ') || '선택 없음'} · 브리지: {plan.scope.bridges.join(', ') || '선택 없음'}</p>
        <p className="text-sm">사용 기능: {plan.features.includes('power') ? '조회·시작·정상 종료' : '조회'}</p>
        <p className="text-sm">{plan.expires_at ? `만료: ${new Date(plan.expires_at * 1000).toLocaleString()} · 선택한 범위에만 권한을 부여합니다.` : 'Proxmox의 기존 토큰·권한·만료일은 변경하지 않습니다. Gjallar는 선택한 자원만 사용합니다.'}</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">대상</th><th className="p-2">부여할 권한</th></tr></thead>
          <tbody>{plan.acls.map((acl) => <tr key={acl.path}><td className="p-2">{acl.path}</td><td className="p-2">{plan.roles[acl.role].join(', ')}</td></tr>)}</tbody></table></div>
        {plan.create_roles.length > 0 && <p className="text-sm">새 권한 역할: {plan.create_roles.join(', ')}</p>}
        {!plan.can_confirm && <p role="alert" className="text-sm text-red-800">권한 부족: {plan.missing_privileges.map((row) => `${row.path}: ${row.privileges.join(', ')}`).join(' / ')}</p>}
        <button disabled={busy || !plan.can_confirm} className={buttonClass} onClick={() => act(attempt.mode === 'import_env' ? 'import-env' : 'confirm', { plan_digest: plan.digest })}>{attempt.mode === 'import_env' ? '기존 토큰 가져오기·조회 검증' : '위 내용으로 토큰 발급·권한 설정'}</button>
      </div>}
      {canVerify && <button disabled={busy} className={buttonClass} onClick={() => act('verify')}>토큰 권한·자원 조회 다시 검증</button>}
      {attempt.mode === 'import_env' && attempt.phase === 'import_staging' && <button disabled={busy} className={buttonClass}
        onClick={() => act('import-env', { plan_digest: attempt.plan_digest })}>기존 토큰 암호화 저장·검증 재개</button>}
      {attempt.phase === 'verified' && <div className="space-y-2"><p className="text-sm">전환은 미완결 VM 작업이 없을 때 가능합니다. 전환 후 모든 Gjallar 서버 프로세스를 재시작하세요.</p>
        <button disabled={busy} className={buttonClass} onClick={() => act('activate')}>검증한 연결로 전환</button></div>}
      {attempt.phase === 'active' && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">연결을 저장했습니다. 서버 재시작 후 Overview·Workloads 또는 CLI에서 실제 자원 조회를 확인하세요.</p>}
      {canCancel && <button disabled={busy} className="text-sm text-slate-600 underline" onClick={() => act('cancel')}>발급 전 등록 취소</button>}
      {needsCleanup && <div className="space-y-3 rounded-lg border border-amber-200 p-4"><p className="text-sm">발급·권한 설정 결과가 불명확하면 먼저 토큰을 확인하세요. 다시 로그인해야 할 수 있습니다.</p>
        <button disabled={busy} className={buttonClass} onClick={() => act('observe')}>등록 토큰 존재 확인</button>
        {observation && <p className="text-sm">토큰 존재: {observation.token_exists ? '확인됨' : '조회에서 발견되지 않음'} · {observation.secret_recoverable ? '서버에 암호화 저장됨' : '저장된 토큰 비밀값 없음'}</p>}
        <form onSubmit={(event) => { event.preventDefault(); const tokenId = new FormData(event.currentTarget).get('tokenId'); act('revoke', { token_id: tokenId }) }} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">폐기할 전체 토큰 ID<input name="tokenId" required autoComplete="off" placeholder="user@pve!gjallar-…" className={inputClass} /></label>
          <button disabled={busy} className="rounded-lg bg-red-700 px-4 py-2 text-sm text-white disabled:opacity-50">입력한 토큰 폐기·결과 확인</button>
        </form><p className="text-xs text-slate-500">활성 토큰을 폐기하면 자원 조회·조작이 중단됩니다. 미완결 작업이 있으면 폐기를 거부합니다.</p>
      </div>}
    </div>}
  </div>
}
