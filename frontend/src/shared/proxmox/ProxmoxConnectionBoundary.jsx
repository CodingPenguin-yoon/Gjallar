import { AlertTriangle, RefreshCw, Server } from 'lucide-react'
import { Link } from 'react-router-dom'
import { isProxmoxInventoryAvailable, isProxmoxOperational, normalizeProxmoxConnection } from './connection'

const reasonMessages = Object.freeze({
  proxmox_inventory_configuration_missing: 'Proxmox API 연결 설정이 아직 완료되지 않았습니다.',
  proxmox_inventory_mode_invalid: '지원하지 않는 inventory mode가 설정되어 있습니다.',
  proxmox_tls_failed: 'Proxmox TLS 인증을 확인하지 못했습니다.',
  proxmox_connection_timed_out: 'Proxmox 연결 시간이 초과되었습니다.',
  proxmox_connection_unreachable: 'Proxmox API에 연결할 수 없습니다.',
  proxmox_authentication_failed: 'Proxmox API 인증에 실패했습니다.',
  proxmox_api_rejected: 'Proxmox API가 inventory 요청을 거부했습니다.',
  proxmox_inventory_unavailable: 'Proxmox inventory를 불러오지 못했습니다.',
})

export default function ProxmoxConnectionBoundary({ requestStatus, connection, onRetry, canConfigure = false, requireLive = false, children }) {
  if (requestStatus === 'loading' || requestStatus === 'idle') {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm" aria-live="polite">
        <div className="flex items-center gap-3 text-slate-700">
          <RefreshCw className="h-5 w-5 animate-spin" />
          <span className="font-semibold">Proxmox 연결 상태를 확인하고 있습니다.</span>
        </div>
      </section>
    )
  }

  const boundaryReady = requireLive
    ? isProxmoxOperational(connection)
    : isProxmoxInventoryAvailable(connection)
  if (requestStatus === 'ready' && boundaryReady) return children

  const status = normalizeProxmoxConnection(connection)
  const unconfigured = status.state === 'unconfigured'
  const message = reasonMessages[status.reason]
    || (unconfigured ? 'Proxmox API 연결 설정이 필요합니다.' : 'Proxmox 연결 상태를 확인할 수 없습니다.')

  return (
    <section className={`rounded-lg border bg-white p-6 shadow-sm ${unconfigured ? 'border-yellow-200' : 'border-red-200'}`} aria-live="polite">
      <div className="flex items-start gap-3">
        {unconfigured
          ? <Server className="mt-0.5 h-5 w-5 shrink-0 text-yellow-700" />
          : <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />}
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Proxmox {status.state}</div>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">{message}</h2>
          <p className="mt-2 text-sm text-slate-600">
            {status.inventoryAvailable && requireLive
              ? '각 작업에 필요한 대상 정보와 권한은 실행 전에 확인합니다.'
              : '실제 Proxmox inventory를 확인할 수 있을 때만 Overview와 Workloads 읽기 화면을 엽니다. Insights, Operations, Jobs, Risks, Account, Admin은 계속 사용할 수 있습니다.'}
          </p>

          {unconfigured ? (
            <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              {canConfigure ? (
                <>
                  <p>Proxmox 연결을 등록하고 사용할 자원과 권한을 확인하세요.</p>
                  <Link to="/settings/proxmox" className="mt-3 inline-flex rounded-lg bg-slate-950 px-3 py-2 font-semibold text-white hover:bg-slate-800">Proxmox 연결 설정</Link>
                </>
              ) : <p>관리자에게 Proxmox 연결 등록을 요청하세요.</p>}
            </div>
          ) : null}
          {canConfigure && status.missingConfiguration.length > 0 ? (
            <details className="mt-4 rounded-lg bg-slate-50 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-slate-500">기존 환경 변수 방식의 설정 진단</summary>
              <div className="mt-2 flex flex-wrap gap-2">
                {status.missingConfiguration.map((name) => (
                  <code key={name} className="rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700">{name}</code>
                ))}
              </div>
            </details>
          ) : null}

          <button type="button" onClick={onRetry} className="mt-5 inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
            <RefreshCw className="h-4 w-4" />
            연결 다시 확인
          </button>
        </div>
      </div>
    </section>
  )
}
