import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Clock3, Eye, FileSearch, RefreshCw, ShieldCheck } from 'lucide-react'
import {
  INSIGHT_CATEGORIES,
  insightSectionCoverageComplete,
  insightStatusTone,
  insightToneClass,
} from '../../entities/insight/model'
import { apiV1Client } from '../../shared/api/apiV1'
import { insightCategoryPath, vmDetailPathFromTarget } from '../../shared/navigation/targetPaths'
import { loadInsightsModel, selectExactTargetFindingView } from './model'

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

function SectionCard({ section }) {
  return (
    <Link
      to={insightCategoryPath(section.category)}
      className="min-h-28 rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-400 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2"
      aria-label={`${section.label} findings ${summaryValue(section)}`}
    >
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
    </Link>
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
  const targetPath = vmDetailPathFromTarget(finding.targetType, finding.targetId)
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
        {targetPath ? (
          <Link to={targetPath} className="shrink-0 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 font-mono text-xs font-semibold text-blue-800 hover:bg-blue-100">
            {finding.targetType} / {finding.targetId} · VM 열기
          </Link>
        ) : (
          <div className="shrink-0 text-xs text-slate-500">{finding.targetType} / {finding.targetId}</div>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>source <strong className="text-slate-700">{finding.source}</strong></span>
        <span>freshness <strong className="text-slate-700">{finding.freshness}</strong></span>
        <span>rule <strong className="text-slate-700">{finding.ruleVersion}</strong></span>
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

function TargetEmptyPanel({ section, targetType, targetId }) {
  const coverageComplete = insightSectionCoverageComplete(section)
  if (!coverageComplete) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
        {section.label} coverage가 unknown, partial, stale 또는 truncated 상태이므로 exact target {targetType} / {targetId}의 finding 부재를 확정할 수 없습니다.
      </div>
    )
  }
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
      사용 가능한 {section.label} 응답에서 exact target {targetType} / {targetId}와 일치하는 finding이 없습니다.
    </div>
  )
}

export default function InsightsExplorer({ activeCategory = 'overview' }) {
  const [searchParams] = useSearchParams()
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
  const targetType = String(searchParams.get('target_type') || '').trim()
  const targetId = String(searchParams.get('target_id') || '').trim()
  const findingId = String(searchParams.get('finding') || '').trim()
  const hasExactTarget = Boolean(targetType && targetId)
  const findingView = useMemo(() => selectExactTargetFindingView(visibleSections, {
    targetType: hasExactTarget ? targetType : '',
    targetId: hasExactTarget ? targetId : '',
    findingId,
  }), [findingId, hasExactTarget, targetId, targetType, visibleSections])
  const filteredSections = findingView.sections
  const findings = filteredSections.flatMap((section) => section.findings)
  const renderedFindingCount = activeCategory === 'overview'
    ? filteredSections.reduce((total, section) => total + Math.min(section.findings.length, 2), 0)
    : findings.length

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
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">운영 상태 진단</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">위험, VM 준비 상태, 가용 용량과 배치를 관찰 근거와 함께 확인합니다.</p>
        </div>
        <button
          type="button"
          onClick={loadModel}
          disabled={loading}
          className="inline-flex w-fit items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          새로고침
        </button>
      </header>

      {activeCategory === 'overview' ? (
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <div className="font-semibold">관찰된 상태를 바탕으로 진단합니다</div>
            <div className="mt-1">관찰 시각과 근거를 확인하세요. 필요한 VM 작업은 해당 VM 상세에서 시작할 수 있습니다.</div>
          </div>
        </div>
      </div>
      ) : null}

      {model && activeCategory === 'overview' && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {INSIGHT_CATEGORIES.map((category) => (
            <SectionCard key={category} section={model.sections[category]} />
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

      {model && hasExactTarget ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
          <div>
            Exact target context: <span className="font-mono font-semibold">{targetType} / {targetId}</span>
            {findingId ? <span> · finding <span className="font-mono">{findingId}</span></span> : null}
          </div>
          <Link to={insightCategoryPath(activeCategory)} className="font-semibold underline">target filter 해제</Link>
        </div>
      ) : null}

      {model && hasExactTarget && findingId && !findingView.requestedFindingMatched ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          요청한 finding은 현재 반환된 응답에 없습니다. coverage가 불완전하면 소멸을 확정하지 않으며, 현재 반환된 exact-target finding을 대신 표시합니다.
        </div>
      ) : null}

      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{model ? `새로고침에 실패해 이전 관찰 결과를 표시합니다. ${error}` : error}</div>}
      {loading && !model && <div role="status" aria-live="polite" className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">Insights를 불러오는 중입니다.</div>}

      {model && filteredSections.map((section) => {
        const displayedFindings = activeCategory === 'overview' ? section.findings.slice(0, 2) : section.findings
        return <div key={section.category} className="space-y-3">
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
              {activeCategory === 'overview' && section.findings.length > 0 ? (
                <Link to={insightCategoryPath(section.category)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500">
                  전체 {section.findings.length}건 보기
                </Link>
              ) : null}
            </div>
          </div>
          {!section.available ? (
            <UnavailablePanel section={section} />
          ) : section.findings.length === 0 ? (
            hasExactTarget
              ? <TargetEmptyPanel section={section} targetType={targetType} targetId={targetId} />
              : <EmptyPanel section={section} />
          ) : (
            <div className="space-y-3">
              {displayedFindings.map((finding) => <FindingCard key={finding.id} finding={finding} />)}
            </div>
          )}
        </div>
      })}

      {model && findings.length > 0 && <div className="text-right text-xs text-slate-500">현재 보기 {renderedFindingCount} / 전체 {findings.length} findings</div>}
    </section>
  )
}
