import { useState } from 'react'
import { ClipboardCheck } from 'lucide-react'
import { drsToneClass, formatDrsBlocker } from '../utils/drsAdvisor'

const DRS_POLICY_VALUES = ['unknown', 'allowed', 'restricted', 'blocked']

function drsPolicyValueTone(value) {
  if (value === 'allowed') return 'green'
  if (value === 'blocked') return 'red'
  if (value === 'restricted') return 'yellow'
  return 'yellow'
}

function drsPolicyLocation(item) {
  const locator = item?.currentLocator || {}
  return `${locator.nodeId || '-'} / VMID ${locator.vmid ?? '-'}`
}

function StatusPill({ children, tone = 'slate' }) {
  return (
    <span className={`inline-flex min-w-0 max-w-full items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${drsToneClass(tone)}`}>
      <span className="truncate">{children}</span>
    </span>
  )
}

function DetailStatusRow({ label, value, tone }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs">
      <span className="shrink-0 text-slate-500">{label}</span>
      {tone ? (
        <StatusPill tone={tone}>{value}</StatusPill>
      ) : (
        <span className="min-w-0 truncate text-right font-semibold text-slate-800">{value}</span>
      )}
    </div>
  )
}

function CompactBlockerList({ blockers }) {
  if (!blockers.length) {
    return <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">none</span>
  }
  const visibleBlockers = blockers.slice(0, 4)
  const hiddenCount = blockers.length - visibleBlockers.length
  return (
    <div className="flex flex-wrap gap-1.5">
      {visibleBlockers.map((blocker) => (
        <span key={blocker} className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">
          {formatDrsBlocker(blocker)}
        </span>
      ))}
      {hiddenCount > 0 && (
        <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600">+{hiddenCount} more</span>
      )}
    </div>
  )
}

function DrsPolicyReviewModal({ item, saving, error, result, onCancel, onSubmit }) {
  const [policy, setPolicy] = useState(item?.policy?.value || 'unknown')
  const [reason, setReason] = useState(item?.policy?.reason || '')
  const [acknowledged, setAcknowledged] = useState(false)
  if (!item) return null
  const reasonRequired = policy !== 'unknown'
  const reasonReady = !reasonRequired || reason.trim().length > 0
  const canSubmit = item.policyWriteAllowed && acknowledged && reasonReady && !saving
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="border-b border-slate-200 px-5 py-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Review DRS Policy Change</h3>
              <div className="mt-1 text-xs text-slate-500">{item.currentLocator.name} - {drsPolicyLocation(item)}</div>
            </div>
            <StatusPill tone={item.policyWriteAllowed ? 'green' : 'yellow'}>{item.policyWriteAllowed ? 'write allowed' : 'write blocked'}</StatusPill>
          </div>
        </div>
        <div className="space-y-4 p-5">
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
            Policy changes do not start migration, approve migration, or write Proxmox tags. Allowed is only a prerequisite for later DRS review.
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <DetailStatusRow label="Current policy" value={item.policy.value} tone={drsPolicyValueTone(item.policy.value)} />
            <DetailStatusRow label="Identity confidence" value={item.identityConfidence} tone={item.identityConfidence === 'high' ? 'green' : 'yellow'} />
            <DetailStatusRow label="Observed" value={item.expectedObservation.observedAt || '-'} />
            <DetailStatusRow label="Fingerprint" value={item.expectedObservation.fingerprintHash || '-'} />
          </div>
          {item.policyWriteBlockers.length > 0 && <CompactBlockerList blockers={item.policyWriteBlockers} />}
          <label className="block text-sm font-semibold text-slate-800">
            Policy
            <select
              value={policy}
              onChange={(event) => setPolicy(event.target.value)}
              disabled={saving || !item.policyWriteAllowed}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
            >
              {DRS_POLICY_VALUES.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-semibold text-slate-800">
            Reason
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={saving || !item.policyWriteAllowed}
              rows={3}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              disabled={saving || !item.policyWriteAllowed}
              className="mt-1"
            />
            <span>I reviewed the latest observation guard and understand this only changes the Gjallar DRS prerequisite policy.</span>
          </label>
          {reasonRequired && !reasonReady && <div className="text-xs font-semibold text-amber-700">A reason is required for allowed, restricted, or blocked.</div>}
          {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
          {result && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
              Policy audit {result.auditEventId || 'no-op'} - {result.newPolicy.value}
            </div>
          )}
        </div>
        <div className="flex flex-col-reverse gap-2 border-t border-slate-200 px-5 py-4 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onSubmit(item, { policy, reason, acknowledged })}
            disabled={!canSubmit}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-300 bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            <ClipboardCheck className="h-4 w-4" />
            {saving ? 'Saving policy' : 'Save policy'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default DrsPolicyReviewModal
