import { useState } from 'react'
import { chartSegments, formatMetric } from './model'

const stamp = seconds => seconds == null ? '관찰 없음' : new Date(seconds * 1000).toLocaleString()
const clock = seconds => seconds == null ? '—' : new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

export default function MetricPanel({ history, metric, current, inspect = false, compact = false, color = '#2dd4bf' }) {
  const points = history?.available ? history.points : []
  const [index, setIndex] = useState(null)
  const memoryCapacity = metric.key === 'memory_used_bytes'
    ? Math.max(1, current?.available && Number.isFinite(current.values?.memory_total_bytes) ? current.values.memory_total_bytes : 0,
      ...points.map(point => Number.isFinite(point.values.memory_total_bytes) ? point.values.memory_total_bytes : 0)) : 1
  const chart = chartSegments(points, metric.key, history?.resolution_seconds, metric.unit === '%' ? 100 : memoryCapacity)
  const summary = history?.metrics?.[metric.key]
  const selectedIndex = Math.max(0, Math.min(index ?? points.length - 1, points.length - 1))
  const selected = points[selectedIndex]
  const latest = [...points].reverse().find(point => Number.isFinite(point.values[metric.key]))
  const currentValue = current?.available && Number.isFinite(current.values?.[metric.key]) ? current.values[metric.key] : null
  const value = currentValue ?? latest?.values[metric.key]
  const stale = currentValue === null && summary?.stale
  return <section className="gj-metric-panel" aria-label={`${metric.label} 추이 패널`}>
    <header className="flex items-start justify-between gap-3">
      <div className={compact ? 'flex flex-wrap items-baseline gap-x-3 gap-y-1' : ''}><h3 className="text-xs font-medium text-slate-300">{metric.label}</h3><p className={`${compact ? '' : 'mt-1'} font-mono text-xl font-semibold tracking-tight text-white`}>{formatMetric(value, metric.unit)}</p></div>
      <div className="shrink-0 whitespace-nowrap text-right text-[11px] text-slate-400"><span>{currentValue !== null ? '현재 조회' : '마지막 이력'}</span><p className={stale ? 'mt-1 text-amber-300' : 'mt-1'}>{stale ? '최신 여부 주의' : currentValue !== null ? new Date(current.received_at).toLocaleTimeString() : clock(summary?.latest_value_at)}</p></div>
    </header>
    {chart.segments.length ? <div className="mt-2 flex gap-2">
      <div className="flex w-14 shrink-0 flex-col justify-between whitespace-nowrap pb-5 text-right font-mono text-[10px] text-slate-400"><span>{formatMetric(chart.maximum, metric.unit)}</span><span>{formatMetric(chart.maximum / 2, metric.unit)}</span><span>0</span></div>
      <div className="min-w-0 flex-1">
        <svg viewBox="0 0 800 200" preserveAspectRatio="none" className={`${compact ? 'h-16' : 'h-24'} w-full`} role="img" aria-label={`${metric.label} 추이. 결측 구간은 연결하지 않습니다.`}>
          {[20, 100, 180].map(y => <line key={y} x1="20" x2="780" y1={y} y2={y} stroke="#334155" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />)}
          {chart.segments.map((segment, i) => segment.length === 1
            ? <circle key={i} cx={segment[0].x} cy={segment[0].y} r="2.5" fill={color} />
            : <polyline key={i} points={segment.map(point => `${point.x},${point.y}`).join(' ')} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />)}
        </svg>
        <div className="flex justify-between font-mono text-[10px] text-slate-400"><span>{clock(history.start)}</span><span>{clock(history.end)}</span></div>
      </div>
    </div> : <p className="flex min-h-32 items-center text-xs text-slate-400">{history?.available ? '이 기간의 관찰값 없음' : history?.message || '이력 관찰 없음'}</p>}
    <footer className="mt-2 flex flex-wrap justify-between gap-1 border-t border-slate-700 pt-2 text-[10px] text-slate-400">
      <span>PVE 평균 · {history?.resolution_seconds ? `${history.resolution_seconds}초 간격` : '표본 간격 불명'}</span>
      <span className={summary?.missing_points ? 'text-amber-300' : ''}>{summary ? `유효 ${summary.observed_points} · 누락 ${summary.missing_points}` : '관찰 없음'}</span>
    </footer>
    {inspect && selected && <div className="mt-3 border-t border-slate-700 pt-3 text-xs text-slate-300">
      <label className="block">{metric.label} 시각 선택 · {stamp(selected.timestamp)} · {formatMetric(selected.values[metric.key], metric.unit)}
        <input className="mt-2 block w-full" type="range" min="0" max={points.length - 1} value={selectedIndex} onChange={event => setIndex(Number(event.target.value))} /></label>
      <details className="mt-2"><summary className="cursor-pointer">마지막 관찰 20개</summary><div className="mt-2 max-h-48 overflow-auto"><table className="w-full text-left"><thead><tr><th>시각</th><th>{metric.label}</th></tr></thead><tbody>{points.slice(-20).map(point => <tr key={point.timestamp} className="border-t border-slate-700"><td className="py-1">{stamp(point.timestamp)}</td><td>{formatMetric(point.values[metric.key], metric.unit)}</td></tr>)}</tbody></table></div></details>
    </div>}
  </section>
}
