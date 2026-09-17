import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import {
  accountNavItem,
  adminNavItem,
  insightsNavItems,
  operationsNavItems,
  resolveSectionNavItems,
  workloadNavItems,
} from '../src/app/navigationModel.js'

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
const vmDetailPage = readFileSync(new URL('../src/pages/workloads/VmDetailPage.jsx', import.meta.url), 'utf8')

assert.match(appFacade, /from ['"]\.\/app\/App['"]/, 'Root App must be a compatibility entrypoint into the app layer')

for (const label of ['Overview', 'Workloads', 'Insights', 'Operations', 'Settings']) {
  assert.ok(navigation.includes(`label: '${label}'`), `Primary navigation must expose ${label}`)
}
for (const label of ['Inventory', 'Create VM', 'All operations', 'Job history', 'Summary', 'Risks', 'VM readiness', 'Capacity', 'Placement', 'Account', 'Users & sessions']) {
  assert.ok(navigation.includes(label), `Section navigation must expose ${label}`)
}
assert.doesNotMatch(navigation, /label: 'Network readiness'/, 'Retired network comparison must not remain a navigation item')
assert.doesNotMatch(navigation, /label: 'DRS Advisor'/, 'DRS must not remain a primary product navigation item')
assert.doesNotMatch(navigation, /label: 'DRS Policies'/, 'DRS Policies must not remain a Workloads navigation item')

for (const [items, pathname, expectedLabel] of [
  [workloadNavItems, '/instances', 'Inventory'],
  [workloadNavItems, '/instances/306', 'Inventory'],
  [workloadNavItems, '/instances/create', 'Create VM'],
  [workloadNavItems, '/infra', 'Inventory'],
  [workloadNavItems, '/create', 'Create VM'],
  [insightsNavItems, '/insights', 'Summary'],
  [insightsNavItems, '/insights/risks', 'Risks'],
  [insightsNavItems, '/insights/readiness', 'VM readiness'],
  [insightsNavItems, '/insights/capacity', 'Capacity'],
  [insightsNavItems, '/insights/placement', 'Placement'],
  [operationsNavItems, '/operations', 'All operations'],
  [operationsNavItems, '/operations/operation-123', 'All operations'],
  [operationsNavItems, '/operations/jobs', 'Job history'],
  [operationsNavItems, '/jobs', 'Job history'],
  [operationsNavItems, '/operations/guided-qm/vm-unlock', 'All operations'],
  [operationsNavItems, '/operations/risks', 'All operations'],
  [operationsNavItems, '/risks', 'All operations'],
  [[accountNavItem, adminNavItem], '/settings/account', 'Account'],
  [[accountNavItem, adminNavItem], '/account', 'Account'],
  [[accountNavItem, adminNavItem], '/settings/admin/users', 'Users & sessions'],
  [[accountNavItem, adminNavItem], '/admin/users', 'Users & sessions'],
]) {
  const activeItems = resolveSectionNavItems(items, pathname).filter((item) => item.isActive)
  assert.equal(activeItems.length, 1, `${pathname} must activate exactly one section navigation item`)
  assert.equal(activeItems[0].label, expectedLabel, `${pathname} must activate ${expectedLabel}`)
}
assert.match(navigation, /aria-current=\{isActive \? 'page' : undefined\}/, 'Section navigation must expose its single resolved active item as the current page')
assert.match(navigation, /className=\{subnavClass\(\{ isActive \}\)\}/, 'Section navigation styling must use the same resolved active item')
assert.doesNotMatch(navigation, /<NavLink/, 'Section navigation must not reintroduce an independent router active-state calculation')

for (const route of [
  'path="/"',
  'path="/instances"',
  'path="/instances/create"',
  'path="/instances/networks"',
  'path="/instances/:vmid"',
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

for (const route of ['/instances/networks', '/networks']) {
  assert.ok(app.includes(`path="${route}" element={<Navigate to="/instances" replace />}`), `${route} must redirect to inventory`)
}
assert.doesNotMatch(app, /NetworkReadiness|networkReadinessRoute/, 'Retired network screen must not remain in app composition')
for (const retiredPath of ['../src/pages/workloads/NetworkReadinessPage.jsx', '../src/components/NetworkReadinessScreen.jsx', '../src/utils/networkReadiness.js']) {
  assert.equal(existsSync(new URL(retiredPath, import.meta.url)), false, `${retiredPath} must be removed with its independent screen`)
}
assert.doesNotMatch(dashboard, /Network readiness|navigate\('\/instances\/networks'\)/, 'Overview must not advertise the retired screen')

assert.match(navigation, /isAdmin \? \[accountNavItem, adminNavItem, proxmoxSetupNavItem\] : \[accountNavItem\]/, 'Admin Users navigation must remain admin-only')
assert.equal(operationsNavItems.some((item) => item.path === '/operations/guided-qm/vm-unlock'), false, 'Guided execution must use the retained contextual action instead of a history tab')
assert.match(navigation, /if \(items\.length < 2\) return null/, 'A single Settings destination must not produce a redundant subnav')
assert.match(app, /function AdminGuard/, 'Direct admin route access must be guarded')
assert.match(app, /path="\/jobs"\s+element=\{jobsRoute\}/, 'Legacy Jobs alias must direct-render so query strings are preserved')
assert.match(app, /visiblePrimaryNavItems/, 'Unavailable Proxmox navigation must be hidden')
assert.match(app, /isProxmoxInventoryAvailable/, 'Partial authoritative inventory must keep read navigation available')
assert.match(app, /<InsightsPage category=\{category\}/, 'Insights routes must compose the dedicated page boundary')
assert.doesNotMatch(app, /operationalRoute\(\s*insightsRoute/, 'Insights must remain visible for partial source availability')
assert.doesNotMatch(app, /path="\/(?:drs|instances\/drs-policies)"/, 'Removed DRS URLs must follow the unknown-path fallback')
assert.match(app, /<Route path="\*" element=\{<Navigate to="\/" replace \/>\} \/>/, 'Authenticated unknown paths must continue to redirect to Overview')
assert.match(app, /inventoryRoute\(<Dashboard \/>\)/, 'Dashboard must accept readable partial inventory')
assert.match(app, /const createVmRoute = \(\s*inventoryRoute\(/, 'Create input must accept partial inventory')
assert.match(app, /<CreateVmPage currentUser=\{currentUser\} canExecuteLiveMutation=\{canOperate\(currentUser\)\}/, 'Create review permissions must not depend on unrelated guest observation')
assert.match(app, /canOperate\(currentUser\) && proxmoxOperational/, 'Mutation affordances must require role and live connection truth')
assert.doesNotMatch(app, /from ['"]\.\.\/components\//, 'App layer must compose pages rather than legacy screen components')
assert.doesNotMatch(app, /from ['"]\.\.\/(?:services|utils)\//, 'App layer must use shared public modules')

assert.match(navigation, /APP_SHELL_CLASS = 'mx-auto w-full max-w-7xl px-4 sm:px-8'/, 'Authenticated layout must define one responsive shell width')
assert.ok(shell.includes('<div className={`${APP_SHELL_CLASS} py-4 sm:py-5`}>'), 'Header must use shared shell width')
assert.ok(shell.includes('<div className={APP_SHELL_CLASS}>'), 'Primary navigation must use shared shell width')
assert.ok(shell.includes('<main id="main-content" className={`${APP_SHELL_CLASS} py-6 sm:py-8`}>'), 'Main content must use shared shell width')
assert.match(shell, /Skip to main content/, 'Authenticated shell must expose a keyboard skip link')
assert.match(shell, />Gjallar</, 'App shell must lead with the current product identity')
assert.match(shell, /Observe-first Operations Intelligence · Verified Actions/, 'App shell must state the observe-first identity')
assert.doesNotMatch(shell, /Gjallar Operations Console|Proxmox VM 운영 관리/, 'App shell must not revive the old console-only identity')
assert.match(workloadPage, /WorkloadInventory/, 'Workload Cockpit page must consume the workload feature boundary')
assert.match(vmDetailPage, /VmDetail/, 'VM detail page must consume the exact workload detail feature boundary')

assert.match(dashboard, /cpu_usage_percent/, 'Dashboard must prefer live Proxmox CPU usage')
assert.match(dashboard, /memory_usage_percent/, 'Dashboard must prefer live Proxmox memory usage')
assert.match(dashboard, /Promise\.allSettled/, 'Dashboard must preserve partial inventory on adjacent query failure')
assert.match(dashboard, /사용 가능한 inventory 데이터는 계속 표시합니다/, 'Dashboard must explain partial failures')
assert.match(dashboard, /Node inventory \{model\.summary\.nodeStatus\}/, 'Dashboard must report observed node availability')
assert.doesNotMatch(dashboard, /quorum|Cluster \{model\.summary\./i, 'Dashboard must not infer Proxmox quorum from node reachability')
assert.doesNotMatch(dashboard, /실시간/, 'Dashboard must not describe request-time inventory as real-time data')
assert.doesNotMatch(dashboard, /Current read-only observation/, 'Dashboard must not label preserved fallback snapshots as current')
assert.doesNotMatch(dashboard, /cpuAllocated|memoryAllocatedGb|CPU alloc|Memory alloc/, 'Dashboard must not revive allocated-resource fallbacks')
assert.match(dashboard, /redRisks === null \? '-' :/, 'Unavailable Risks must not render as zero')
assert.match(dashboard, /risks unavailable/, 'Dashboard must identify unavailable Risk context')
assert.match(dashboard, /activeJobs === null \? 'jobs unavailable'/, 'Unavailable Jobs must not render as zero')
assert.match(dashboard, /label="Red risks"/, 'Dashboard must name the metric as the red-risk count it actually reports')
assert.match(dashboard, /redRisks > 0 \? 'red' : 'slate'/, 'A zero legacy Risk response must remain neutral rather than green')
for (const source of ['jobs', 'risks']) {
  assert.ok(dashboard.includes(`${source}: ${source}.status === 'fulfilled'`), `Dashboard must track ${source} source availability`)
}
for (const source of ['cluster', 'nodes', 'vms']) {
  assert.ok(dashboard.includes(`${source}: inventoryResultAvailable(${source})`), `Dashboard must require availability meta for ${source}`)
}
assert.match(dashboard, /storages: inventorySourceComplete\(storages, 'storage'\)/, 'Dashboard must not trust incomplete storage observation')
assert.match(dashboard, /networks: inventorySourceComplete\(networks, 'network'\)/, 'Dashboard must not trust incomplete network observation')
assert.match(dashboard, /node\.vmsAvailable \?/, 'Unavailable VM inventory must not render retained per-node counts')
assert.match(dashboard, /node\.networksAvailable \?/, 'Unavailable Network inventory must not render retained bridges')
assert.match(dashboard, /node\.storagesAvailable \?/, 'Unavailable Storage inventory must not render retained capacity')

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
