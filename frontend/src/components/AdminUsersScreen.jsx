import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Ban, CheckCircle2, KeyRound, Loader2, RefreshCw, ShieldCheck, UserPlus, Users } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { authFailureMessage } from '../utils/auth'

const ROLE_OPTIONS = ['viewer', 'operator', 'admin']

function formatTimestamp(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function StatusPill({ enabled }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
      {enabled ? 'Enabled' : 'Disabled'}
    </span>
  )
}

function RolePill({ role }) {
  const tone = role === 'admin'
    ? 'border-blue-200 bg-blue-50 text-blue-700'
    : role === 'operator'
      ? 'border-amber-200 bg-amber-50 text-amber-700'
      : 'border-slate-200 bg-slate-50 text-slate-600'
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold uppercase ${tone}`}>{role}</span>
}

function SessionStatusPill({ status, isCurrent }) {
  const normalized = String(status || '').toLowerCase()
  const tone = normalized === 'active'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : normalized === 'revoked'
      ? 'border-red-200 bg-red-50 text-red-700'
      : 'border-amber-200 bg-amber-50 text-amber-800'
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold uppercase ${tone}`}>
      {isCurrent ? 'Current ' : ''}{normalized || 'unknown'}
    </span>
  )
}

function userSortKey(user) {
  return `${user.enabled === false ? '1' : '0'}:${user.username || ''}`
}

function compareSessions(left, right) {
  if (left.is_current_session !== right.is_current_session) return left.is_current_session ? -1 : 1
  const statusOrder = { active: 0, expired: 1, revoked: 2 }
  const leftStatus = statusOrder[String(left.status || '').toLowerCase()] ?? 9
  const rightStatus = statusOrder[String(right.status || '').toLowerCase()] ?? 9
  if (leftStatus !== rightStatus) return leftStatus - rightStatus
  const leftCreated = new Date(left.created_at || 0).getTime()
  const rightCreated = new Date(right.created_at || 0).getTime()
  if (leftCreated !== rightCreated) return rightCreated - leftCreated
  return String(left.session_id || '').localeCompare(String(right.session_id || ''))
}

function AdminUsersScreen({ currentUser = null, onCurrentUserChanged = null }) {
  const [users, setUsers] = useState([])
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyKey, setBusyKey] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [createForm, setCreateForm] = useState({ username: '', password: '', role: 'viewer' })
  const [resetPasswords, setResetPasswords] = useState({})

  const sortedUsers = useMemo(
    () => [...users].sort((left, right) => userSortKey(left).localeCompare(userSortKey(right))),
    [users],
  )
  const sortedSessions = useMemo(() => [...sessions].sort(compareSessions), [sessions])

  const loadUsers = async () => {
    setLoading(true)
    setError('')
    try {
      const [userResponse, sessionResponse] = await Promise.all([
        apiV1Client.listAdminUsers(),
        apiV1Client.listAdminSessions(),
      ])
      setUsers(Array.isArray(userResponse) ? userResponse : [])
      setSessions(Array.isArray(sessionResponse) ? sessionResponse : [])
    } catch (err) {
      setError(authFailureMessage(err, '관리 데이터를 불러오지 못했습니다.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const refreshIfCurrentUserChanged = async (username) => {
    if (username !== currentUser?.username) return false
    if (typeof onCurrentUserChanged === 'function') {
      await onCurrentUserChanged()
      return true
    }
    return false
  }

  const runAction = async ({ key, successMessage, username = '', action }) => {
    setBusyKey(key)
    setError('')
    setNotice('')
    try {
      const result = await action()
      setNotice(successMessage)
      const currentUserChanged = result?.current_session_revoked
        ? await refreshIfCurrentUserChanged(currentUser?.username)
        : await refreshIfCurrentUserChanged(username)
      if (!currentUserChanged) await loadUsers()
    } catch (err) {
      setError(authFailureMessage(err, '사용자 작업을 처리하지 못했습니다.'))
    } finally {
      setBusyKey('')
    }
  }

  const handleCreate = async (event) => {
    event.preventDefault()
    await runAction({
      key: 'create',
      successMessage: `${createForm.username} 계정을 만들었습니다.`,
      action: async () => {
        await apiV1Client.createAdminUser(createForm)
        setCreateForm({ username: '', password: '', role: 'viewer' })
      },
    })
  }

  const handleRoleChange = async (username, role) => {
    await runAction({
      key: `role:${username}`,
      username,
      successMessage: `${username} 역할을 ${role}(으)로 변경했습니다.`,
      action: () => apiV1Client.setAdminUserRole(username, role),
    })
  }

  const handleDisable = async (username) => {
    await runAction({
      key: `disable:${username}`,
      username,
      successMessage: `${username} 계정을 비활성화했습니다.`,
      action: () => apiV1Client.disableAdminUser(username),
    })
  }

  const handleResetPassword = async (event, username) => {
    event.preventDefault()
    const password = resetPasswords[username] || ''
    await runAction({
      key: `reset:${username}`,
      username,
      successMessage: `${username} 비밀번호를 재설정했습니다.`,
      action: async () => {
        await apiV1Client.resetAdminUserPassword(username, password)
        setResetPasswords((current) => ({ ...current, [username]: '' }))
      },
    })
  }

  const handleRevokeSession = async (session) => {
    await runAction({
      key: `session:${session.session_id}`,
      successMessage: session.is_current_session ? '현재 세션을 해지했습니다.' : `${session.username} 세션을 해지했습니다.`,
      action: () => apiV1Client.revokeAdminSession(session.session_id),
    })
  }

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            <ShieldCheck className="h-4 w-4" />
            Admin
          </div>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">User Management</h2>
        </div>
        <button type="button" onClick={loadUsers} disabled={loading} className="inline-flex w-fit items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{notice}</span>
        </div>
      )}

      <form className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" onSubmit={handleCreate}>
        <div className="mb-4 flex items-center gap-2">
          <UserPlus className="h-4 w-4 text-slate-600" />
          <h3 className="text-sm font-semibold text-slate-950">Create User</h3>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_12rem_auto] md:items-end">
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Username</span>
            <input
              aria-label="Create username"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={createForm.username}
              onChange={(event) => setCreateForm((current) => ({ ...current, username: event.target.value }))}
              autoComplete="off"
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Password</span>
            <input
              aria-label="Create password"
              type="password"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={createForm.password}
              onChange={(event) => setCreateForm((current) => ({ ...current, password: event.target.value }))}
              autoComplete="new-password"
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-medium text-slate-700">Role</span>
            <select
              aria-label="Create role"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={createForm.role}
              onChange={(event) => setCreateForm((current) => ({ ...current, role: event.target.value }))}
            >
              {ROLE_OPTIONS.map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
          </label>
          <button type="submit" disabled={busyKey === 'create' || !createForm.username || !createForm.password} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60">
            {busyKey === 'create' ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            Create
          </button>
        </div>
      </form>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-slate-600" />
            <h3 className="text-sm font-semibold text-slate-950">Local Users</h3>
          </div>
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{sortedUsers.length} users</span>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
            <colgroup>
              <col className="w-[14rem]" />
              <col className="w-[8rem]" />
              <col className="w-[8rem]" />
              <col className="w-[12rem]" />
              <col className="w-[12rem]" />
              <col className="w-[12rem]" />
              <col className="w-[18rem]" />
            </colgroup>
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">Username</th>
                <th className="px-4 py-3 text-left font-semibold">Role</th>
                <th className="px-4 py-3 text-left font-semibold">Enabled</th>
                <th className="px-4 py-3 text-left font-semibold">Created</th>
                <th className="px-4 py-3 text-left font-semibold">Updated</th>
                <th className="px-4 py-3 text-left font-semibold">Last login</th>
                <th className="px-4 py-3 text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && sortedUsers.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-sm text-slate-500" colSpan={7}>Loading users...</td>
                </tr>
              ) : null}
              {!loading && sortedUsers.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-sm text-slate-500" colSpan={7}>No local users found.</td>
                </tr>
              ) : null}
              {sortedUsers.map((user) => (
                <tr key={user.username} className="align-top hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="truncate font-semibold text-slate-950" title={user.username}>{user.username}</div>
                    {user.username === currentUser?.username && <div className="mt-1 text-xs font-medium text-blue-700">Current session</div>}
                  </td>
                  <td className="px-4 py-3"><RolePill role={user.role} /></td>
                  <td className="px-4 py-3"><StatusPill enabled={user.enabled} /></td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatTimestamp(user.created_at)}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatTimestamp(user.updated_at)}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatTimestamp(user.last_login_at)}</td>
                  <td className="px-4 py-3">
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <select
                          aria-label={`Change role for ${user.username}`}
                          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={user.role}
                          disabled={busyKey === `role:${user.username}` || user.enabled === false}
                          onChange={(event) => handleRoleChange(user.username, event.target.value)}
                        >
                          {ROLE_OPTIONS.map((role) => <option key={role} value={role}>{role}</option>)}
                        </select>
                        <button
                          type="button"
                          aria-label={`Disable ${user.username}`}
                          onClick={() => handleDisable(user.username)}
                          disabled={busyKey === `disable:${user.username}` || user.enabled === false}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Disable
                        </button>
                      </div>
                      <form className="flex gap-2" data-testid={`reset-password-${user.username}`} onSubmit={(event) => handleResetPassword(event, user.username)}>
                        <input
                          aria-label={`New password for ${user.username}`}
                          type="password"
                          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          value={resetPasswords[user.username] || ''}
                          onChange={(event) => setResetPasswords((current) => ({ ...current, [user.username]: event.target.value }))}
                          autoComplete="new-password"
                          placeholder="New password"
                        />
                        <button
                          type="submit"
                          disabled={busyKey === `reset:${user.username}` || !(resetPasswords[user.username] || '')}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <KeyRound className="h-3.5 w-3.5" />
                          Reset
                        </button>
                      </form>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-slate-600" />
            <h3 className="text-sm font-semibold text-slate-950">Sessions</h3>
          </div>
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{sortedSessions.length} sessions</span>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
            <colgroup>
              <col className="w-[14rem]" />
              <col className="w-[12rem]" />
              <col className="w-[8rem]" />
              <col className="w-[10rem]" />
              <col className="w-[12rem]" />
              <col className="w-[12rem]" />
              <col className="w-[12rem]" />
              <col className="w-[10rem]" />
            </colgroup>
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">Session</th>
                <th className="px-4 py-3 text-left font-semibold">User</th>
                <th className="px-4 py-3 text-left font-semibold">Role</th>
                <th className="px-4 py-3 text-left font-semibold">Status</th>
                <th className="px-4 py-3 text-left font-semibold">Created</th>
                <th className="px-4 py-3 text-left font-semibold">Expires</th>
                <th className="px-4 py-3 text-left font-semibold">Revoked</th>
                <th className="px-4 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && sortedSessions.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-sm text-slate-500" colSpan={8}>Loading sessions...</td>
                </tr>
              ) : null}
              {!loading && sortedSessions.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-sm text-slate-500" colSpan={8}>No sessions found.</td>
                </tr>
              ) : null}
              {sortedSessions.map((session) => (
                <tr key={session.session_id} className="align-top hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="truncate font-mono text-xs font-semibold text-slate-800" title={session.session_id}>{session.session_id}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="truncate font-semibold text-slate-950" title={session.username}>{session.username}</div>
                    <div className="mt-1 truncate text-xs text-slate-500" title={session.user_id}>{session.enabled ? 'Enabled' : 'Disabled'}</div>
                  </td>
                  <td className="px-4 py-3"><RolePill role={session.role} /></td>
                  <td className="px-4 py-3"><SessionStatusPill status={session.status} isCurrent={session.is_current_session} /></td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatTimestamp(session.created_at)}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatTimestamp(session.expires_at)}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatTimestamp(session.revoked_at)}</td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      aria-label={`Revoke session ${session.session_id}`}
                      onClick={() => handleRevokeSession(session)}
                      disabled={busyKey === `session:${session.session_id}` || session.status !== 'active'}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {busyKey === `session:${session.session_id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Ban className="h-3.5 w-3.5" />}
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  )
}

export default AdminUsersScreen
