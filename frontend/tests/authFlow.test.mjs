import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const {
  ROLE_ORDER,
  authFailureMessage,
  canAdmin,
  canOperate,
  hasRole,
} = await importExpected('../src/utils/auth.js', 'auth role helpers')

assert.deepEqual(Object.keys(ROLE_ORDER), ['viewer', 'operator', 'admin'])
assert.equal(hasRole({ role: 'viewer' }, 'viewer'), true)
assert.equal(hasRole({ role: 'viewer' }, 'operator'), false)
assert.equal(hasRole({ role: 'operator' }, 'viewer'), true)
assert.equal(hasRole({ role: 'admin' }, 'operator'), true)
assert.equal(canAdmin({ role: 'admin' }), true)
assert.equal(canAdmin({ role: 'operator' }), false)
assert.equal(canOperate({ role: 'operator' }), true)
assert.equal(canOperate({ role: 'viewer' }), false)
assert.equal(authFailureMessage({ status: 401 }, 'fallback'), '로그인이 필요합니다.')
assert.equal(authFailureMessage({ status: 403 }, 'fallback'), '권한이 부족합니다.')
assert.equal(authFailureMessage({ message: 'custom' }, 'fallback'), 'custom')

const appSource = readFileSync(new URL('../src/app/App.jsx', import.meta.url), 'utf8')
const appShellSource = readFileSync(new URL('../src/app/AppShell.jsx', import.meta.url), 'utf8')
const navigationSource = [
  readFileSync(new URL('../src/app/navigationModel.js', import.meta.url), 'utf8'),
  readFileSync(new URL('../src/app/navigation.jsx', import.meta.url), 'utf8'),
].join('\n')
const accountSource = readFileSync(new URL('../src/pages/settings/AccountSettingsPage.jsx', import.meta.url), 'utf8')
assert.match(appSource, /apiV1Client\.me\(\)/, 'App must bootstrap from /auth/me')
assert.match(appSource, /apiV1Client\.login\(username, password\)/, 'App must login through the auth API')
assert.match(appSource, /apiV1Client\.logout\(\)/, 'App must logout through the auth API')
assert.match(accountSource, /apiV1Client\.changePassword\(form\.currentPassword, form\.newPassword\)/, 'Account page must change passwords through the auth API')
assert.match(appSource, /path="\/login"/, 'App must expose a /login route')
assert.match(appSource, /path="\/settings\/account"/, 'App must expose the canonical authenticated account route')
assert.match(appSource, /path="\/account"/, 'App must preserve the legacy authenticated account alias')
assert.match(appSource, /Navigate to="\/login"/, 'Unauthenticated users must be redirected to /login')
assert.match(appShellSource, /currentUser\?\.username/, 'App shell must show current username')
assert.match(appShellSource, /currentUser\?\.role/, 'App shell must show current role')
assert.match(appSource, /canOperate\(currentUser\)/, 'App must derive mutation permission from the authenticated role')
assert.match(appSource, /canAdmin\(currentUser\)/, 'App must derive admin permission from the authenticated role')
assert.match(appSource, /canExecuteLiveMutation=\{canOperate\(currentUser\)\}/, 'Create VM live execution must receive role permission')
assert.match(appSource, /<WorkloadCockpitPage currentUser=\{currentUser\} canMutate=\{canMutate\}/, 'Workload Cockpit must receive the verified mutation permission')
assert.match(appSource, /<GuidedQmUnlockPage canExecute=\{canMutate\}/, 'Guided qm plan must require verified mutation permission')
assert.match(appSource, /<OperationDetailPage canExecute=\{canMutate\}/, 'Guided operation actions in detail must require verified mutation permission')
assert.match(appSource, /path="\/settings\/admin\/users"/, 'App must expose the canonical admin user-management route')
assert.match(appSource, /path="\/admin\/users"/, 'App must preserve the legacy guarded admin user-management alias')
assert.match(appSource, /<AdminGuard currentUser=\{currentUser\}>/, 'Admin route must use a route-level admin guard')
assert.match(navigationSource, /isAdmin \? \[accountNavItem, adminNavItem\] : \[accountNavItem\]/, 'Settings subnavigation must keep Admin Users admin-only')
assert.match(navigationSource, /label: 'Account'/, 'Account settings nav item must be available for authenticated users')
assert.match(appSource, /onCurrentUserChanged=\{refreshCurrentUser\}/, 'Admin self-demotion must refresh the current session')
assert.match(appSource, /onPasswordChanged=\{refreshCurrentUser\}/, 'Self password changes must refresh the current session state')
assert.doesNotMatch(appSource, /password_hash|session_token_hash|token_hash|user_agent_hash|ip_hash/, 'App must not reference secret auth storage fields')

const wizardSource = readFileSync(new URL('../src/components/CreateInstanceWizard.jsx', import.meta.url), 'utf8')
assert.match(wizardSource, /canExecuteLiveMutation/, 'Create VM wizard must guard live Proxmox execution by role')
assert.match(wizardSource, /operator 또는 admin 권한이 필요합니다/, 'Create VM wizard must explain insufficient mutation role')
assert.match(wizardSource, /세션 사용자/, 'Create VM wizard must show session-derived actor instead of editable operator_id')
assert.doesNotMatch(wizardSource, /updateForm\('operatorId'/, 'Create VM wizard must not expose editable operator_id input')
assert.match(wizardSource, /disabled=\{!canExecuteLiveMutation \|\| loading/, 'Create VM review must disable for viewers')
assert.match(wizardSource, /disabled=\{!canExecuteLiveMutation \|\| !model\.review\.canApprove/, 'Create VM approval must disable for viewers')
assert.match(wizardSource, /disabled=\{!canExecuteLiveMutation/, 'Create VM acknowledgement must disable for viewers')

const instanceListSource = readFileSync(new URL('../src/features/workloads/inventory/WorkloadInventory.jsx', import.meta.url), 'utf8')
assert.match(instanceListSource, /canMutateVms/, 'Instance list must guard VM lifecycle mutations by role')
assert.match(instanceListSource, /VM lifecycle actions require operator or admin role/, 'Instance list must explain insufficient VM lifecycle role')
assert.match(instanceListSource, /canMutateVms && canStartVm\(vm\)/, 'VM Start action button must be hidden unless the role can mutate')
assert.match(instanceListSource, /canMutateVms && canShutdownVm\(vm\)/, 'VM Shutdown action button must be hidden unless the role can mutate')
assert.doesNotMatch(instanceListSource, /approved_actor|operator_id|actor:/, 'Instance inventory must not include a frontend-supplied actor')

console.log('authFlow contract exercised')
