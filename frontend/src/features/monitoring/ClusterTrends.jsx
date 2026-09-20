import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import MetricPanel from './MetricPanel'
import { aggregateClusterReports, clusterMetrics, readClusterReports } from './clusterMetrics'

const colors = ['#2dd4bf', '#a78bfa', '#38bdf8', '#fbbf24']
export default function ClusterTrends({ nodes, refreshKey }) {
  const [timeframe, setTimeframe] = useState('hour')
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState(null)
  const signature = JSON.stringify(nodes.map(({ id, name, cpuTotal }) => ({ id, name, cpuTotal })))
  const identity = JSON.stringify([signature, timeframe, refreshKey, revision])
  useEffect(() => {
    let cancelled = false
    const selected = JSON.parse(signature)
    if (selected.length) readClusterReports(selected, timeframe, (...args) => apiV1Client.getMetrics(...args), () => cancelled).then(results => {
      if (!cancelled) setState({ identity, report: aggregateClusterReports(selected, results, timeframe) })
    })
    return () => { cancelled = true }
  }, [identity, signature, timeframe])
  const report = state?.identity === identity ? state.report : null
  const busy = nodes.length > 0 && !report
  return <section className="min-w-0" aria-label="클러스터 전체 추이">
    <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-baseline gap-2"><h2 className="text-sm font-semibold">클러스터 전체 추이</h2><span className="text-[11px] text-slate-500">{report ? `${report.observedNodes}/${nodes.length} 노드 관찰` : `${nodes.length}개 노드`}</span></div>
      <div className="flex items-center gap-2"><select aria-label="전체 추이 기간" className="gj-compact-select" value={timeframe} onChange={event => setTimeframe(event.target.value)}><option value="hour">최근 1시간</option><option value="day">최근 1일</option><option value="week">최근 1주</option></select><button aria-label="전체 추이 새로고침" className="gj-icon-button" disabled={busy || !nodes.length} onClick={() => setRevision(value => value + 1)}><RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} /></button></div>
    </header>
    {busy && <p role="status" className="gj-empty-panel">전체 {nodes.length}개 노드의 사용량을 조회하고 있습니다.</p>}
    {!nodes.length && <p className="gj-empty-panel">조회 가능한 노드가 없습니다.</p>}
    {report?.failedNodes.length > 0 && <p role="alert" className="mb-2 rounded-md bg-amber-50 p-2 text-xs text-amber-900">전체 합계 관찰 불완전 · {report.failedNodes.join(', ')}. 누락된 값은 합산하지 않습니다.</p>}
    {report && <div className="grid gap-2 sm:grid-cols-2">{clusterMetrics.map((metric, index) => <MetricPanel key={`${identity}:${metric.key}`} metric={metric} current={report.current} history={report.history} compact color={colors[index]} />)}</div>}
    <p className="mt-2 text-[11px] leading-relaxed text-slate-500">CPU는 현재 노드 CPU 용량 기준 가중 평균 · 메모리·네트워크는 같은 시각의 전체 노드 합계 · 내부 통신 포함 · 누락은 빈 구간으로 표시</p>
  </section>
}
