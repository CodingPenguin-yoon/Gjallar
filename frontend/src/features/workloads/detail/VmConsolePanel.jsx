import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiV1Client, API_V1_ENDPOINTS } from '../../../shared/api/apiV1'

const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50'

export default function VmConsolePanel({ vm }) {
  const [review, setReview] = useState(null)
  const [phase, setPhase] = useState('idle')
  const [error, setError] = useState('')
  const display = useRef(null)
  const connection = useRef(null)
  const generation = useRef(0)

  function release() {
    generation.current += 1
    const current = connection.current
    connection.current = null
    if (current) {
      clearTimeout(current.timer)
      current.rfb?.disconnect()
      current.socket?.close()
    }
  }
  useEffect(() => () => release(), [])

  async function prepare() {
    if (phase === 'preparing' || phase === 'connecting' || phase === 'connected') return
    release()
    const current = generation.current
    setPhase('preparing'); setError(''); setReview(null)
    try {
      const data = await apiV1Client.getVmConsole(vm.nodeId, vm.vmid)
      if (generation.current !== current) return
      if (data.target.node_id !== vm.nodeId || Number(data.target.vmid) !== Number(vm.vmid)) throw new Error('조회한 콘솔 대상이 선택한 VM과 다릅니다.')
      setReview(data); setPhase('ready')
    } catch (failure) {
      if (generation.current === current) {setError(failure.message); setPhase('closed')}
    }
  }

  async function connectConsole() {
    if (connection.current || phase !== 'ready') return
    const current = ++generation.current
    const handle = {}; connection.current = handle
    setPhase('connecting'); setError('')
    function failed(message) {
      if (generation.current !== current) return
      release(); setPhase('closed'); setError(message)
    }
    try {
      // Load before requesting the short-lived PVE proxy, so its connection window isn't consumed by the download.
      const {default: RFB} = await import('@novnc/novnc')
      if (generation.current !== current) return
      const url = new URL(API_V1_ENDPOINTS.vmConsoleSocket(vm.nodeId, vm.vmid), window.location.origin)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(url); handle.socket = socket
      handle.timer = setTimeout(() => failed('콘솔 연결 시간이 초과됐습니다. 자동 재접속하지 않았습니다.'), 20000)
      socket.onerror = () => failed('콘솔 연결을 열지 못했습니다. 로그인·선택 권한과 서버 연결을 확인하세요.')
      socket.onclose = event => failed(event.code === 4408 ? '콘솔 접속 시간이 만료됐습니다. 다시 준비한 뒤 연결하세요.' : '콘솔이 종료됐습니다. 로그인·선택 권한과 서버 연결을 확인한 뒤 다시 준비하세요.')
      socket.onmessage = event => {
        if (generation.current !== current) return
        let message
        try { message = JSON.parse(event.data) } catch { failed('콘솔 초기 응답을 확인할 수 없습니다.'); return }
        if (message.type !== 'ready' || typeof message.password !== 'string' || !message.password) {
          failed('콘솔 초기 응답을 확인할 수 없습니다.'); return
        }
        // Credentials remain inside this connection; never persist them or add them to a URL.
        let rfb
        try { rfb = new RFB(display.current, socket, {shared: true, credentials: {password: message.password}}) }
        catch { failed('콘솔 화면 초기화에 실패했습니다.'); return }
        handle.rfb = rfb
        rfb.scaleViewport = true
        rfb.resizeSession = false
        rfb.addEventListener('connect', () => {
          if (generation.current === current) {clearTimeout(handle.timer); setPhase('connected')}
        })
        rfb.addEventListener('disconnect', () => failed('콘솔 연결이 종료됐습니다. 자동 재접속하지 않았습니다. 필요하면 다시 준비하세요.'))
        rfb.addEventListener('securityfailure', () => failed('PVE 콘솔 인증에 실패했습니다. 권한과 연결 상태를 확인하세요.'))
        rfb.addEventListener('credentialsrequired', () => failed('지원하지 않는 추가 콘솔 인증이 필요합니다.'))
        rfb.addEventListener('serververification', () => failed('지원하지 않는 추가 콘솔 인증 방식입니다.'))
      }
    } catch {
      failed('콘솔 화면을 준비하지 못했습니다. 연결 상태를 확인한 뒤 다시 준비하세요.')
    }
  }

  const active = phase === 'connecting' || phase === 'connected'
  return <div id="console" className="mt-4 space-y-3 border-t border-slate-200 pt-4">
    <h4 className="font-semibold">웹 콘솔</h4>
    <p className="text-sm text-slate-600">실행 중인 VM의 화면과 키보드·마우스에 접근합니다. 입력은 게스트 상태를 바꿀 수 있습니다. 연결 종료는 VM을 끄지 않습니다.</p>
    {!active && <button type="button" className={button} disabled={phase === 'preparing' || vm.status !== 'running'} onClick={prepare}>콘솔 접속 준비</button>}
    {vm.status !== 'running' && <p className="text-sm text-slate-600">실행 중인 VM만 연결할 수 있습니다. 자동 시작하지 않습니다.</p>}
    {review && phase === 'ready' && <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
      <p>{review.target.node_id} / VM {review.target.vmid} · {review.name}</p>
      {review.warnings.map(warning => <p key={warning}>{warning}</p>)}
      <button type="button" className={button} onClick={connectConsole}>확인한 VM 콘솔 연결</button>
    </div>}
    {active && <div className="flex flex-wrap items-center gap-3 text-sm"><span role="status">{phase === 'connected' ? '콘솔 연결됨 · 최대 15분' : '콘솔 인증·화면 연결 중…'}</span>
      <button type="button" className={button} onClick={() => {release(); setPhase('closed'); setError('')}}>콘솔 연결 종료</button></div>}
    {phase === 'closed' && !error && <p role="status" className="text-sm">콘솔 연결을 종료했습니다.</p>}
    {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error} <Link to="/settings/proxmox" className="underline">연결 권한 확인</Link></p>}
    <div ref={display} aria-label="VM 콘솔 화면" className={active ? 'h-[480px] overflow-hidden rounded-lg bg-slate-950' : 'hidden'} />
  </div>
}
