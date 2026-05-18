import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, HelpCircle, Monitor, Network, RefreshCw, XCircle } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { buildNetworkReadinessModel, buildSourceMigrationReadinessView, statusTone } from '../utils/networkReadiness'

function StatusPill({ tone = 'slate', children }) {
  const tones = {
    green: 'border-green-200 bg-green-50 text-green-700',
    yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800',
    red: 'border-red-200 bg-red-50 text-red-700',
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone] || tones.slate}`}>{children}</span>
}

function SummaryCard({ label, value, sublabel }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-slate-950">{value}</div>
      {sublabel && <div className="mt-1 text-xs text-slate-500">{sublabel}</div>}
    </div>
  )
}

function readinessLabel(status) {
  if (status === 'ready') return '준비됨'
  if (status === 'needs_review') return '검토 필요'
  if (status === 'blocked') return '차단'
  if (status === 'active') return '활성'
  if (status === 'inactive') return '비활성'
  if (status === 'missing') return '매핑 없음'
  return '정보 부족'
}

function reasonLabel(reason) {
  const labels = {
    shared_active_bridge_observed: '같은 활성 bridge 확인',
    no_shared_active_bridge: '일치/후보 없음',
    exact_active_bridge_observed: '같은 활성 bridge 확인',
    cidr_verified_exact_bridge_match: 'CIDR 일치 확인',
    bridge_name_cidr_unverified: 'CIDR 근거 부족',
    bridge_id_subnet_mismatch: '같은 bridge ID의 CIDR 불일치',
    same_cidr_different_bridge_ids: '같은 CIDR, bridge 이름 다름',
    target_bridge_missing: '대상 bridge 없음',
    target_bridge_inactive: '대상 bridge 비활성',
    source_bridge_cidr_unavailable: 'source bridge CIDR 없음',
    bridge_evidence_missing: '네트워크 근거 부족',
    vm_nic_bridge_evidence_missing: 'vm_nic_bridge_evidence_missing',
    duplicate_ip_observed: '중복 IP 감지',
  }
  return labels[reason] || reason || '-'
}

function bridgeList(values = [], fallback = '-') {
  return values.length > 0 ? values.join(', ') : fallback
}

function statusIcon(status) {
  if (status === 'ready' || status === 'active') return <CheckCircle2 className="h-4 w-4" />
  if (status === 'blocked' || status === 'inactive') return <XCircle className="h-4 w-4" />
  if (status === 'needs_review') return <AlertTriangle className="h-4 w-4" />
  return <HelpCircle className="h-4 w-4" />
}

function resultValue(result) {
  return result?.status === 'fulfilled' ? result.value : []
}

function resultAvailable(result) {
  return result?.status === 'fulfilled'
}

function resultError(label, result) {
  if (result?.status !== 'rejected') return null
  const message = result.reason instanceof Error ? result.reason.message : String(result.reason || 'request failed')
  return `${label}: ${message}`
}

function IpEvidenceCell({ vm }) {
  if (vm.ipAddresses.length === 0) return '관찰 IP 없음'
  const labels = vm.ipAddresses.map((ipAddress) => {
    const scopes = Array.from(new Set(
      vm.ipEvidence
        .filter((item) => item.ipAddress === ipAddress)
        .map((item) => item.scope)
        .filter(Boolean)
    ))
    const suffix = scopes.length > 0 && !scopes.every((scope) => scope === 'primary')
      ? ` (${scopes.join(', ')})`
      : ''
    return `${ipAddress}${suffix}`
  })
  return labels.join(', ')
}

function MigrationSourceSelector({ model, view, onSourceChange }) {
  if (model.nodes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
        노드 inventory가 없어 마이그레이션 원본을 선택할 수 없습니다.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <label htmlFor="network-migration-source" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        마이그레이션 원본
      </label>
      <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <select
          id="network-migration-source"
          value={view.selectedSourceNodeId}
          onChange={(event) => onSourceChange(event.target.value)}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 sm:max-w-sm"
        >
          {model.nodes.map((node) => (
            <option key={node.nodeId} value={node.nodeId}>
              {node.displayName}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <span className="font-medium text-slate-950">{view.sourceNode?.displayName || view.selectedSourceNodeId}</span>
          {view.sourceNode && <StatusPill tone={view.sourceNode.status === 'online' ? 'green' : 'slate'}>{view.sourceNode.status}</StatusPill>}
          <StatusPill tone={view.summary.duplicateIpWarnings > 0 ? 'red' : 'slate'}>
            중복 IP 경고 {view.summary.duplicateIpWarnings}
          </StatusPill>
        </div>
      </div>
    </div>
  )
}

function comparisonLabel(status) {
  const labels = {
    exact: '일치',
    bridge_name_unverified: '이름만 같음',
    bridge_id_subnet_mismatch: 'CIDR 불일치',
    remap_candidate: 'remap 필요',
    missing: '매핑 없음',
    inactive: '비활성',
    unknown: '정보 부족',
  }
  return labels[status] || readinessLabel(status)
}

function targetBridgeLabel(comparison) {
  if (comparison.targetBridgeIds.length > 0) return bridgeList(comparison.targetBridgeIds)
  if (comparison.status === 'missing') return '없음'
  if (comparison.status === 'unknown') return '정보 부족'
  return '-'
}

function uniqueBridgeValues(bridges = [], field) {
  return Array.from(new Set(
    bridges
      .map((bridge) => bridge?.[field])
      .filter(Boolean)
  ))
}

function valueOrNone(value) {
  return value || '없음'
}

function comparisonDetail(comparison) {
  const targetCidrs = uniqueBridgeValues(comparison.targetBridges, 'cidr')
  const targetGateways = uniqueBridgeValues(comparison.targetBridges, 'gateway')

  if (comparison.status === 'exact') {
    const cidr = comparison.sourceCidr || comparison.cidrs[0] || 'CIDR 없음'
    const gateway = comparison.sourceGateway || comparison.gateways[0]
    return gateway ? `${cidr} · GW ${gateway}` : cidr
  }

  if (comparison.status === 'bridge_name_unverified') {
    return `CIDR 근거 부족 · source: ${valueOrNone(comparison.sourceCidr)} · target: ${targetCidrs[0] || '없음'}`
  }

  if (comparison.status === 'remap_candidate') {
    const cidr = comparison.sourceCidr || comparison.cidrs[0] || 'CIDR 없음'
    return `같은 CIDR ${cidr} · bridge 이름 다름`
  }

  if (comparison.status === 'bridge_id_subnet_mismatch') {
    return `source: ${valueOrNone(comparison.sourceCidr)} · target: ${targetCidrs[0] || '없음'}`
  }

  if (comparison.status === 'inactive') {
    const gatewayText = targetGateways.length > 0 ? ` · target GW ${targetGateways.join(', ')}` : ''
    return `대상 bridge 비활성 · source: ${valueOrNone(comparison.sourceCidr)} · target: ${targetCidrs[0] || '없음'}${gatewayText}`
  }

  if (comparison.status === 'missing') {
    if (comparison.reason === 'source_bridge_cidr_unavailable') {
      return 'source CIDR 없음 · 대상 후보 없음'
    }
    return `source: ${valueOrNone(comparison.sourceCidr)} · target: 없음`
  }

  return reasonLabel(comparison.reason)
}

function TargetResultCell({ row }) {
  const summary = row.networkComparisonSummary || {}
  const reviewCount = (summary.bridgeNameUnverified || 0) + (summary.remapCandidate || 0)
  const blockedCount = (summary.bridgeIdSubnetMismatch || 0) + (summary.missing || 0) + (summary.inactive || 0)
  const parts = [
    summary.exact > 0 ? `일치 ${summary.exact}` : '',
    reviewCount > 0 ? `검토 ${reviewCount}` : '',
    blockedCount > 0 ? `차단 ${blockedCount}` : '',
    summary.unknown > 0 ? `정보 부족 ${summary.unknown}` : '',
  ].filter(Boolean)

  return (
    <div>
      <StatusPill tone={statusTone(row.status)}>
        <span className="mr-1 inline-flex">{statusIcon(row.status)}</span>
        {readinessLabel(row.status)}
      </StatusPill>
      <div className="mt-1 text-xs text-slate-500">{parts.length > 0 ? parts.join(' · ') : '매핑 근거 없음'}</div>
      <div className="mt-1 text-xs text-slate-500">{reasonLabel(row.reason)}</div>
    </div>
  )
}

function SourceTargetNetworkMap({ row }) {
  if (row.networkComparisons.length === 0) return reasonLabel(row.reason)

  return (
    <div className="flex min-w-72 flex-col gap-2">
      {row.networkComparisons.map((comparison) => (
        <div key={comparison.id} className="border-l-2 border-slate-200 pl-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-950">{comparison.sourceBridgeId}</span>
            <span className="text-xs font-semibold text-slate-400">-&gt;</span>
            <span className="font-semibold text-slate-800">{targetBridgeLabel(comparison)}</span>
            <StatusPill tone={statusTone(comparison.status)}>{comparisonLabel(comparison.status)}</StatusPill>
          </div>
          <div className="mt-1 text-xs text-slate-500">{comparisonDetail(comparison)}</div>
        </div>
      ))}
    </div>
  )
}

function TargetReadinessTable({ view }) {
  if (view.targetRows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
        선택한 source와 비교할 대상 노드가 없습니다.
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">대상 노드</th>
              <th className="px-4 py-3">결과</th>
              <th className="px-4 py-3">네트워크 매핑</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {view.targetRows.map((row) => (
              <tr key={row.id}>
                <td className="px-4 py-3">
                  <div className="flex min-w-0 items-center gap-2 font-semibold text-slate-950">
                    <span className="truncate">{view.sourceNode?.displayName || view.selectedSourceNodeId}</span>
                    <ArrowRight className="h-4 w-4 shrink-0 text-slate-400" />
                    <span className="truncate">{row.targetNode.displayName}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{row.targetNode.status}</div>
                </td>
                <td className="px-4 py-3"><TargetResultCell row={row} /></td>
                <td className="px-4 py-3 text-slate-700">
                  <SourceTargetNetworkMap row={row} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function VmImpactTable({ view }) {
  if (view.sourceVms.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
        선택한 source node에 표시할 VM이 없습니다.
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">VM</th>
              <th className="px-4 py-3">노드</th>
              <th className="px-4 py-3">준비도</th>
              <th className="px-4 py-3">관찰 IP</th>
              <th className="px-4 py-3">게스트 에이전트</th>
              <th className="px-4 py-3">경고</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {view.sourceVms.map((vm) => (
              <tr key={vm.id}>
                <td className="px-4 py-3">
                  <div className="font-semibold text-slate-950">{vm.name}</div>
                  <div className="text-xs text-slate-500">{vm.vmid}</div>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-700">{vm.nodeId}</td>
                <td className="px-4 py-3">
                  <StatusPill tone="yellow">정보 부족</StatusPill>
                  <div className="mt-1 text-xs text-slate-500">{reasonLabel(vm.readiness.reason)}</div>
                </td>
                <td className="px-4 py-3 text-slate-700">
                  <IpEvidenceCell vm={vm} />
                </td>
                <td className="px-4 py-3">
                  <StatusPill tone={vm.guestAgent.available ? 'green' : 'yellow'}>
                    {vm.guestAgent.available ? '확인됨' : '미확인'}
                  </StatusPill>
                </td>
                <td className="px-4 py-3 text-slate-700">
                  <div className="flex flex-col gap-1">
                    <span className="inline-flex items-center gap-1 text-yellow-700">
                      <AlertTriangle className="h-4 w-4" />
                      {reasonLabel('vm_nic_bridge_evidence_missing')}
                    </span>
                    {vm.duplicateIps.map((ipAddress) => (
                      <span key={ipAddress} className="inline-flex items-center gap-1 text-red-700">
                        <AlertTriangle className="h-4 w-4" />
                        중복 IP: {ipAddress}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function NetworkReadinessScreen() {
  const [model, setModel] = useState(() => buildNetworkReadinessModel())
  const [selectedSourceNodeId, setSelectedSourceNodeId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const sourceView = buildSourceMigrationReadinessView(model, selectedSourceNodeId)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nodesResult, vmsResult, networksResult] = await Promise.allSettled([
        apiV1Client.listNodes(),
        apiV1Client.listVms(),
        apiV1Client.listNetworks(),
      ])
      const errors = [
        resultError('nodes', nodesResult),
        resultError('vms', vmsResult),
        resultError('networks', networksResult),
      ].filter(Boolean)
      setModel(buildNetworkReadinessModel({
        nodes: resultValue(nodesResult),
        vms: resultValue(vmsResult),
        networks: resultValue(networksResult),
        evidence: {
          nodesAvailable: resultAvailable(nodesResult),
          vmsAvailable: resultAvailable(vmsResult),
          networksAvailable: resultAvailable(networksResult),
        },
        errors,
      }))
      if (errors.length > 0) {
        setError(`일부 inventory 근거만 표시합니다: ${errors.join('; ')}`)
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '네트워크 준비도 근거를 inventory에서 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-blue-600">
            <Network className="h-4 w-4" />
            네트워크 준비도
          </div>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">네트워크 준비도</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            기존 live inventory 응답을 조합해 마이그레이션 전 네트워크 근거를 읽기 전용으로 보여줍니다. Proxmox 네트워크 설정을 변경하거나 DRS 실행 권한을 부여하지 않습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={loadModel}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          새로고침
        </button>
      </header>

      {error && <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">{error}</div>}

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Network className="h-5 w-5 text-slate-500" />
          <h2 className="text-lg font-semibold text-slate-950">마이그레이션 원본</h2>
        </div>
        <MigrationSourceSelector model={model} view={sourceView} onSourceChange={setSelectedSourceNodeId} />
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-slate-500" />
          <h2 className="text-lg font-semibold text-slate-950">대상 네트워크 비교</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <SummaryCard label="대상 노드" value={sourceView.targetRows.length} sublabel={`원본 bridge ${bridgeList(sourceView.summary.sourceBridgeIds, '활성 없음')}`} />
          <SummaryCard label="준비됨" value={sourceView.summary.ready} sublabel={`정보 부족 ${sourceView.summary.unknown}`} />
          <SummaryCard label="검토 필요" value={sourceView.summary.needsReview} sublabel={`이름/remap ${sourceView.summary.bridgeNameUnverifiedMappings + sourceView.summary.remapCandidateMappings}`} />
          <SummaryCard label="차단" value={sourceView.summary.blocked} sublabel={`불일치/없음 ${sourceView.summary.bridgeIdSubnetMismatchMappings + sourceView.summary.missingMappings + sourceView.summary.inactiveMappings}`} />
          <SummaryCard label="영향 VM" value={sourceView.summary.impactedVms} sublabel={`중복 IP 경고 ${sourceView.summary.duplicateIpWarnings}`} />
        </div>
        <TargetReadinessTable view={sourceView} />
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Monitor className="h-5 w-5 text-slate-500" />
          <h2 className="text-lg font-semibold text-slate-950">영향 VM</h2>
        </div>
        <VmImpactTable view={sourceView} />
      </section>
    </div>
  )
}

export default NetworkReadinessScreen
