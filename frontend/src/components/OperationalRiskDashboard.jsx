import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, FileText, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { loadRisksScreenModel, riskLevelLabel, riskToneClass } from '../utils/risksScreen'

function SummaryCard({ label, value, hint, level = 'unknown', icon: Icon = Activity }) {
  return (
    <div className="min-h-28 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <div className={`mt-4 text-3xl font-bold ${riskMetricClass(level)}`}>{value}</div>
        </div>
        <span className={`rounded-lg border p-2 ${riskToneClass(level)}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

function riskMetricClass(level) {
  const normalized = String(level ?? '').toLowerCase()
  if (normalized === 'red') return 'text-red-600'
  if (normalized === 'yellow') return 'text-amber-600'
  if (normalized === 'green') return 'text-emerald-600'
  return 'text-slate-950'
}

function RiskBadge({ level }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${riskToneClass(level)}`}>
      {riskLevelLabel(level)}
    </span>
  )
}

function RiskListItem({ active, risk, onOpen }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`w-full rounded-lg border bg-white p-4 text-left shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50 ${
        active ? 'border-slate-950 ring-2 ring-slate-100' : 'border-slate-200'
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={risk.level} />
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{risk.code}</span>
          </div>
          <div className="line-clamp-2 text-sm font-semibold text-slate-950">{risk.message || '검토가 필요한 위험 항목입니다.'}</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>ID {risk.id}</span>
            {risk.jobId && <span>Job {risk.jobId}</span>}
          </div>
        </div>
        <div className="text-xs font-semibold text-slate-400">{active ? '선택됨' : '상세'}</div>
      </div>
    </button>
  )
}

function DetailRow({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold text-slate-950">{value || '-'}</div>
    </div>
  )
}

function RiskDetailPanel({ risk }) {
  if (!risk) {
    return (
      <aside className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2 text-lg font-semibold text-slate-950">
          <ShieldCheck className="h-5 w-5 text-slate-500" />
          선택한 알림
        </div>
        <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">목록에서 항목을 선택하면 상세 근거가 표시됩니다.</div>
      </aside>
    )
  }

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold text-slate-950">
            <AlertTriangle className="h-5 w-5 text-slate-500" />
            선택한 알림
          </div>
          <p className="mt-1 text-sm text-slate-500">작업 전에 확인해야 하는 근거입니다.</p>
        </div>
        <RiskBadge level={risk.level} />
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
        <DetailRow label="Risk ID" value={risk.id} />
        <DetailRow label="Job ID" value={risk.jobId} />
        <DetailRow label="Code" value={risk.code} />
        <DetailRow label="Level" value={riskLevelLabel(risk.level)} />
      </div>

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Message</div>
        <div className="mt-2 text-sm leading-6 text-slate-800">{risk.message || '검토가 필요한 위험 항목입니다.'}</div>
      </div>

      {risk.artifactsUrl && (
        <a
          href={risk.artifactsUrl}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          <FileText className="h-4 w-4" />
          근거 파일 보기
        </a>
      )}
    </aside>
  )
}

function filterRisks(items, query) {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return items
  return items.filter((risk) => [risk.id, risk.jobId, risk.level, risk.code, risk.message].some((value) => String(value ?? '').toLowerCase().includes(normalized)))
}

function OperationalRiskDashboard() {
  const [model, setModel] = useState(null)
  const [query, setQuery] = useState('')
  const [activeRiskId, setActiveRiskId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextModel = await loadRisksScreenModel(apiV1Client)
      setModel(nextModel)
      setActiveRiskId((currentId) => currentId || nextModel.items[0]?.id || null)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load Risks')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  const summary = model?.summary || { total: 0, red: 0, yellow: 0, green: 0, unknown: 0 }
  const risks = useMemo(() => filterRisks(model?.items || [], query), [model, query])
  const activeRisk = risks.find((risk) => risk.id === activeRiskId) || risks[0] || null

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${summary.red > 0 ? riskToneClass('red') : riskToneClass('green')}`}>
              Risk {summary.red > 0 ? 'Check' : 'OK'}
            </span>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live read-only</span>
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">Risks / Alerts</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">VM 생성 검토와 작업 경계에서 나온 위험 신호를 읽기 전용으로 확인합니다.</p>
        </div>
        <button
          type="button"
          onClick={loadModel}
          className="inline-flex w-fit items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          새로고침
        </button>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <SummaryCard label="Total" value={summary.total} hint="전체 알림" />
        <SummaryCard label="Red" value={summary.red} hint="즉시 확인" level="red" icon={AlertTriangle} />
        <SummaryCard label="Yellow" value={summary.yellow} hint="주의 필요" level="yellow" icon={AlertTriangle} />
        <SummaryCard label="Green" value={summary.green} hint="정상 판단" level="green" icon={ShieldCheck} />
        <SummaryCard label="Unknown" value={summary.unknown} hint="분류 대기" />
      </div>

      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
        <div className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 h-4 w-4" />
          <div>
            <div className="font-semibold">읽기 전용 안전 경계</div>
            <div>이 화면은 위험 근거 조회만 지원합니다. 정책 변경이나 실제 실행 조작은 이 탭에서 제공하지 않습니다.</div>
          </div>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">알림 목록</h3>
              <div className="mt-1 text-xs text-slate-500">높은 위험도부터 정렬됩니다.</div>
            </div>
            <div className="relative w-full lg:max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="ID, 작업, 코드, 메시지 검색"
                className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-100"
              />
            </div>
          </div>

          <div className="space-y-3 p-4">
            {loading && !model ? (
              <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">알림 데이터를 불러오는 중입니다.</div>
            ) : risks.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">조건에 맞는 위험 항목이 없습니다.</div>
            ) : (
              risks.map((risk) => (
                <RiskListItem
                  key={risk.id}
                  active={activeRisk?.id === risk.id}
                  risk={risk}
                  onOpen={() => setActiveRiskId(risk.id)}
                />
              ))
            )}
          </div>
        </div>

        <RiskDetailPanel risk={activeRisk} />
      </div>
    </section>
  )
}

export default OperationalRiskDashboard
