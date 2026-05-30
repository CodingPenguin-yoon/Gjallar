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

const appSource = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
assert.match(appSource, /apiV1Client\.me\(\)/, 'App must bootstrap from /auth/me')
assert.match(appSource, /apiV1Client\.login\(username, password\)/, 'App must login through the auth API')
assert.match(appSource, /apiV1Client\.logout\(\)/, 'App must logout through the auth API')
assert.match(appSource, /path="\/login"/, 'App must expose a /login route')
assert.match(appSource, /Navigate to="\/login"/, 'Unauthenticated users must be redirected to /login')
assert.match(appSource, /currentUser\?\.username/, 'App shell must show current username')
assert.match(appSource, /currentUser\?\.role/, 'App shell must show current role')
assert.match(appSource, /canOperate\(currentUser\)/, 'App must derive mutation permission from the authenticated role')
assert.match(appSource, /canAdmin\(currentUser\)/, 'App must derive admin permission from the authenticated role')
assert.match(appSource, /canExecuteLiveMutation=\{canMutate\}/, 'Create VM live execution must receive role permission')
assert.match(appSource, /canStartVms=\{canMutate\}/, 'VM Start controls must receive role permission')
assert.match(appSource, /canManageDrsPolicies=\{canMutate\}/, 'Infra Explorer DRS policy controls must receive role permission')
assert.match(appSource, /<DrsAdvisorScreen currentUser=\{currentUser\} canOperate=\{canMutate\}/, 'DRS Advisor must receive session user and operator permission')
assert.match(appSource, /path="\/admin\/users"/, 'App must expose the admin user-management route')
assert.match(appSource, /<AdminGuard currentUser=\{currentUser\}>/, 'Admin route must use a route-level admin guard')
assert.match(appSource, /Admin Users/, 'Admin nav item must be available for admins')
assert.match(appSource, /onCurrentUserChanged=\{refreshCurrentUser\}/, 'Admin self-demotion must refresh the current session')

const wizardSource = readFileSync(new URL('../src/components/CreateInstanceWizard.jsx', import.meta.url), 'utf8')
assert.match(wizardSource, /canExecuteLiveMutation/, 'Create VM wizard must guard live Proxmox execution by role')
assert.match(wizardSource, /operator 또는 admin 권한이 필요합니다/, 'Create VM wizard must explain insufficient mutation role')
assert.match(wizardSource, /세션 사용자/, 'Create VM wizard must show session-derived actor instead of editable operator_id')
assert.doesNotMatch(wizardSource, /updateForm\('operatorId'/, 'Create VM wizard must not expose editable operator_id input')
assert.match(wizardSource, /disabled=\{!canExecuteLiveMutation \|\| loading/, 'Create VM review must disable for viewers')
assert.match(wizardSource, /disabled=\{!canExecuteLiveMutation \|\| !model\.review\.canApprove/, 'Create VM approval must disable for viewers')
assert.match(wizardSource, /disabled=\{!canExecuteLiveMutation/, 'Create VM acknowledgement must disable for viewers')

const instanceListSource = readFileSync(new URL('../src/components/InstanceList.jsx', import.meta.url), 'utf8')
assert.match(instanceListSource, /canStartVms/, 'Instance list must guard VM Start by role')
assert.match(instanceListSource, /canManageDrsPolicies/, 'Instance list must guard DRS policy updates by role')
assert.match(instanceListSource, /VM Start requires operator or admin role/, 'Instance list must explain insufficient VM Start role')
assert.match(instanceListSource, /DRS policy review is visible, but updates require operator or admin role/, 'Instance list must explain insufficient DRS policy role')
assert.match(instanceListSource, /canStartVms && canStartVm\(vm\)/, 'VM Start action button must be hidden unless the role can mutate')
assert.match(instanceListSource, /submitDrsPolicyUpdate/, 'Infra Explorer DRS policy updates must go through the shared API helper')

const drsSource = readFileSync(new URL('../src/components/DrsAdvisorScreen.jsx', import.meta.url), 'utf8')
const drsPolicyModalSource = readFileSync(new URL('../src/components/DrsPolicyReviewModal.jsx', import.meta.url), 'utf8')
assert.match(drsSource, /function DrsAdvisorScreen\(\{ currentUser = null, canOperate = false \}\)/, 'DRS Advisor must accept current user and mutation permission props')
assert.match(drsSource, /approvalReadiness\.approvalPacketCreatable/, 'DRS approval packet button must be gated by backend readiness')
assert.match(drsSource, /canOperate \? \(/, 'DRS approval packet control must branch on operator permission')
assert.match(drsSource, /DRS approval packet creation requires operator or admin role/, 'DRS Advisor must explain insufficient approval role')
assert.match(drsSource, /DRS policy updates require operator or admin role/, 'DRS policy updates must explain insufficient mutation role')
assert.match(drsSource, /submitDrsPolicyUpdate/, 'DRS policy updates must go through the API helper')
assert.match(drsPolicyModalSource, /Policy changes do not start migration/, 'DRS policy review modal must explain migration boundary')
assert.doesNotMatch(drsSource, /approved_actor|operator_id|actor:/, 'DRS approval payload must not include a frontend-supplied actor')
assert.doesNotMatch(instanceListSource, /approved_actor|operator_id|actor:/, 'Infra Explorer DRS policy payload must not include a frontend-supplied actor')

console.log('authFlow contract exercised')
