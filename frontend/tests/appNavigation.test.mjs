import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const srcRoot = new URL('../src', import.meta.url)
const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')

for (const label of ['Dashboard', 'Infra Explorer', 'Networks', 'Create VM', 'Placement', 'Jobs/Runs', 'Risks/Alerts']) {
  assert.ok(app.includes(label), `App navigation must expose PRD label: ${label}`)
}
for (const route of ['path="/infra"', 'path="/networks"', 'path="/create"', 'path="/placement"', 'path="/jobs"', 'path="/risks"']) {
  assert.ok(app.includes(route), `App routes must expose PRD route: ${route}`)
}
assert.doesNotMatch(app, /from ['"]\.\/services\/api(?:\.js)?['"]/, 'App must not import the legacy /api client')
assert.doesNotMatch(app, /LlmInfraChat|LLM Assistant|\/assistant|Sparkles/, 'LLM assistant must not be routed or shown in MVP nav')
assert.doesNotMatch(app, /provisionInstance|checkIpAvailability|handleProvision|provisioningRequest|onProvision|isProvisioning/, 'App must not own legacy provisioning execution flow')
assert.doesNotMatch(app, /Instance List|Task Board|Risk Dashboard|Monitoring/, 'App must use PRD v1 navigation labels only')
assert.match(app, /cpu_usage_percent/, 'Dashboard must prefer live Proxmox node CPU usage over allocated CPU counts')
assert.match(app, /memory_usage_percent/, 'Dashboard must prefer live Proxmox node memory usage over allocated memory')
assert.doesNotMatch(app, /cpuAllocated|memoryAllocatedGb|CPU alloc|Memory alloc/, 'Dashboard must not fall back to old allocated CPU or memory totals')
assert.match(app, /Promise\.allSettled/, 'Dashboard must keep rendering available inventory when jobs or risks fail')
assert.match(app, /사용 가능한 inventory 데이터는 계속 표시합니다/, 'Dashboard must show partial-failure copy instead of blanking the first screen')

const activeImports = app
  .split('\n')
  .map((line) => line.match(/^import\s+[^\n]+\s+from\s+['"](\.\/components\/[^'"]+)['"]/))
  .filter(Boolean)
  .map((match) => match[1])

assert.deepEqual(
  activeImports.sort(),
  [
    './components/CreateInstanceWizard',
    './components/InstanceList',
    './components/NetworkReadinessScreen',
    './components/OperationalRiskDashboard',
    './components/PlacementScreen',
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
