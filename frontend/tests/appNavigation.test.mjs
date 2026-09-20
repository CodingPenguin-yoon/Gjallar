import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import {
  primaryNavItems,
  overviewNavItems,
  templateNavItems,
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

for (const label of ['전체 현황', 'VM 관리', '템플릿', '모니터링', '인프라', '작업 이력']) {
  assert.ok(navigation.includes(`label: '${label}'`), `Primary navigation must expose ${label}`)
}
for (const label of ['VM 목록', 'VM 생성', '실행 작업', '생성 이력', '상태 요약', '위험 진단', 'VM 준비 상태', '가용 용량', '배치 진단', '내 계정', '사용자·세션']) {
  assert.ok(navigation.includes(label), `Section navigation must expose ${label}`)
}
assert.doesNotMatch(navigation, /label: 'Network readiness'/, 'Retired network comparison must not remain a navigation item')
assert.doesNotMatch(navigation, /label: 'DRS Advisor'/, 'DRS must not remain a primary product navigation item')
assert.doesNotMatch(navigation, /label: 'DRS Policies'/, 'DRS Policies must not remain a Workloads navigation item')

for (const [items, pathname, expectedLabel] of [
  [overviewNavItems, '/', '클러스터 전체'],
  [overviewNavItems, '/nodes', '노드 상세'],
  [primaryNavItems, '/nodes', '전체 현황'],
  [workloadNavItems, '/instances', 'VM 목록'],
  [workloadNavItems, '/instances/306', 'VM 목록'],
  [templateNavItems, '/instances/templates/build', '공식 이미지 제작'],
  [templateNavItems, '/instances/templates/cleanup', '제작 자원 정리'],
  [templateNavItems, '/instances/templates/tests/operation-123', '공식 이미지 제작'],
  [workloadNavItems, '/instances/templates-other', 'VM 목록'],
  [workloadNavItems, '/instances/create', 'VM 생성'],
  [workloadNavItems, '/infra', 'VM 목록'],
  [workloadNavItems, '/create', 'VM 생성'],
  [insightsNavItems, '/insights', '상태 요약'],
  [insightsNavItems, '/insights/risks', '위험 진단'],
  [insightsNavItems, '/insights/readiness', 'VM 준비 상태'],
  [insightsNavItems, '/insights/capacity', '가용 용량'],
  [insightsNavItems, '/insights/placement', '배치 진단'],
  [operationsNavItems, '/operations', '실행 작업'],
  [operationsNavItems, '/operations/operation-123', '실행 작업'],
  [operationsNavItems, '/operations/jobs', '생성 이력'],
  [operationsNavItems, '/jobs', '생성 이력'],
  [operationsNavItems, '/operations/guided-qm/vm-unlock', '실행 작업'],
  [operationsNavItems, '/operations/risks', '실행 작업'],
  [operationsNavItems, '/risks', '실행 작업'],
  [[accountNavItem, adminNavItem], '/settings/account', '내 계정'],
  [[accountNavItem, adminNavItem], '/account', '내 계정'],
  [[accountNavItem, adminNavItem], '/settings/admin/users', '사용자·세션'],
  [[accountNavItem, adminNavItem], '/admin/users', '사용자·세션'],
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
  'path="/nodes"',
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

assert.match(navigation, /isAdmin \? \[accountNavItem, adminNavItem\] : \[accountNavItem\]/, 'Admin Users navigation must remain admin-only')
assert.equal(operationsNavItems.some((item) => item.path === '/operations/guided-qm/vm-unlock'), false, 'Guided execution must use the retained contextual action instead of a history tab')
assert.match(navigation, /if \(items\.length < 2\) return null/, 'A single Settings destination must not produce a redundant subnav')
assert.match(app, /function AdminGuard/, 'Direct admin route access must be guarded')
assert.match(app, /path="\/jobs"\s+element=\{jobsRoute\}/, 'Legacy Jobs alias must direct-render so query strings are preserved')
assert.match(app, /navItems=\{primaryNavItems\}/, 'Navigation remains stable while connection loads; route boundaries guard unavailable inventory')
assert.match(app, /const vmInventoryRoute = \(\s*inventoryRoute\(/, 'Inventory still passes through the existing connection boundary')
assert.match(app, /<InsightsPage category=\{category\}/, 'Insights routes must compose the dedicated page boundary')
assert.doesNotMatch(app, /operationalRoute\(\s*insightsRoute/, 'Insights must remain visible for partial source availability')
assert.doesNotMatch(app, /path="\/(?:drs|instances\/drs-policies)"/, 'Removed DRS URLs must follow the unknown-path fallback')
assert.match(app, /<Route path="\*" element=\{<Navigate to="\/" replace \/>\} \/>/, 'Authenticated unknown paths must continue to redirect to Overview')
assert.match(app, /inventoryRoute\(<OverviewShell><Dashboard \/><\/OverviewShell>\)/, 'Dashboard must accept readable partial inventory')
assert.match(app, /const createVmRoute = \(\s*inventoryRoute\(/, 'Create input must accept partial inventory')
assert.match(app, /<CreateVmPage currentUser=\{currentUser\} canExecuteLiveMutation=\{canOperate\(currentUser\)\}/, 'Create review permissions must not depend on unrelated guest observation')
assert.match(app, /canOperate\(currentUser\) && proxmoxOperational/, 'Mutation affordances must require role and live connection truth')
assert.doesNotMatch(app, /from ['"]\.\.\/components\//, 'App layer must compose pages rather than legacy screen components')
assert.doesNotMatch(app, /from ['"]\.\.\/(?:services|utils)\//, 'App layer must use shared public modules')

assert.match(navigation, /APP_SHELL_CLASS = 'mx-auto w-full max-w-\[1680px\] px-3 sm:px-5'/, 'Authenticated layout must define one responsive shell width')
assert.ok(shell.includes('<div className={`${APP_SHELL_CLASS} py-2`}>'), 'Header must use shared shell width')
assert.ok(shell.includes('<div className={APP_SHELL_CLASS}>'), 'Primary navigation must use shared shell width')
assert.ok(shell.includes('<main id="main-content" tabIndex={-1} className={`${APP_SHELL_CLASS} gj-content py-3 sm:py-4`}>'), 'Main content must use shared shell width')
assert.match(shell, /본문으로 바로가기/, 'Authenticated shell must expose a keyboard skip link')
assert.match(shell, />Gjallar</, 'App shell must lead with the current product identity')
assert.match(shell, /PROXMOX OPERATIONS/, 'App shell must state the observe-first identity')
assert.doesNotMatch(shell, /Gjallar Operations Console|Proxmox VM 운영 관리/, 'App shell must not revive the old console-only identity')
assert.match(workloadPage, /WorkloadInventory/, 'Workload Cockpit page must consume the workload feature boundary')
assert.match(vmDetailPage, /VmDetail/, 'VM detail page must consume the exact workload detail feature boundary')

assert.match(dashboard, /cpu_usage_percent/, 'Dashboard must prefer live Proxmox CPU usage')
assert.match(dashboard, /memory_usage_percent/, 'Dashboard must prefer live Proxmox memory usage')
assert.match(dashboard, /Promise\.allSettled/, 'Dashboard must preserve partial inventory on adjacent query failure')
assert.match(dashboard, /사용 가능한 inventory 데이터는 계속 표시합니다/, 'Dashboard must explain partial failures')
assert.match(dashboard, /model\.summary\.nodeStatus/, 'Dashboard must report observed node availability')
assert.doesNotMatch(dashboard, /quorum|Cluster \{model\.summary\./i, 'Dashboard must not infer Proxmox quorum from node reachability')
assert.doesNotMatch(dashboard, /실시간/, 'Dashboard must not describe request-time inventory as real-time data')
assert.doesNotMatch(dashboard, /Current read-only observation/, 'Dashboard must not label preserved fallback snapshots as current')
assert.doesNotMatch(dashboard, /cpuAllocated|memoryAllocatedGb|CPU alloc|Memory alloc/, 'Dashboard must not revive allocated-resource fallbacks')
assert.match(dashboard, /redRisks === null \? '-' :/, 'Unavailable Risks must not render as zero')
assert.match(dashboard, /위험 조회 불가/, 'Dashboard must identify unavailable Risk context')
assert.match(dashboard, /activeJobs === null \? '작업 조회 불가'/, 'Unavailable Jobs must not render as zero')
assert.match(dashboard, /label="위험 진단 · Red"/, 'Dashboard must name the metric as the red-risk count it actually reports')
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

for (const [path, expected] of [
  ['/', '전체 현황'], ['/instances/7001/backups', 'VM 관리'],
  ['/instances/templates/build', '템플릿'], ['/instances/templates/cleanup', '템플릿'],
  ['/instances/templates/tests/build-123', '템플릿'], ['/create', 'VM 관리'],
  ['/insights/alerts/', '모니터링'], ['/insights', '모니터링'],
  ['/insights/maintenance', '인프라'], ['/settings/proxmox', '인프라'],
  ['/settings/host-network', '인프라'], ['/settings/host-storage', '인프라'],
  ['/operations/jobs', '작업 이력'], ['/infra', 'VM 관리'],
]) {
  assert.deepEqual(resolveSectionNavItems(primaryNavItems, path).filter(item => item.isActive).map(item => item.label), [expected])
}
for (const path of ['/instances-other', '/settings/account', '/settings/admin/users', '/account', '/admin/users']) {
  assert.equal(resolveSectionNavItems(primaryNavItems, path).some(item => item.isActive), false)
}
assert.ok(insightsNavItems.every(item => ['관찰', '진단'].includes(item.group)))
assert.equal(insightsNavItems.some(item => item.path === '/insights/maintenance'), false)
assert.equal(workloadNavItems.some(item => item.path.startsWith('/instances/templates')), false)
assert.match(app, /<TemplatesShell><ImageBuildPage/, 'Template routes must use their own feature navigation')
assert.match(app, /<InfrastructureShell isAdmin=\{isAdmin\}><AdminGuard currentUser=\{currentUser\}><HostNetworkPage/, 'Infrastructure reorganization must retain admin guards')
assert.match(shell, /resolveSectionNavItems\(navItems, pathname\)/, 'Nested primary routes must resolve exactly one active tab')
const accountMenu = readFileSync(new URL('../src/app/AccountMenu.jsx', import.meta.url), 'utf8')
assert.match(accountMenu, /canAdmin\(currentUser\) \? \[accountNavItem, adminNavItem\] : \[accountNavItem\]/)
assert.match(accountMenu, /event.key === 'Escape'/)
