import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { renderToStaticMarkup } from 'react-dom/server'
import { jsx, jsxs } from 'react/jsx-runtime'

function loadCommonJsModule(code, filename) {
  const module = { exports: {} }
  const dirname = path.dirname(filename)
  const localRequire = (specifier) => {
    if (specifier === 'react/jsx-runtime') return { jsx, jsxs, Fragment: Symbol.for('react.fragment') }
    throw new Error(`Unexpected require in compiled test module: ${specifier}`)
  }

  const script = new vm.Script(`(function (exports, require, module, __filename, __dirname, globalThis) {${code}\n})`, {
    filename,
  })

  script.runInThisContext()(module.exports, localRequire, module, filename, dirname, globalThis)
  return module.exports
}

function createHookHarness() {
  const state = []
  let cursor = 0
  let effects = []

  return {
    hooks: {
      useState(initialValue) {
        const index = cursor
        if (state[index] === undefined) {
          state[index] = typeof initialValue === 'function' ? initialValue() : initialValue
        }
        cursor += 1
        const setState = (nextValue) => {
          state[index] = typeof nextValue === 'function' ? nextValue(state[index]) : nextValue
        }
        return [state[index], setState]
      },
      useMemo(factory) {
        return factory()
      },
      useEffect(effect) {
        effects.push(effect)
      },
    },
    beginRender() {
      cursor = 0
      effects = []
    },
    async flushEffects() {
      for (const effect of effects) {
        const result = effect()
        if (result && typeof result.then === 'function') await result
      }
      await Promise.resolve()
      await Promise.resolve()
    },
  }
}

function icon(name) {
  return function Icon(props) {
    return jsx('svg', { ...props, 'data-icon': name })
  }
}

function compileAdminUsersSource(source) {
  return source
    .replace(
      /import\s+\{\s*useEffect,\s*useMemo,\s*useState\s*\}\s+from\s+'react'/,
      'const { useEffect, useMemo, useState } = globalThis.__ADMIN_USERS_TEST_MOCKS__.reactHooks',
    )
    .replace(
      /import\s+\{\s*([\s\S]*?)\s*\}\s+from\s+'lucide-react'/,
      `const {
  AlertTriangle,
  Ban,
  CheckCircle2,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
  UserPlus,
  Users,
} = globalThis.__ADMIN_USERS_TEST_MOCKS__.icons`,
    )
    .replace(
      /import\s+\{\s*apiV1Client\s*\}\s+from\s+'..\/services\/apiV1'/,
      'const { apiV1Client } = globalThis.__ADMIN_USERS_TEST_MOCKS__.api',
    )
    .replace(
      /import\s+\{\s*authFailureMessage\s*\}\s+from\s+'..\/utils\/auth'/,
      'const { authFailureMessage } = globalThis.__ADMIN_USERS_TEST_MOCKS__.auth',
    )
}

function findElement(node, predicate) {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = findElement(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!node || typeof node !== 'object') return null
  if (predicate(node)) return node

  const children = node.props?.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const match = findElement(child, predicate)
      if (match) return match
    }
    return null
  }

  return findElement(children, predicate)
}

const sourcePath = new URL('../src/components/AdminUsersScreen.jsx', import.meta.url)
const source = readFileSync(sourcePath, 'utf8')

assert.match(source, /apiV1Client\.listAdminUsers\(\)/)
assert.match(source, /apiV1Client\.listAdminSessions\(\)/)
assert.match(source, /apiV1Client\.createAdminUser\(createForm\)/)
assert.match(source, /apiV1Client\.setAdminUserRole\(username, role\)/)
assert.match(source, /apiV1Client\.disableAdminUser\(username\)/)
assert.match(source, /apiV1Client\.resetAdminUserPassword\(username, password\)/)
assert.match(source, /apiV1Client\.revokeAdminSession\(session\.session_id\)/)
assert.match(source, /authFailureMessage\(err/)
assert.match(source, /onCurrentUserChanged/)
assert.doesNotMatch(source, /password_hash|session_token_hash|token_hash|user_agent_hash|ip_hash/)

const users = [
  {
    username: 'admin',
    role: 'admin',
    enabled: true,
    created_at: '2026-05-27T00:00:00+00:00',
    updated_at: '2026-05-27T00:00:00+00:00',
    last_login_at: '2026-05-27T01:00:00+00:00',
  },
  {
    username: 'api-viewer',
    role: 'viewer',
    enabled: true,
    created_at: '2026-05-27T00:00:00+00:00',
    updated_at: '2026-05-27T00:00:00+00:00',
    last_login_at: null,
  },
]
const sessions = [
  {
    session_id: 'sess-current',
    user_id: 'user-admin',
    username: 'admin',
    role: 'admin',
    enabled: true,
    status: 'active',
    is_current_session: true,
    created_at: '2026-05-27T03:00:00+00:00',
    expires_at: '2026-05-28T03:00:00+00:00',
    revoked_at: null,
  },
  {
    session_id: 'sess-active',
    user_id: 'user-viewer',
    username: 'api-viewer',
    role: 'viewer',
    enabled: true,
    status: 'active',
    is_current_session: false,
    created_at: '2026-05-27T02:00:00+00:00',
    expires_at: '2026-05-28T02:00:00+00:00',
    revoked_at: null,
  },
  {
    session_id: 'sess-expired',
    user_id: 'user-viewer',
    username: 'api-viewer',
    role: 'viewer',
    enabled: true,
    status: 'expired',
    is_current_session: false,
    created_at: '2026-05-26T02:00:00+00:00',
    expires_at: '2026-05-26T03:00:00+00:00',
    revoked_at: null,
  },
  {
    session_id: 'sess-revoked',
    user_id: 'user-viewer',
    username: 'api-viewer',
    role: 'viewer',
    enabled: true,
    status: 'revoked',
    is_current_session: false,
    created_at: '2026-05-25T02:00:00+00:00',
    expires_at: '2026-05-26T02:00:00+00:00',
    revoked_at: '2026-05-25T03:00:00+00:00',
  },
]
const calls = []
let currentRefreshes = 0

const fakeClient = {
  async listAdminUsers() {
    calls.push(['listAdminUsers'])
    return users.map((user) => ({ ...user }))
  },
  async listAdminSessions() {
    calls.push(['listAdminSessions'])
    return sessions.map((session) => ({ ...session }))
  },
  async createAdminUser(payload) {
    calls.push(['createAdminUser', { ...payload }])
    users.push({
      username: payload.username,
      role: payload.role,
      enabled: true,
      created_at: '2026-05-27T02:00:00+00:00',
      updated_at: '2026-05-27T02:00:00+00:00',
      last_login_at: null,
    })
    return { user: users.at(-1) }
  },
  async setAdminUserRole(username, role) {
    calls.push(['setAdminUserRole', username, role])
    const user = users.find((item) => item.username === username)
    user.role = role
    return { user }
  },
  async disableAdminUser(username) {
    calls.push(['disableAdminUser', username])
    const user = users.find((item) => item.username === username)
    user.enabled = false
    return { user, revoked_sessions: 1 }
  },
  async resetAdminUserPassword(username, password) {
    calls.push(['resetAdminUserPassword', username, password])
    return { user: users.find((item) => item.username === username), revoked_sessions: 1 }
  },
  async revokeAdminSession(sessionId) {
    calls.push(['revokeAdminSession', sessionId])
    const session = sessions.find((item) => item.session_id === sessionId)
    const wasActive = session.status === 'active'
    session.status = 'revoked'
    session.revoked_at = '2026-05-27T04:00:00+00:00'
    return {
      session,
      revoked: wasActive,
      idempotent: !wasActive,
      current_session_revoked: session.is_current_session,
    }
  },
}

const compiled = transformSync(compileAdminUsersSource(source), {
  loader: 'jsx',
  format: 'cjs',
  jsx: 'automatic',
}).code

const hookHarness = createHookHarness()
globalThis.__ADMIN_USERS_TEST_MOCKS__ = {
  reactHooks: hookHarness.hooks,
  icons: {
    AlertTriangle: icon('AlertTriangle'),
    Ban: icon('Ban'),
    CheckCircle2: icon('CheckCircle2'),
    KeyRound: icon('KeyRound'),
    Loader2: icon('Loader2'),
    RefreshCw: icon('RefreshCw'),
    ShieldCheck: icon('ShieldCheck'),
    UserPlus: icon('UserPlus'),
    Users: icon('Users'),
  },
  api: { apiV1Client: fakeClient },
  auth: { authFailureMessage: (error, fallback) => error?.message || fallback },
}

const compiledModule = loadCommonJsModule(compiled, String(sourcePath))
const AdminUsersScreen = compiledModule.default

hookHarness.beginRender()
AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
await hookHarness.flushEffects()

hookHarness.beginRender()
let tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
let html = renderToStaticMarkup(tree)
assert.match(html, /Users &amp; sessions/)
assert.match(html, /Create User/)
assert.match(html, /Local Users/)
assert.match(html, /Sessions/)
assert.match(html, /api-viewer/)
assert.match(html, /Current session/)
assert.match(html, /sess-current/)
assert.match(html, /sess-active/)
assert.match(html, /Current active/i)
assert.match(html, /expired/i)
assert.match(html, /revoked/i)
assert.match(html, /Enabled/)
assert.doesNotMatch(html, /password_hash|session_token_hash|token_hash|user_agent_hash|ip_hash|create-secret|reset-secret/)

findElement(tree, (element) => element.props?.['aria-label'] === 'Create username').props.onChange({ target: { value: 'new-operator' } })
findElement(tree, (element) => element.props?.['aria-label'] === 'Create password').props.onChange({ target: { value: 'create-secret' } })
findElement(tree, (element) => element.props?.['aria-label'] === 'Create role').props.onChange({ target: { value: 'operator' } })

hookHarness.beginRender()
tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
await findElement(tree, (element) => element.type === 'form' && !element.props?.['data-testid']).props.onSubmit({ preventDefault() {} })

assert.deepEqual(calls.find((call) => call[0] === 'createAdminUser'), ['createAdminUser', { username: 'new-operator', password: 'create-secret', role: 'operator' }])

hookHarness.beginRender()
tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
html = renderToStaticMarkup(tree)
assert.match(html, /new-operator/)
assert.doesNotMatch(html, /create-secret/)

await findElement(tree, (element) => element.props?.['aria-label'] === 'Change role for new-operator').props.onChange({ target: { value: 'admin' } })
await findElement(tree, (element) => element.props?.['aria-label'] === 'Disable new-operator').props.onClick()
assert.deepEqual(calls.find((call) => call[0] === 'setAdminUserRole'), ['setAdminUserRole', 'new-operator', 'admin'])
assert.deepEqual(calls.find((call) => call[0] === 'disableAdminUser'), ['disableAdminUser', 'new-operator'])

await findElement(tree, (element) => element.props?.['aria-label'] === 'Revoke session sess-active').props.onClick()
assert.deepEqual(calls.find((call) => call[0] === 'revokeAdminSession'), ['revokeAdminSession', 'sess-active'])

hookHarness.beginRender()
tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
await findElement(tree, (element) => element.props?.['aria-label'] === 'Revoke session sess-current').props.onClick()
assert.equal(currentRefreshes, 1, 'Revoking the current session must refresh current auth state')

hookHarness.beginRender()
tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
findElement(tree, (element) => element.props?.['aria-label'] === 'New password for new-operator').props.onChange({ target: { value: 'reset-secret' } })

hookHarness.beginRender()
tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
await findElement(tree, (element) => element.props?.['data-testid'] === 'reset-password-new-operator').props.onSubmit({ preventDefault() {} })
assert.deepEqual(calls.find((call) => call[0] === 'resetAdminUserPassword'), ['resetAdminUserPassword', 'new-operator', 'reset-secret'])

hookHarness.beginRender()
tree = AdminUsersScreen({
  currentUser: { username: 'admin', role: 'admin' },
  onCurrentUserChanged: async () => {
    currentRefreshes += 1
  },
})
html = renderToStaticMarkup(tree)
assert.doesNotMatch(html, /reset-secret/)

await findElement(tree, (element) => element.props?.['aria-label'] === 'Change role for admin').props.onChange({ target: { value: 'operator' } })
assert.equal(currentRefreshes, 2, 'Changing the current admin must refresh current auth state')

console.log('adminUsersScreen RED contract exercised')
