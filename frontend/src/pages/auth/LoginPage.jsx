import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Server } from 'lucide-react'
import { authFailureMessage } from '../../shared/auth/permissions'

export default function LoginPage({ onLogin }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submitLogin = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await onLogin({ username, password })
      const target = location.state?.from?.pathname || '/'
      navigate(target, { replace: true })
    } catch (err) {
      setError(authFailureMessage(err, '로그인에 실패했습니다.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6 py-10">
        <section className="w-full rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <Server className="h-7 w-7 text-slate-700" />
            <div>
              <h1 className="text-xl font-semibold text-slate-950">Gjallar Login</h1>
              <p className="mt-1 text-sm text-slate-500">Proxmox 운영 콘솔 접근</p>
            </div>
          </div>
          <form className="mt-6 space-y-4" onSubmit={submitLogin}>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Username</span>
              <input
                autoComplete="username"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Password</span>
              <input
                type="password"
                autoComplete="current-password"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
            ) : null}
            <button
              type="submit"
              disabled={submitting || !username || !password}
              className="inline-flex w-full items-center justify-center rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Logging in...' : 'Login'}
            </button>
          </form>
        </section>
      </main>
    </div>
  )
}
