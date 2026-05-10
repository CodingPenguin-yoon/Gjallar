import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, FolderGit2, Network, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { buildNetworkPolicyModel, formFromBridge, upsertNetworkPolicyBinding } from '../utils/networkPolicy'

function StatusPill({ tone = 'slate', children }) {
  const tones = {
    green: 'border-green-200 bg-green-50 text-green-700',
    yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800',
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone] || tones.slate}`}>{children}</span>
}

function SummaryCard({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-slate-950">{value}</div>
    </div>
  )
}

function BridgeRow({ bridge, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(bridge)}
      className={`flex w-full items-center justify-between gap-3 rounded-lg border p-3 text-left transition ${
        selected ? 'border-blue-400 bg-blue-50' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
      }`}
    >
      <div>
        <div className="font-semibold text-slate-950">{bridge.bridgeId}</div>
        <div className="mt-1 text-xs text-slate-500">{bridge.type} · {bridge.active ? 'active' : 'inactive'}</div>
      </div>
      <div className="flex flex-col items-end gap-1">
        <StatusPill tone={bridge.registered ? 'green' : 'yellow'}>{bridge.registered ? '등록됨' : '미등록'}</StatusPill>
        {bridge.displayName && <span className="text-xs text-slate-500">{bridge.displayName}</span>}
      </div>
    </button>
  )
}

function RegisteredPolicyList({ policy }) {
  const networks = policy?.networks || []
  if (networks.length === 0) {
    return <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">아직 등록된 네트워크 정책이 없습니다.</div>
  }
  return (
    <div className="space-y-3">
      {networks.map((network) => (
        <div key={network.network_id} className="rounded-lg border border-slate-200 p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-slate-950">{network.display_name || network.network_id}</div>
              <div className="text-xs text-slate-500">{network.network_id}</div>
            </div>
            <StatusPill>{network.nodes.length} bridge</StatusPill>
          </div>
          <div className="mt-3 space-y-2">
            {network.nodes.map((node) => (
              <div key={`${node.node_id}:${node.bridge_id}`} className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <div className="font-medium text-slate-800">{node.node_id} · {node.bridge_id}</div>
                <div>{node.subnet || 'subnet 미지정'} / {node.gateway || 'gateway 미지정'}</div>
                {(node.static_ip_ranges || []).length > 0 && (
                  <div className="mt-1">
                    {(node.static_ip_ranges || []).map((range, index) => (
                      <span key={`${range.start}-${range.end}-${index}`} className="mr-2 inline-block">
                        {range.start || '시작 미지정'} - {range.end || '끝 미지정'}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function NetworkPolicyScreen() {
  const [model, setModel] = useState(null)
  const [draftPolicy, setDraftPolicy] = useState(null)
  const [form, setForm] = useState(formFromBridge())
  const [selectedBridgeId, setSelectedBridgeId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const nextModel = buildNetworkPolicyModel(await apiV1Client.getNetworkPolicy())
      setModel(nextModel)
      setDraftPolicy(nextModel.policy)
      const firstBridge = nextModel.bridges[0]
      if (firstBridge) {
        setSelectedBridgeId(firstBridge.id)
        setForm(formFromBridge(firstBridge))
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '네트워크 정보를 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  const selectedBridge = useMemo(
    () => model?.bridges.find((bridge) => bridge.id === selectedBridgeId),
    [model, selectedBridgeId],
  )

  const selectBridge = (bridge) => {
    setSelectedBridgeId(bridge.id)
    setForm(formFromBridge(bridge))
    setMessage('')
  }

  const updateForm = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }))
    setMessage('')
  }

  const updateStaticIpRange = (index, field, value) => {
    setForm((current) => ({
      ...current,
      staticIpRanges: (current.staticIpRanges || [{ start: '', end: '' }]).map((range, currentIndex) => (
        currentIndex === index ? { ...range, [field]: value } : range
      )),
    }))
    setMessage('')
  }

  const addStaticIpRange = () => {
    setForm((current) => ({
      ...current,
      staticIpRanges: [...(current.staticIpRanges || []), { start: '', end: '' }],
    }))
    setMessage('')
  }

  const removeStaticIpRange = (index) => {
    setForm((current) => {
      const ranges = (current.staticIpRanges || []).filter((_, currentIndex) => currentIndex !== index)
      return {
        ...current,
        staticIpRanges: ranges.length > 0 ? ranges : [{ start: '', end: '' }],
      }
    })
    setMessage('')
  }

  const addToDraft = () => {
    const nextPolicy = upsertNetworkPolicyBinding(draftPolicy, form)
    setDraftPolicy(nextPolicy)
    setMessage('저장 전 정책에 반영했습니다.')
  }

  const savePolicy = async () => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const result = await apiV1Client.saveNetworkPolicy({ policy: draftPolicy })
      setMessage(result.commit_sha ? `IaC에 저장했습니다: ${result.commit_sha.slice(0, 12)}` : 'IaC에 저장했습니다.')
      await loadModel()
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '네트워크 정책 저장에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const bridgesByNode = model?.bridgesByNode || {}
  const nodes = model?.nodes || []
  const canSavePolicy = (draftPolicy?.networks || []).length > 0

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-blue-600">
            <Network className="h-4 w-4" />
            Networks
          </div>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">네트워크 정책</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Proxmox에서 발견한 노드별 vmbr을 공용 IaC 정책과 맞춰 관리합니다.
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

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">{message}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="노드" value={model?.summary.nodes || 0} />
        <SummaryCard label="발견된 vmbr" value={model?.summary.total || 0} />
        <SummaryCard label="등록됨" value={model?.summary.registered || 0} />
        <SummaryCard label="미등록" value={model?.summary.unregistered || 0} />
      </div>

      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
        <div className="flex items-start gap-2">
          <FolderGit2 className="mt-0.5 h-4 w-4" />
          <div>
            <div className="font-semibold">저장 위치</div>
            <div className="mt-1 break-all">{model?.policyPath || 'IaC 정책 파일을 확인 중입니다.'}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="space-y-4">
          {loading && !model ? (
            <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">네트워크 목록을 불러오는 중입니다.</div>
          ) : nodes.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">발견된 vmbr이 없습니다.</div>
          ) : (
            nodes.map((nodeId) => (
              <div key={nodeId} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="font-semibold text-slate-950">{nodeId}</h2>
                  <StatusPill>{bridgesByNode[nodeId]?.length || 0} bridge</StatusPill>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(bridgesByNode[nodeId] || []).map((bridge) => (
                    <BridgeRow
                      key={bridge.id}
                      bridge={bridge}
                      selected={selectedBridge?.id === bridge.id}
                      onSelect={selectBridge}
                    />
                  ))}
                </div>
              </div>
            ))
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="font-semibold text-slate-950">vmbr 등록</h2>
            <div className="mt-4 space-y-3">
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">노드</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.nodeId} onChange={(event) => updateForm('nodeId', event.target.value)} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">Bridge</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.bridgeId} onChange={(event) => updateForm('bridgeId', event.target.value)} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">네트워크 ID</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.networkId} onChange={(event) => updateForm('networkId', event.target.value)} placeholder="server-net" />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">표시 이름</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.displayName} onChange={(event) => updateForm('displayName', event.target.value)} placeholder="서버망" />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">Subnet</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.subnet} onChange={(event) => updateForm('subnet', event.target.value)} placeholder="192.168.2.0/24" />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">Gateway</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.gateway} onChange={(event) => updateForm('gateway', event.target.value)} placeholder="192.168.2.1" />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium text-slate-700">DNS</span>
                <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.dns} onChange={(event) => updateForm('dns', event.target.value)} placeholder="192.168.2.1, 1.1.1.1" />
              </label>
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-slate-700">고정 IP 범위</span>
                  <button type="button" onClick={addStaticIpRange} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                    <Plus className="h-3.5 w-3.5" />
                    범위 추가
                  </button>
                </div>
                <div className="space-y-2">
                  {(form.staticIpRanges || [{ start: '', end: '' }]).map((range, index) => (
                    <div key={index} className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] items-center gap-2">
                      <input
                        className="min-w-0 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                        value={range.start}
                        onChange={(event) => updateStaticIpRange(index, 'start', event.target.value)}
                        placeholder="192.168.2.140"
                      />
                      <span className="text-sm text-slate-400">-</span>
                      <input
                        className="min-w-0 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                        value={range.end}
                        onChange={(event) => updateStaticIpRange(index, 'end', event.target.value)}
                        placeholder="192.168.2.150"
                      />
                      <button type="button" onClick={() => removeStaticIpRange(index)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-300 text-slate-500 hover:bg-slate-50" aria-label="고정 IP 범위 삭제">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              <button type="button" onClick={addToDraft} className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                <CheckCircle2 className="h-4 w-4" />
                정책에 추가
              </button>
              <button type="button" onClick={savePolicy} disabled={saving || !canSavePolicy} className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                <Save className="h-4 w-4" />
                IaC에 저장
              </button>
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 font-semibold text-slate-950">등록된 정책</h2>
            <RegisteredPolicyList policy={draftPolicy} />
          </section>
        </aside>
      </div>
    </div>
  )
}

export default NetworkPolicyScreen
