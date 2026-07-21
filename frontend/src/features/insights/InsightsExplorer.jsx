import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Clock3, Eye, FileSearch, RefreshCw, ShieldCheck } from 'lucide-react'
import {
  INSIGHT_CATEGORIES,
  insightStatusTone,
  insightToneClass,
} from '../../entities/insight/model'
import { apiV1Client } from '../../shared/api/apiV1'
import { loadInsightsModel } from './model'

function StatusBadge({ value }) {
  const tone = insightStatusTone(value)
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${insightToneClass(tone)}`}>
      {value || 'unknown'}
    </span>
  )
}

function formatObservedAt(value) {
  if (!value) return '관찰 시각 없음'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function summaryValue(section) {
  if (!section.available) return '-'
  return section.summary.finding_count ?? section.findings.length
}

function SectionCard({ section, active }) {
  return (
    <article className={`rounded-lg border bg-white p-4 shadow-sm ${active ? 'border-slate-950 ring-2 ring-slate-100' : 'border-slate-200'}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{section.label}</div>
          <div className="mt-3 text-3xl font-bold text-slate-950">{summaryValue(section)}</div>
          <div className="mt-1 text-xs text-slate-500">findings</div>
        </div>
        <StatusBadge value={section.status} />
      </div>
      <div className="mt-4 space-y-1 text-xs text-slate-500">
        <div className="truncate">source {section.source}</div>
        <div className="truncate">rule {section.ruleVersion}</div>
        <div className="truncate">freshness {section.freshness}</div>
      </div>
    </article>
  )
}

function EvidenceGrid({ finding }) {
  const rows = Object.entries(finding.evidence).slice(0, 12)
  if (!rows.length) return <div className="text-xs text-slate-500">추가 evidence가 없습니다.</div>
  return (
    <dl className="grid gap-2 sm:grid-cols-2">
      {rows.map(([key, value]) => (
        <div key={key} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <dt className="text-xs font-medium text-slate-500">{key}</dt>
          <dd className="mt-1 break-words text-xs font-semibold text-slate-800">
            {typeof value === 'object' ? JSON.stringify(value) : String(value ?? '-')}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function FindingCard({ finding }) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge value={finding.severity} />
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{finding.code}</span>
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-950">{finding.title}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">{finding.message}</p>
        </div>
        <div className="shrink-0 text-xs text-slate-500">{finding.targetType} / {finding.targetId}</div>
      </div>
      <div className="mt-4 grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
        <div className="rounded-md border border-slate-200 px-3 py-2">source <strong className="text-slate-800">{finding.source}</strong></div>
        <div className="rounded-md border border-slate-200 px-3 py-2">freshness <strong className="text-slate-800">{finding.freshness}</strong></div>
        <div className="rounded-md border border-slate-200 px-3 py-2">rule <strong className="text-slate-800">{finding.ruleVersion}</strong></div>
      </div>
      <details className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">Evidence 보기</summary>
        <div className="mt-3"><EvidenceGrid finding={finding} /></div>
      </details>
    </article>
  )
}

function UnavailablePanel({ section }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <div className="font-semibold">{section.label} source unavailable</div>
          <div className="mt-1">{section.unavailableReason || '현재 source를 관찰할 수 없습니다.'}</div>
          <div className="mt-2 text-xs">빈 결과를 정상 상태로 해석하지 않습니다.</div>
        </div>
      </div>
    </div>
  )
}

function EmptyPanel({ section }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
      현재 {section.label} rule에서 보고할 finding이 없습니다. Source {section.source}는 사용 가능하며 관찰 결과는 {section.status}입니다.
    </div>
  )
}

export default function InsightsExplorer({ activeCategory = 'overview' }) {
  const [model, setModel] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setModel(await loadInsightsModel(apiV1Client))
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Insights를 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  const visibleSections = useMemo(() => {
    if (!model) return []
    if (INSIGHT_CATEGORIES.includes(activeCategory)) return [model.sections[activeCategory]]
    return INSIGHT_CATEGORIES.map((category) => model.sections[category])
  }, [activeCategory, model])
  const findings = visibleSections.flatMap((section) => section.findings)

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge value={model?.status || (loading ? 'loading' : 'unavailable')} />
            <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <Eye className="h-3.5 w-3.5" /> observe only
            </span>
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">Operational Insights</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">Risk, readiness, capacity, placement 신호를 source·freshness·rule·evidence와 함께 조회합니다.</p>
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

      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <div className="font-semibold">실행이 닫힌 관찰 경계</div>
            <div className="mt-1">이 화면은 approval, operation, Proxmox mutation을 만들지 않습니다. allowed actions: none</div>
          </div>
        </div>
      </div>

      {model && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {INSIGHT_CATEGORIES.map((category) => (
            <SectionCard key={category} section={model.sections[category]} active={activeCategory === category} />
          ))}
        </div>
      )}

      {model && (
        <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-600 shadow-sm sm:grid-cols-3">
          <div className="flex items-center gap-2"><FileSearch className="h-4 w-4" /> connection {model.connection.state || 'unknown'}</div>
          <div className="flex items-center gap-2"><Clock3 className="h-4 w-4" /> generated {formatObservedAt(model.generatedAt)}</div>
          <div className="flex items-center gap-2"><Eye className="h-4 w-4" /> mode {model.executionMode}</div>
        </div>
      )}

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {loading && !model && <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">Insights를 불러오는 중입니다.</div>}

      {model && visibleSections.map((section) => (
        <div key={section.category} className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-xl font-semibold text-slate-950">{section.label}</h3>
              <p className="mt-1 text-xs text-slate-500">observed {formatObservedAt(section.observedAt)} · {section.source} · {section.ruleVersion}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {section.summary.truncated === true && (
                <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                  {section.summary.returned_finding_count} / {section.summary.finding_count} 표시
                </span>
              )}
              <StatusBadge value={section.status} />
            </div>
          </div>
          {!section.available ? (
            <UnavailablePanel section={section} />
          ) : section.findings.length === 0 ? (
            <EmptyPanel section={section} />
          ) : (
            <div className="space-y-3">
              {section.findings.map((finding) => <FindingCard key={finding.id} finding={finding} />)}
            </div>
          )}
        </div>
      ))}

      {model && findings.length > 0 && <div className="text-right text-xs text-slate-500">현재 보기 {findings.length} findings</div>}
    </section>
  )
}
