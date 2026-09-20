import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import MetricPanel from '../../features/monitoring/MetricPanel'
import useMetricsReport from '../../features/monitoring/useMetricsReport'
import ThresholdHistory from '../../features/monitoring/ThresholdHistory'
import { apiV1Client } from '../../shared/api/apiV1'

const input = 'mt-1 block w-full rounded-md border border-slate-300 bg-white px-2 py-1.5'
const periods = { hour: '최근 1시간', day: '최근 1일', week: '최근 1주', month: '최근 1개월', year: '최근 1년' }
const stamp = seconds => seconds == null ? '관찰 없음' : new Date(seconds * 1000).toLocaleString()
const colors = ['#2dd4bf', '#a78bfa', '#38bdf8', '#fbbf24', '#fb7185', '#818cf8']

export default function MetricsPage({ nodeOnly = false }) {
  const [search] = useSearchParams()
  const initial = useRef({ kind: nodeOnly ? 'node' : search.get('kind') || 'node', node: search.get('node') || '', resource: nodeOnly ? '' : search.get('vmid') || search.get('storage') || '' })
  const [kind, setKind] = useState(initial.current.kind)
  const [node, setNode] = useState(initial.current.node)
  const [resource, setResource] = useState(initial.current.resource)
  const [timeframe, setTimeframe] = useState('hour')
  const [options, setOptions] = useState({ nodes: [], vms: [], storage: [] })
  const [request, setRequest] = useState(null)
  const [revision, setRevision] = useState(0)
  const [metricKey, setMetricKey] = useState('')
  const [inventoryError, setInventoryError] = useState('')
  const [loadingOptions, setLoadingOptions] = useState(true)
  const { report, busy, error } = useMetricsReport(request?.kind || 'node', request?.node || '', request?.resource || '', request?.timeframe || 'hour', revision)
  useEffect(() => {
    let cancelled = false
    Promise.allSettled([apiV1Client.listNodes(), apiV1Client.listVms(), apiV1Client.listStorage()]).then(results => {
      if (cancelled) return
      const loaded = Object.fromEntries(['nodes', 'vms', 'storage'].map((key, index) => [key, results[index].status === 'fulfilled' ? results[index].value : []]))
      setOptions(loaded); setLoadingOptions(false)
      if (results.some(result => result.status === 'rejected')) setInventoryError('일부 대상 목록을 읽지 못했습니다. 연결 상태와 권한을 확인하세요.')
      const selectedNode = initial.current.node || loaded.nodes[0]?.node_id || ''
      setNode(selectedNode)
      if (selectedNode && (initial.current.kind === 'node' || initial.current.resource)) setRequest({ ...initial.current, node: selectedNode, timeframe: 'hour' })
    })
    return () => { cancelled = true }
  }, [])
  const selectedNode = options.nodes.find(item => item.node_id === node)
  const metric = report?.metrics.find(item => item.key === metricKey) || report?.metrics[0]
  const visibleMetrics = report?.metrics.filter(item => item.key !== 'memory_total_bytes') || []
  const missingMetrics = report?.metrics.filter(item => !Number.isFinite(report.current.values?.[item.key])) || []
  const change = setter => event => { setter(event.target.value); setRequest(null) }
  return <section className="space-y-3">
    <header className="flex flex-wrap items-center justify-between gap-2"><div><h1 className="text-xl font-semibold">{nodeOnly ? '노드 상세' : '자원 모니터링'}</h1><p className="mt-1 text-xs text-slate-500">CPU·메모리·네트워크 · 선택한 자원의 현재 조회값과 PVE 평균 추이</p></div><Link className="text-xs font-medium text-teal-700 hover:underline" to="/insights/alerts">실행 실패·복구 이력 →</Link></header>
    {inventoryError && <p role="alert" className="rounded-md bg-amber-50 p-3 text-xs text-amber-900">{inventoryError}</p>}
    <form className="gj-panel p-3" onSubmit={event => { event.preventDefault(); setRequest({kind, node, resource, timeframe}); setRevision(value => value + 1) }}>
      <fieldset disabled={busy || loadingOptions} className={`grid grid-cols-2 items-end gap-2 ${nodeOnly ? 'sm:grid-cols-3' : 'xl:grid-cols-5'}`}>
        {!nodeOnly && <label className="text-xs text-slate-600">자원 종류<select className={input} value={kind} onChange={event => { setKind(event.target.value); setResource(''); setRequest(null) }}><option value="node">노드</option><option value="vm">VM</option><option value="storage">스토리지</option></select></label>}
        <label className="text-xs text-slate-600">노드<select required className={input} value={node} onChange={event => { setNode(event.target.value); setResource(''); setRequest(null) }}><option value="">선택하세요</option>{options.nodes.map(row => <option key={row.node_id} value={row.node_id}>{row.node_id}</option>)}</select></label>
        {kind !== 'node' && <label className="text-xs text-slate-600">{kind === 'vm' ? 'VM' : '스토리지'}<select required className={input} value={resource} onChange={change(setResource)}><option value="">선택하세요</option>{(kind === 'vm' ? options.vms : options.storage).filter(row => row.node_id === node).map(row => { const id = kind === 'vm' ? row.vmid : row.storage_id; return <option key={id} value={id}>{id}{row.name ? ` · ${row.name}` : ''}</option> })}</select></label>}
        <label className="text-xs text-slate-600">기간<select className={input} value={timeframe} onChange={change(setTimeframe)}>{Object.entries(periods).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button className="min-h-9 rounded-md bg-teal-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{busy || loadingOptions ? '조회 중…' : '사용량과 추이 조회'}</button>
      </fieldset>
    </form>
    {nodeOnly && selectedNode && <section aria-label="선택 노드 자원" className="gj-panel flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-2 text-xs">
      <strong>{selectedNode.node_id} · {selectedNode.status}</strong>
      <span>{selectedNode.cpu_total > 0 ? `${selectedNode.cpu_total} logical CPU` : 'CPU 용량 미관찰'}</span>
      <span>{selectedNode.memory_total_mb > 0 ? `${(selectedNode.memory_total_mb / 1024).toFixed(1)} GiB 메모리` : '메모리 용량 미관찰'}</span>
      <span>스토리지: {selectedNode.storage?.map(item => item.storage_id).join(' · ') || '관찰 없음'}</span>
      <span>브리지: {selectedNode.networks?.map(item => item.bridge_id).join(' · ') || '관찰 없음'}</span>
    </section>}
    {error && <p role="alert" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">{error} <Link className="underline" to="/settings/proxmox">연결 확인</Link></p>}
    {busy && <p className="gj-empty-panel" role="status">PVE의 현재 값과 이력을 조회하고 있습니다.</p>}
    {!request && !loadingOptions && <p className="gj-empty-panel">대상과 기간을 선택한 뒤 조회하세요.</p>}
    {report && <>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs"><h2 className="font-semibold">{report.target.node_id} · {report.target.vmid || report.target.storage_id || '노드'} · {periods[report.timeframe]}</h2><span className="text-slate-500">조회 수신 {new Date(report.current.received_at).toLocaleString()}</span></div>
      {!report.current.available && <p role="status" className="rounded-md bg-amber-50 p-3 text-xs">현재 사용량 조회 불가: {report.current.message}</p>}
      <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">{visibleMetrics.map((item, index) => <MetricPanel key={`${report.history.received_at}:${item.key}`} history={report.history} current={report.current} metric={item} color={colors[index % colors.length]} />)}</div>
      <div className="gj-panel px-3 py-2 text-[11px] text-slate-500">
        <p>실제 관찰 범위: {stamp(report.history.start)} ~ {stamp(report.history.end)} · 평균(AVERAGE) · 누락을 0으로 채우거나 결측 구간을 연결하지 않습니다.</p>
        <p className="mt-1">요청 기간 전체 데이터 보존은 보장하지 않습니다. {report.current.limitation}</p>
        {missingMetrics.length > 0 && <p className="mt-1">현재 관찰 없음: {missingMetrics.map(item => item.label).join(' · ')}. 값이 있는 경우 이력의 마지막 값으로 구분해 표시합니다.</p>}
        {!report.history.available && <p className="mt-1 text-amber-800">이력 조회 불가: {report.history.message}</p>}
      </div>
      {report.history.available && <details className="gj-panel p-3"><summary className="cursor-pointer text-sm font-semibold">시각별 상세 값 조회</summary><div className="mt-3 space-y-3"><label className="block text-xs">추이 지표<select className={input} value={metric?.key || ''} onChange={event => setMetricKey(event.target.value)}>{report.metrics.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>{metric && <MetricPanel key={`${metric.key}:${report.history.received_at}`} history={report.history} current={report.current} metric={metric} inspect />}</div></details>}
      {report.target.kind === 'vm' && <Link className="inline-block text-sm text-teal-700 underline" to={`/instances/${report.target.vmid}`}>VM 상세와 작업</Link>}
      <div className="gj-panel p-3"><ThresholdHistory report={report.thresholds} /></div>
    </>}
  </section>
}
