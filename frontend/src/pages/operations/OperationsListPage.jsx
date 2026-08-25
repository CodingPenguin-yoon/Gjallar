import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Clock3, List, Plus, RefreshCw } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import { authFailureMessage } from '../../shared/auth/permissions'
import {
  formatOperationTime,
  normalizeOperation,
  OPERATION_STATUSES,
  operationTypeLabel,
} from '../../entities/operation/model'
import OperationStatusBadge from '../../entities/operation/ui/OperationStatusBadge'

export default function OperationsListPage({ canExecute = false }) {
  const [filters, setFilters] = useState({ status: '', operation_type: '' })
  const [operations, setOperations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadOperations = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const items = await apiV1Client.listOperations({ ...filters, limit: 100 })
      setOperations((Array.isArray(items) ? items : []).map(normalizeOperation))
    } catch (err) {
      setError(authFailureMessage(err, 'Operation 목록을 불러오지 못했습니다.'))
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    loadOperations()
  }, [loadOperations])

  const hasFilters = Boolean(filters.status || filters.operation_type)

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Verified operations</div>
          <h2 className="mt-2 text-3xl font-semibold text-slate-950">Operations</h2>
          <p className="mt-1 text-sm text-slate-600">API와 guided manual 작업의 현재 상태와 검증 이력을 함께 확인합니다.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canExecute ? (
            <Link
              to="/operations/guided-qm/vm-unlock"
              className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
            >
              <Plus className="h-4 w-4" />
              Guided qm unlock
            </Link>
          ) : null}
          <button
            type="button"
            onClick={loadOperations}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-2">
        <label className="space-y-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</span>
          <select
            value={filters.status}
            onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            <option value="">All statuses</option>
            {OPERATION_STATUSES.map((status) => <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Type</span>
          <select
            value={filters.operation_type}
            onChange={(event) => setFilters((current) => ({ ...current, operation_type: event.target.value }))}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            <option value="">All types</option>
            <option value="vm_create">Create VM</option>
            <option value="vm_start">VM Start</option>
            <option value="vm_shutdown">VM Shutdown</option>
            <option value="guided_qm_vm_unlock">Guided qm unlock</option>
          </select>
        </label>
      </div>

      {error ? (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <div>{operations.length > 0 ? `새로고침에 실패해 이전 Operation 목록을 표시합니다. ${error}` : error}</div>
            {operations.length === 0 ? (
              <button type="button" onClick={loadOperations} className="mt-2 rounded-md border border-red-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-red-800 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500">
                Retry operations
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {error && operations.length === 0 ? null : <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading && operations.length === 0 ? (
          <div role="status" aria-live="polite" className="p-8 text-center text-sm text-slate-500">Loading operations...</div>
        ) : operations.length === 0 ? (
          <div className="flex flex-col items-center px-6 py-10 text-center">
            <Clock3 className="h-8 w-8 text-slate-300" />
            <h3 className="mt-3 text-base font-semibold text-slate-950">{hasFilters ? '조건에 맞는 Operation이 없습니다' : '아직 기록된 Operation이 없습니다'}</h3>
            <p className="mt-1 max-w-lg text-sm text-slate-500">
              {hasFilters ? '필터를 초기화해 전체 검증 작업을 확인하세요.' : 'Workloads에서 VM 작업을 시작하면 검증 상태와 이력이 여기에 기록됩니다.'}
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {hasFilters ? (
                <button type="button" onClick={() => setFilters({ status: '', operation_type: '' })} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500">
                  필터 초기화
                </button>
              ) : (
                <Link to="/instances" className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500">
                  <List className="h-4 w-4" /> Workloads 보기
                </Link>
              )}
              {!hasFilters && canExecute ? (
                <Link to="/operations/guided-qm/vm-unlock" className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2">
                  <Plus className="h-4 w-4" /> Guided qm unlock
                </Link>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Operation</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Target</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Status</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Mode</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Updated</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {operations.map((operation) => (
                  <tr key={operation.id}>
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-950">{operationTypeLabel(operation.type)}</div>
                      <div className="mt-1 max-w-xs truncate font-mono text-xs text-slate-500" title={operation.id}>{operation.id}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-700">{operation.targetId}</td>
                    <td className="px-4 py-3"><OperationStatusBadge status={operation.status} /></td>
                    <td className="px-4 py-3 text-slate-600">{operation.executionMode}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-600">{formatOperationTime(operation.updatedAt)}</td>
                    <td className="px-4 py-3 text-right">
                      <Link to={`/operations/${encodeURIComponent(operation.id)}`} className="font-semibold text-blue-700 hover:text-blue-900">Open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>}
    </section>
  )
}
