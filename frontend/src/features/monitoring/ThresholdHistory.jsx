const states = { normal: '정상 관찰', warning: '주의', critical: '위험', unknown: '관찰 불명', open: '초과 관찰', cleared: '정상 관찰 후 해제' }
const time = value => value == null ? '미관찰' : new Date(value * 1000).toLocaleString()

export default function ThresholdHistory({ report }) {
  if (!report) return null
  return <section className="space-y-3 border-t pt-4" aria-label="임계 상태와 이력">
    <h2 className="font-semibold">임계 상태와 이력</h2>
    <div className="grid gap-3 sm:grid-cols-2">{report.rules.map(rule => <div key={rule.key} className="rounded-lg border p-3 text-sm">
      <p className="font-semibold">{rule.label} · 현재 {states[rule.current_state]}</p>
      <p>{rule.current_percent == null ? '관찰 없음' : `${rule.current_percent.toFixed(1)}%`} · 주의 ≥{rule.warning_percent}% · 위험 ≥{rule.critical_percent}%</p>
      <p className="mt-1 text-xs text-slate-500">마지막 이력 상태: {states[rule.history_state]}</p>
    </div>)}</div>
    <p className="text-sm text-slate-600">{report.limitation} {report.retention}</p>
    {!report.history_available && <p className="text-sm text-amber-900">이력 또는 일정한 표본 간격이 없어 임계 구간을 계산하지 못했습니다.</p>}
    {report.history_available && !report.intervals.length && <p className="text-sm">관찰 가능한 평균 표본에서 임계 초과 구간을 찾지 못했습니다. 미관찰 구간의 정상 여부는 알 수 없습니다.</p>}
    {report.truncated && <p className="text-sm text-amber-900">전체 {report.interval_count}개 중 최근 {report.intervals.length}개만 표시합니다.</p>}
    {report.intervals.length > 0 && <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><thead><tr><th className="py-2">지표·상태</th><th>최초 초과 관찰</th><th>마지막 초과 관찰</th><th>정상 관찰</th></tr></thead><tbody>{report.intervals.map(interval => <tr key={interval.id} className="border-t align-top">
      <td className="py-3 pr-3"><span className="font-semibold">{interval.label} · {states[interval.state]}</span><p className="mt-1 text-xs">최고 {states[interval.maximum_severity]}{interval.has_observation_gaps ? ' · 관찰 공백 있음' : ''}</p></td>
      <td className="py-3 pr-3">{time(interval.first_observed_at)}{!interval.onset_confirmed && <p className="text-xs text-amber-900">앞선 상태 불명·이미 높았을 수 있음</p>}</td>
      <td className="py-3 pr-3">{time(interval.last_high_observed_at)}</td><td className="py-3">{time(interval.cleared_observed_at)}</td>
    </tr>)}</tbody></table></div>}
    <p className="text-xs text-slate-500">계산 규칙: {report.rule_version}</p>
  </section>
}
