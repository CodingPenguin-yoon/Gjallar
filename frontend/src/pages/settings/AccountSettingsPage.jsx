import { useState } from 'react'
import { AlertTriangle, CheckCircle2, KeyRound, UserCircle } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import { authFailureMessage } from '../../shared/auth/permissions'

export default function AccountSettingsScreen({ currentUser, onPasswordChanged }) {
  const [form, setForm] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const submitPasswordChange = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    if (form.newPassword !== form.confirmPassword) {
      setError('새 비밀번호 확인이 일치하지 않습니다.')
      return
    }
    setSubmitting(true)
    try {
      const response = await apiV1Client.changePassword(form.currentPassword, form.newPassword)
      setForm({ currentPassword: '', newPassword: '', confirmPassword: '' })
      setNotice(`비밀번호를 변경했습니다. 다른 세션 ${response.revoked_sessions || 0}개를 해지했습니다.`)
      if (typeof onPasswordChanged === 'function') await onPasswordChanged()
    } catch (err) {
      setError(authFailureMessage(err, '비밀번호를 변경하지 못했습니다.'))
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = form.currentPassword && form.newPassword && form.confirmPassword && !submitting

  return (
    <section className="mx-auto max-w-2xl space-y-5">
      <header>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <UserCircle className="h-4 w-4" />
          Account
        </div>
        <h2 className="mt-3 text-3xl font-semibold text-slate-950">{currentUser?.username}</h2>
        <p className="mt-2 text-sm text-slate-600">
          현재 역할 <span className="font-semibold text-slate-800">{currentUser?.role}</span> · 비밀번호를 변경하고 다른 로그인 세션을 안전하게 해지합니다.
        </p>
      </header>

      <form className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" onSubmit={submitPasswordChange}>
        <div className="mb-4 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-slate-600" />
          <h3 className="text-sm font-semibold text-slate-950">Change Password</h3>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium text-slate-700">Current password</span>
            <input
              aria-label="Current password"
              type="password"
              autoComplete="current-password"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus-visible:border-slate-500 focus-visible:ring-2 focus-visible:ring-slate-100"
              value={form.currentPassword}
              onChange={(event) => updateField('currentPassword', event.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-slate-700">New password</span>
            <input
              aria-label="New password"
              type="password"
              autoComplete="new-password"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus-visible:border-slate-500 focus-visible:ring-2 focus-visible:ring-slate-100"
              value={form.newPassword}
              onChange={(event) => updateField('newPassword', event.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-slate-700">Confirm new password</span>
            <input
              aria-label="Confirm new password"
              type="password"
              autoComplete="new-password"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus-visible:border-slate-500 focus-visible:ring-2 focus-visible:ring-slate-100"
              value={form.confirmPassword}
              onChange={(event) => updateField('confirmPassword', event.target.value)}
            />
          </label>
        </div>
        {error ? (
          <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
        {notice ? (
          <div role="status" aria-live="polite" className="mt-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{notice}</span>
          </div>
        ) : null}
        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <KeyRound className="h-4 w-4" />
          {submitting ? 'Changing...' : 'Change password'}
        </button>
      </form>
    </section>
  )
}
