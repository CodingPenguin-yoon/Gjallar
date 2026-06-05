import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const srcRoot = new URL('../src', import.meta.url)
const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')

const primaryNavBlock = app.match(/const primaryNavItems = \[([\s\S]*?)\]\n\nconst vmInstancesSubnavItems/)
assert.ok(primaryNavBlock, 'App must define primary navigation items')
const primaryLabels = [...primaryNavBlock[1].matchAll(/label: '([^']+)'/g)].map((match) => match[1])
assert.deepEqual(primaryLabels, ['Overview', 'VM Instances', 'DRS Advisor', 'Operations', 'Settings'], 'Top primary nav must expose exactly the approved labels')
const vmSubnavBlock = app.match(/const vmInstancesSubnavItems = \[([\s\S]*?)\]\n\nconst operationsSubnavItems/)
assert.ok(vmSubnavBlock, 'App must define VM Instances subnavigation items')
const vmSubnavLabels = [...vmSubnavBlock[1].matchAll(/label: '([^']+)'/g)].map((match) => match[1])
assert.deepEqual(vmSubnavLabels, ['Inventory', 'DRS Policies', 'Create VM', 'Network readiness'], 'VM Instances subnav must keep DRS Policies near Inventory')

for (const label of ['Inventory', 'DRS Policies', 'Create VM', 'Network readiness', 'Jobs', 'Risks', 'Account', 'Admin Users']) {
  assert.ok(app.includes(label), `App subnavigation must expose label: ${label}`)
}
for (const route of ['path="/"', 'path="/instances"', 'path="/instances/drs-policies"', 'path="/instances/create"', 'path="/instances/networks"', 'path="/drs"', 'path="/operations/jobs"', 'path="/operations/risks"', 'path="/settings/account"', 'path="/settings/admin/users"']) {
  assert.ok(app.includes(route), `App routes must expose canonical route: ${route}`)
}
for (const route of ['path="/infra"', 'path="/networks"', 'path="/create"', 'path="/jobs"', 'path="/risks"', 'path="/admin/users"', 'path="/account"']) {
  assert.ok(app.includes(route), `App routes must preserve legacy alias route: ${route}`)
}
assert.match(app, /const accountNavItem = \{ label: 'Account', path: '\/settings\/account'/, 'Account navigation must live under Settings')
assert.match(app, /const adminNavItem = \{ label: 'Admin Users', path: '\/settings\/admin\/users'/, 'Admin Users navigation must live under Settings')
assert.match(app, /const settingsSubnavItems = isAdmin \? \[accountNavItem, adminNavItem\] : \[accountNavItem\]/, 'Account settings must be visible to all authenticated users while Admin Users remains admin-only')
assert.match(app, /function AdminGuard/, 'Direct admin route access must be guarded at route level')
assert.match(app, /path="\/settings\/account"\s+element=\{accountRoute\}/, 'Canonical account route must be an active authenticated route')
assert.match(app, /path="\/account"\s+element=\{accountRoute\}/, 'Legacy account alias must keep rendering the account route')
assert.match(app, /path="\/jobs"\s+element=\{jobsRoute\}/, 'Legacy jobs alias must direct-render TaskBoard so query strings are preserved')
assert.doesNotMatch(app, /path="\/placement"|PlacementScreen|label: 'Placement'/, 'Placement must not remain an active product route')
assert.doesNotMatch(app, /from ['"]\.\/services\/api(?:\.js)?['"]/, 'App must not import the legacy /api client')
assert.doesNotMatch(app, /LlmInfraChat|LLM Assistant|\/assistant|Sparkles/, 'LLM assistant must not be routed or shown in MVP nav')
assert.doesNotMatch(app, /provisionInstance|checkIpAvailability|handleProvision|provisioningRequest|onProvision|isProvisioning/, 'App must not own legacy provisioning execution flow')
assert.doesNotMatch(app, /Instance List|Task Board|Risk Dashboard|Monitoring/, 'App must use PRD v1 navigation labels only')
assert.match(app, /cpu_usage_percent/, 'Dashboard must prefer live Proxmox node CPU usage over allocated CPU counts')
assert.match(app, /memory_usage_percent/, 'Dashboard must prefer live Proxmox node memory usage over allocated memory')
assert.doesNotMatch(app, /cpuAllocated|memoryAllocatedGb|CPU alloc|Memory alloc/, 'Dashboard must not fall back to old allocated CPU or memory totals')
assert.match(app, /Promise\.allSettled/, 'Dashboard must keep rendering available inventory when jobs or risks fail')
assert.match(app, /사용 가능한 inventory 데이터는 계속 표시합니다/, 'Dashboard must show partial-failure copy instead of blanking the first screen')
assert.match(app, /const appShellClass = 'mx-auto w-full max-w-7xl px-8'/, 'Authenticated layout must define one shared app shell width')
assert.ok(app.includes('<div className={`${appShellClass} py-5`}>'), 'Authenticated header inner container must use the shared shell with header padding')
assert.ok(app.includes('<div className={appShellClass}>'), 'Primary navigation inner container must use the shared shell')
assert.ok(app.includes('<main className={`${appShellClass} py-8`}>'), 'Authenticated main container must use the shared shell with main padding')
assert.doesNotMatch(app, /className="container mx-auto px-8(?: py-[58])?"/, 'Authenticated layout must not keep separate container shell classes')
assert.doesNotMatch(
  app,
  /<div className="bg-white rounded-lg border border-gray-200 shadow-sm">\s*<InstanceList\b/,
  'VM inventory route must not wrap InstanceList in an extra card',
)

for (const component of [
  'DrsAdvisorScreen',
  'DrsPoliciesScreen',
  'CreateInstanceWizard',
  'NetworkReadinessScreen',
  'OperationalRiskDashboard',
  'AdminUsersScreen',
]) {
  assert.doesNotMatch(
    app,
    new RegExp(`<div className="mx-auto max-w-[^"]+">\\s*<${component}\\b`),
    `${component} route must not add a route-level max-width wrapper`,
  )
}

const activeImports = app
  .split('\n')
  .map((line) => line.match(/^import\s+[^\n]+\s+from\s+['"](\.\/components\/[^'"]+)['"]/))
  .filter(Boolean)
  .map((match) => match[1])

assert.deepEqual(
  activeImports.sort(),
  [
    './components/CreateInstanceWizard',
    './components/AdminUsersScreen',
    './components/DrsPoliciesScreen',
    './components/DrsAdvisorScreen',
    './components/InstanceList',
    './components/NetworkReadinessScreen',
    './components/OperationalRiskDashboard',
    './components/TaskBoard',
  ].sort(),
  'Only PRD MVP screen components should be actively routed from App',
)

for (const legacyPath of [
  '../src/services/api.js',
  '../src/components/LlmInfraChat.jsx',
  '../src/utils/provisioningPayload.js',
  '../src/utils/provisioningReadiness.js',
  '../src/utils/provisioningSummary.js',
  '../src/utils/resourcePreflight.js',
  '../src/utils/lifecycleSafety.js',
  '../src/utils/inventorySummary.js',
  '../src/utils/monitoringSignals.js',
  '../src/utils/riskPolicy.js',
  '../src/utils/taskBoardSummary.js',
]) {
  assert.equal(existsSync(new URL(legacyPath, import.meta.url)), false, `${legacyPath} must stay out of active src`)
}

function collectSourceFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return collectSourceFiles(path)
    return /\.(js|jsx|mjs)$/.test(path) ? [path] : []
  })
}

for (const file of collectSourceFiles(srcRoot.pathname)) {
  const rel = relative(srcRoot.pathname, file)
  const source = readFileSync(file, 'utf8')
  assert.doesNotMatch(source, /from ['"](?:\.\.\/|\.\/)?services\/api(?:\.js)?['"]/, `${rel} must not import legacy services/api`)
  assert.doesNotMatch(source, /LlmInfraChat|LLM Infra Assistant|LLM Assistant|\/assistant/, `${rel} must not expose the parked LLM assistant`)
}

console.log('appNavigation RED contract exercised')
