import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardCheck, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import DrsPolicyReviewModal from './DrsPolicyReviewModal'
import { apiV1Client } from '../services/apiV1'
import { authFailureMessage } from '../utils/auth'
import { formatDrsBlocker, loadDrsPolicyCoverage, submitDrsPolicyUpdate } from '../utils/drsAdvisor'

const DRS_POLICY_VALUES = ['unknown', 'allowed', 'restricted', 'blocked']

function policyToneClass(policy) {
  if (policy === 'allowed') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (policy === 'blocked') return 'bg-red-50 text-red-700 border-red-200'
  if (policy === 'restricted') return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-slate-50 text-slate-600 border-slate-200'
}

function identityToneClass(confidence) {
  return confidence === 'high'
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : 'bg-amber-50 text-amber-700 border-amber-200'
}

function compactBlockers(blockers = [], limit = 2) {
  const visible = blockers.slice(0, limit).map(formatDrsBlocker)
  const hiddenCount = blockers.length - visible.length
  return hiddenCount > 0 ? `${visible.join(', ')} +${hiddenCount}` : visible.join(', ')
}

function locationText(item) {
  const locator = item?.currentLocator || {}
  return `${locator.nodeId || '-'} / VMID ${locator.vmid ?? '-'}`
}

function itemName(item) {
  return item?.currentLocator?.name || item?.vmIdentityId || 'unknown VM'
}

function canSelectPolicyItem(item, canManageDrsPolicies) {
  return Boolean(canManageDrsPolicies && item?.policyWriteAllowed)
}

function policyReviewDisabledReason(item, canManageDrsPolicies, saving) {
  if (!item) return 'No DRS policy item is available.'
  if (!canManageDrsPolicies) return 'DRS policy updates require operator or admin role.'
  if (!item.policyWriteAllowed) {
    const blockerText = compactBlockers(item.policyWriteBlockers || [])
    return blockerText ? `DRS policy write blocked: ${blockerText}.` : 'DRS policy write is blocked for this VM identity.'
  }
  if (saving) return 'Saving DRS policy.'
  return ''
}

function CountTile({ label, value, tone = 'slate' }) {
  const toneClass = tone === 'green'
    ? 'text-emerald-700'
    : tone === 'red'
      ? 'text-red-700'
      : tone === 'yellow'
        ? 'text-amber-700'
        : 'text-slate-950'
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-2xl font-bold ${toneClass}`}>{value}</div>
    </div>
  )
}

function StatusPill({ children, className }) {
  return (
    <span className={`inline-flex max-w-full rounded-full border px-2.5 py-1 text-xs font-semibold ${className}`}>
      <span className="truncate">{children}</span>
    </span>
  )
}

function BulkDrsPolicyModal({ items, saving, error, onCancel, onSubmit }) {
  const [policy, setPolicy] = useState('unknown')
  const [reason, setReason] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const reasonRequired = policy !== 'unknown'
  const reasonReady = !reasonRequired || reason.trim().length > 0
  const canSubmit = items.length > 0 && acknowledged && reasonReady && !saving
  const visibleNames = items.slice(0, 5).map(itemName)
  const hiddenCount = items.length - visibleNames.length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
      <div className="max-h-[90vh] w-full max-w-xl overflow-auto rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="border-b border-slate-200 px-5 py-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Bulk DRS Policy Change</h3>
              <div className="mt-1 text-xs text-slate-500">{items.length} selected VM{items.length === 1 ? '' : 's'}</div>
            </div>
            <StatusPill className="border-blue-200 bg-blue-50 text-blue-700">bulk edit</StatusPill>
          </div>
        </div>

        <div className="space-y-4 p-5">
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
            Policy changes do not start migration, approve migration, or write Proxmox tags. Allowed is only a prerequisite for later DRS review.
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected VMs</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {visibleNames.map((name) => (
                <span key={name} className="max-w-full truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                  {name}
                </span>
              ))}
              {hiddenCount > 0 ? (
                <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">+{hiddenCount} more</span>
              ) : null}
            </div>
          </div>

          <label className="block text-sm font-semibold text-slate-800">
            Policy
            <select
              value={policy}
              onChange={(event) => setPolicy(event.target.value)}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
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
              disabled={saving}
              rows={3}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
            />
          </label>

          <label className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              disabled={saving}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 disabled:cursor-not-allowed"
            />
            <span>I reviewed the selected VM observation guards and understand this only changes the Gjallar DRS prerequisite policy.</span>
          </label>

          {reasonRequired && !reasonReady ? (
            <div className="text-xs font-semibold text-amber-700">A reason is required for allowed, restricted, or blocked.</div>
          ) : null}

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
          ) : null}
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
            onClick={() => onSubmit({ policy, reason, acknowledged })}
            disabled={!canSubmit}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-300 bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            <ClipboardCheck className="h-4 w-4" />
            {saving ? 'Saving policies' : 'Save policies'}
          </button>
        </div>
      </div>
    </div>
  )
}

function DrsPoliciesScreen({ currentUser = null, canManageDrsPolicies = false }) {
  const [coverage, setCoverage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reviewItem, setReviewItem] = useState(null)
  const [savingId, setSavingId] = useState(null)
  const [policyError, setPolicyError] = useState('')
  const [policyResult, setPolicyResult] = useState(null)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkError, setBulkError] = useState('')

  const loadPolicies = async ({ initial = false } = {}) => {
    if (initial) setLoading(true)
    setRefreshing(true)
    setError('')
    try {
      const nextCoverage = await loadDrsPolicyCoverage(apiV1Client)
      setCoverage(nextCoverage)
    } catch (nextError) {
      const message = nextError?.message || 'Unable to load DRS policies'
      setError(message)
      setCoverage(null)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadPolicies({ initial: true })
  }, [])

  const items = coverage?.items || []
  const summary = coverage?.coverage || {}
  const selectableItems = items.filter((item) => canSelectPolicyItem(item, canManageDrsPolicies))
  const selectedItems = items.filter((item) => selectedIds.has(item.vmIdentityId) && canSelectPolicyItem(item, canManageDrsPolicies))
  const allSelectableChecked = selectableItems.length > 0 && selectableItems.every((item) => selectedIds.has(item.vmIdentityId))

  useEffect(() => {
    setSelectedIds((previousIds) => {
      const selectableIds = new Set(selectableItems.map((item) => item.vmIdentityId))
      const nextIds = new Set([...previousIds].filter((id) => selectableIds.has(id)))
      const unchanged = nextIds.size === previousIds.size && [...previousIds].every((id) => nextIds.has(id))
      return unchanged ? previousIds : nextIds
    })
  }, [items, canManageDrsPolicies])

  const openReview = (item) => {
    const disabledReason = policyReviewDisabledReason(item, canManageDrsPolicies, savingId === item?.vmIdentityId || bulkSaving)
    if (disabledReason) return
    setReviewItem(item)
    setPolicyError('')
    setPolicyResult(null)
    setNotice('')
  }

  const closeReview = () => {
    if (savingId || bulkSaving) return
    setReviewItem(null)
    setPolicyError('')
  }

  const submitReview = async (item, { policy, reason, acknowledged }) => {
    if (!canManageDrsPolicies || !item?.policyWriteAllowed || savingId || bulkSaving) return
    setSavingId(item.vmIdentityId)
    setPolicyError('')
    setNotice('')
    try {
      const result = await submitDrsPolicyUpdate(apiV1Client, item.vmIdentityId, {
        policy,
        reason,
        policyChangeAcknowledged: acknowledged,
        expectedObservation: item.expectedObservationPayload,
      })
      setPolicyResult(result)
      setReviewItem(null)
      setNotice(`DRS policy saved for ${item.currentLocator?.name || item.vmIdentityId}; migration approval remains separate.`)
      await loadPolicies()
    } catch (nextError) {
      setPolicyError(authFailureMessage(nextError, 'Unable to update DRS policy'))
    } finally {
      setSavingId(null)
    }
  }

  const toggleSelectedItem = (item) => {
    if (!canSelectPolicyItem(item, canManageDrsPolicies) || bulkSaving) return
    setBulkError('')
    setPolicyError('')
    setSelectedIds((previousIds) => {
      const nextIds = new Set(previousIds)
      if (nextIds.has(item.vmIdentityId)) {
        nextIds.delete(item.vmIdentityId)
      } else {
        nextIds.add(item.vmIdentityId)
      }
      return nextIds
    })
  }

  const toggleAllSelected = () => {
    if (!canManageDrsPolicies || bulkSaving || selectableItems.length === 0) return
    setBulkError('')
    setPolicyError('')
    setSelectedIds((previousIds) => {
      if (allSelectableChecked) {
        return new Set([...previousIds].filter((id) => !selectableItems.some((item) => item.vmIdentityId === id)))
      }
      return new Set([...previousIds, ...selectableItems.map((item) => item.vmIdentityId)])
    })
  }

  const clearSelection = () => {
    if (bulkSaving) return
    setSelectedIds(new Set())
    setBulkError('')
  }

  const openBulkReview = () => {
    if (!canManageDrsPolicies || selectedItems.length === 0 || bulkSaving) return
    setBulkOpen(true)
    setBulkError('')
    setPolicyError('')
    setPolicyResult(null)
    setNotice('')
  }

  const closeBulkReview = () => {
    if (bulkSaving) return
    setBulkOpen(false)
    setBulkError('')
  }

  const submitBulkReview = async ({ policy, reason, acknowledged }) => {
    const pendingItems = selectedItems
    const reasonRequired = policy !== 'unknown'
    if (!canManageDrsPolicies || bulkSaving || pendingItems.length === 0 || !acknowledged || (reasonRequired && !reason.trim())) return
    setBulkSaving(true)
    setBulkError('')
    setPolicyError('')
    setNotice('')
    const successes = []
    const failures = []

    for (const item of pendingItems) {
      try {
        await submitDrsPolicyUpdate(apiV1Client, item.vmIdentityId, {
          policy,
          reason,
          policyChangeAcknowledged: acknowledged,
          expectedObservation: item.expectedObservationPayload,
        })
        successes.push(item)
      } catch (nextError) {
        failures.push({
          item,
          message: authFailureMessage(nextError, 'Unable to update DRS policy'),
        })
      }
    }

    await loadPolicies()

    setSelectedIds(new Set(failures.map(({ item }) => item.vmIdentityId)))

    if (failures.length > 0) {
      const failedText = failures
        .slice(0, 3)
        .map(({ item, message }) => `${itemName(item)}: ${message}`)
        .join('; ')
      const hiddenText = failures.length > 3 ? `; +${failures.length - 3} more` : ''
      const nextError = `Bulk DRS policy update failed for ${failures.length} of ${pendingItems.length}: ${failedText}${hiddenText}`
      setBulkError(nextError)
      setPolicyError(nextError)
      if (successes.length > 0) {
        setNotice(`DRS policy saved for ${successes.length} selected VM${successes.length === 1 ? '' : 's'}; migration approval remains separate.`)
      }
    } else {
      setBulkOpen(false)
      setNotice(`DRS policy saved for ${successes.length} selected VM${successes.length === 1 ? '' : 's'}; migration approval remains separate.`)
    }

    setBulkSaving(false)
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-slate-200 bg-white">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-blue-600" />
        <span className="text-sm text-slate-600">Loading DRS Policies...</span>
      </div>
    )
  }

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-blue-50 p-3 text-blue-700">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-2xl font-semibold text-slate-950">DRS Policies</h2>
            <p className="mt-1 text-sm text-slate-600">Review VM migration policy coverage</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => loadPolicies()}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {!canManageDrsPolicies ? (
        <div className="border-b border-yellow-100 bg-yellow-50 px-6 py-3 text-sm text-yellow-800">
          DRS policy review is visible, but updates require operator or admin role. Current role: {currentUser?.role || 'unknown'}.
        </div>
      ) : null}

      {error ? (
        <div className="border-b border-red-100 bg-red-50 px-6 py-4">
          <div className="flex items-start gap-3 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <div>{error}</div>
          </div>
        </div>
      ) : null}

      {policyError && !reviewItem ? (
        <div className="border-b border-red-100 bg-red-50 px-6 py-3 text-sm text-red-800">
          {policyError}
        </div>
      ) : null}

      {notice && !reviewItem ? (
        <div className="border-b border-emerald-100 bg-emerald-50 px-6 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      ) : null}

      <div className="space-y-5 px-6 py-5">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          <CountTile label="VMs" value={summary.totalNonTemplateVms ?? items.length} />
          <CountTile label="Allowed" value={summary.allowedCount ?? 0} tone="green" />
          <CountTile label="Unknown" value={summary.unknownCount ?? 0} tone="yellow" />
          <CountTile label="Restricted" value={summary.restrictedCount ?? 0} tone="yellow" />
          <CountTile label="Blocked" value={summary.blockedCount ?? 0} tone="red" />
          <CountTile label="Writable" value={summary.writeAllowedCount ?? 0} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="min-w-0 text-sm text-slate-700">
            <span className="font-semibold text-slate-950">{selectedItems.length}</span> selected
            <span className="mx-2 text-slate-300">|</span>
            <span>{selectableItems.length} writable VM{selectableItems.length === 1 ? '' : 's'}</span>
            {!canManageDrsPolicies ? (
              <span className="ml-2 text-slate-500">Selection requires operator or admin role.</span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={clearSelection}
              disabled={selectedItems.length === 0 || bulkSaving}
              className="inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={openBulkReview}
              disabled={!canManageDrsPolicies || selectedItems.length === 0 || bulkSaving}
              aria-label="Open bulk DRS policy update"
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-300 bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <ClipboardCheck className="h-4 w-4" />
              Bulk update
            </button>
          </div>
        </div>

        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            No DRS policy coverage is available.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[84rem] w-full table-fixed divide-y divide-slate-200 text-sm">
              <colgroup>
                <col className="w-[4%] min-w-[4rem]" />
                <col className="w-[17%] min-w-[14rem]" />
                <col className="w-[11%] min-w-[8rem]" />
                <col className="w-[13%] min-w-[9rem]" />
                <col className="w-[18%] min-w-[14rem]" />
                <col className="w-[19%] min-w-[16rem]" />
                <col className="w-[10%] min-w-[8rem]" />
                <col className="w-[8%] min-w-[7rem]" />
              </colgroup>
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3 text-center font-medium">
                    <input
                      type="checkbox"
                      checked={allSelectableChecked}
                      onChange={toggleAllSelected}
                      disabled={!canManageDrsPolicies || selectableItems.length === 0 || bulkSaving}
                      aria-label="Select all writable DRS policy rows"
                      title={canManageDrsPolicies ? 'Select all writable DRS policy rows' : 'DRS policy updates require operator or admin role.'}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
                    />
                  </th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">VM</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Policy</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Identity</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Observation guard</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Policy blockers</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Write state</th>
                  <th scope="col" className="px-4 py-3 text-center font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {items.map((item) => {
                  const policy = item.policy?.value || 'unknown'
                  const disabledReason = policyReviewDisabledReason(item, canManageDrsPolicies, savingId === item.vmIdentityId || bulkSaving)
                  const blockerText = compactBlockers([
                    ...(item.policyWriteBlockers || []),
                    ...(item.drsBlockerImpact?.policyBlockers || []),
                  ], 4)
                  const selectable = canSelectPolicyItem(item, canManageDrsPolicies)
                  const checked = selectable && selectedIds.has(item.vmIdentityId)
                  const selectionTitle = selectable
                    ? `Select ${itemName(item)} for bulk DRS policy update`
                    : disabledReason || 'DRS policy write is blocked for this VM identity.'
                  return (
                    <tr key={item.vmIdentityId} className="align-top hover:bg-slate-50">
                      <td className="px-4 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleSelectedItem(item)}
                          disabled={!selectable || bulkSaving}
                          aria-label={`Select ${itemName(item)} for bulk DRS policy update`}
                          title={selectionTitle}
                          className="h-4 w-4 rounded border-slate-300 text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="truncate font-semibold text-slate-950" title={item.currentLocator?.name}>{itemName(item)}</div>
                        <div className="mt-0.5 truncate font-mono text-xs text-slate-500" title={item.vmIdentityId}>{item.vmIdentityId}</div>
                        <div className="mt-1 text-xs text-slate-500">{locationText(item)}</div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill className={policyToneClass(policy)}>{policy}</StatusPill>
                        <div className="mt-1 truncate text-xs text-slate-500" title={item.policy?.reason || 'not recorded'}>{item.policy?.reason || 'not recorded'}</div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill className={identityToneClass(item.identityConfidence)}>{item.identityConfidence}</StatusPill>
                        <div className="mt-1 truncate text-xs text-slate-500">{item.identityStatus}</div>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-600">
                        <div className="truncate" title={item.expectedObservation?.observedAt || '-'}>{item.expectedObservation?.observedAt || '-'}</div>
                        <div className="mt-1 truncate font-mono text-[11px] text-slate-500" title={item.expectedObservation?.fingerprintHash || '-'}>
                          {item.expectedObservation?.fingerprintHash || '-'}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-600">
                        {blockerText ? (
                          <div className="truncate" title={blockerText}>{blockerText}</div>
                        ) : (
                          <div className="inline-flex items-center gap-1.5 text-emerald-700">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            none
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill className={item.policyWriteAllowed ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}>
                          {item.policyWriteAllowed ? 'write allowed' : 'write blocked'}
                        </StatusPill>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          type="button"
                          onClick={() => openReview(item)}
                          disabled={Boolean(disabledReason)}
                          aria-label={`Review DRS policy for ${item.currentLocator?.name || item.vmIdentityId}`}
                          title={disabledReason || `Review DRS policy for ${item.currentLocator?.name || item.vmIdentityId}`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:border-blue-300 hover:bg-blue-100 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-50 disabled:text-slate-400"
                        >
                          <ClipboardCheck className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {reviewItem ? (
        <DrsPolicyReviewModal
          key={reviewItem.vmIdentityId}
          item={reviewItem}
          saving={savingId === reviewItem.vmIdentityId}
          error={policyError}
          result={policyResult}
          onCancel={closeReview}
          onSubmit={submitReview}
        />
      ) : null}

      {bulkOpen ? (
        <BulkDrsPolicyModal
          items={selectedItems}
          saving={bulkSaving}
          error={bulkError}
          onCancel={closeBulkReview}
          onSubmit={submitBulkReview}
        />
      ) : null}
    </section>
  )
}

export default DrsPoliciesScreen
