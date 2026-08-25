import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const srcRoot = new URL('../src', import.meta.url)
const appFacade = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/app/App.jsx', import.meta.url), 'utf8')
const navigation = [
  readFileSync(new URL('../src/app/navigationModel.js', import.meta.url), 'utf8'),
  readFileSync(new URL('../src/app/navigation.jsx', import.meta.url), 'utf8'),
].join('\n')
const shell = readFileSync(new URL('../src/app/AppShell.jsx', import.meta.url), 'utf8')
const dashboard = readFileSync(new URL('../src/pages/dashboard/DashboardPage.jsx', import.meta.url), 'utf8')
const workloadPage = readFileSync(new URL('../src/pages/workloads/WorkloadCockpitPage.jsx', import.meta.url), 'utf8')

assert.match(appFacade, /from ['"]\.\/app\/App['"]/, 'Root App must be a compatibility entrypoint into the app layer')

for (const label of ['Overview', 'Workloads', 'Insights', 'Operations', 'Settings']) {
  assert.ok(navigation.includes(`label: '${label}'`), `Primary navigation must expose ${label}`)
}
for (const label of ['Inventory', 'Create VM', 'Network readiness', 'Jobs', 'Risks', 'Readiness', 'Capacity', 'Placement', 'Guided qm', 'Account', 'Admin Users']) {
  assert.ok(navigation.includes(label), `Section navigation must expose ${label}`)
}
assert.doesNotMatch(navigation, /label: 'DRS Advisor'/, 'DRS must not remain a primary product navigation item')
assert.doesNotMatch(navigation, /label: 'DRS Policies'/, 'DRS Policies must not remain a Workloads navigation item')

for (const route of [
  'path="/"',
  'path="/instances"',
  'path="/instances/create"',
  'path="/instances/networks"',
  'path="/insights"',
  'path="/insights/risks"',
  'path="/insights/readiness"',
  'path="/insights/capacity"',
  'path="/insights/placement"',
  'path="/operations"',
  'path="/operations/guided-qm/vm-unlock"',
  'path="/operations/:operationId"',
  'path="/operations/jobs"',
  'path="/operations/risks"',
  'path="/settings/account"',
  'path="/settings/admin/users"',
]) {
  assert.ok(app.includes(route), `App routes must expose canonical route: ${route}`)
}
for (const route of ['path="/infra"', 'path="/networks"', 'path="/create"', 'path="/jobs"', 'path="/risks"', 'path="/admin/users"', 'path="/account"']) {
  assert.ok(app.includes(route), `App routes must preserve legacy alias route: ${route}`)
}

assert.match(navigation, /isAdmin \? \[accountNavItem, adminNavItem\] : \[accountNavItem\]/, 'Admin Users navigation must remain admin-only')
assert.match(navigation, /!item\.requiresOperator \|\| canExecute/, 'Guided qm navigation must be hidden without execution permission')
assert.match(app, /function AdminGuard/, 'Direct admin route access must be guarded')
assert.match(app, /path="\/jobs"\s+element=\{jobsRoute\}/, 'Legacy Jobs alias must direct-render so query strings are preserved')
assert.match(app, /visiblePrimaryNavItems/, 'Unavailable Proxmox navigation must be hidden')
assert.match(app, /<InsightsPage category=\{category\}/, 'Insights routes must compose the dedicated page boundary')
assert.doesNotMatch(app, /operationalRoute\(\s*insightsRoute/, 'Insights must remain visible for partial source availability')
assert.doesNotMatch(app, /path="\/(?:drs|instances\/drs-policies)"/, 'Removed DRS URLs must follow the unknown-path fallback')
assert.match(app, /<Route path="\*" element=\{<Navigate to="\/" replace \/>\} \/>/, 'Authenticated unknown paths must continue to redirect to Overview')
assert.match(app, /operationalRoute\(<Dashboard \/>\)/, 'Dashboard must require authoritative Proxmox connection truth')
assert.match(app, /canOperate\(currentUser\) && proxmoxOperational/, 'Mutation affordances must require role and live connection truth')
assert.doesNotMatch(app, /from ['"]\.\.\/components\//, 'App layer must compose pages rather than legacy screen components')
assert.doesNotMatch(app, /from ['"]\.\.\/(?:services|utils)\//, 'App layer must use shared public modules')

assert.match(navigation, /APP_SHELL_CLASS = 'mx-auto w-full max-w-7xl px-8'/, 'Authenticated layout must define one shell width')
assert.ok(shell.includes('<div className={`${APP_SHELL_CLASS} py-5`}>'), 'Header must use shared shell width')
assert.ok(shell.includes('<div className={APP_SHELL_CLASS}>'), 'Primary navigation must use shared shell width')
assert.ok(shell.includes('<main className={`${APP_SHELL_CLASS} py-8`}>'), 'Main content must use shared shell width')
assert.match(workloadPage, /WorkloadInventory/, 'Workload Cockpit page must consume the workload feature boundary')

assert.match(dashboard, /cpu_usage_percent/, 'Dashboard must prefer live Proxmox CPU usage')
assert.match(dashboard, /memory_usage_percent/, 'Dashboard must prefer live Proxmox memory usage')
assert.match(dashboard, /Promise\.allSettled/, 'Dashboard must preserve partial inventory on adjacent query failure')
assert.match(dashboard, /사용 가능한 inventory 데이터는 계속 표시합니다/, 'Dashboard must explain partial failures')
assert.doesNotMatch(dashboard, /cpuAllocated|memoryAllocatedGb|CPU alloc|Memory alloc/, 'Dashboard must not revive allocated-resource fallbacks')

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
  if (rel.startsWith('entities/')) {
    assert.doesNotMatch(source, /from ['"][^'"]*(?:features|pages|app)\//, `${rel} must not depend upward from entities`)
  }
  if (rel.startsWith('features/')) {
    assert.doesNotMatch(source, /from ['"][^'"]*(?:pages|app)\//, `${rel} must not depend upward from features`)
  }
  if (rel.startsWith('shared/')) {
    assert.doesNotMatch(source, /from ['"][^'"]*(?:entities|features|pages|app)\//, `${rel} must not depend upward from shared`)
  }
}

console.log('appNavigation architecture contract exercised')
