import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { jsx, jsxs } from 'react/jsx-runtime'

function compileDashboardSource(source) {
  return source
    .replace(
      /import\s+\{\s*useEffect,\s*useMemo,\s*useState\s*\}\s+from\s+'react'/,
      'const { useEffect, useMemo, useState } = globalThis.__DASHBOARD_TEST_MOCKS__.react'
    )
    .replace(
      /import\s+\{\s*useNavigate\s*\}\s+from\s+'react-router-dom'/,
      'const { useNavigate } = globalThis.__DASHBOARD_TEST_MOCKS__.router'
    )
    .replace(
      /import\s+\{[\s\S]*?\}\s+from\s+'lucide-react'/,
      `const {
  Activity,
  AlertTriangle,
  Clock3,
  Database,
  HardDrive,
  List,
  Network,
  Plus,
  RefreshCw,
  Server,
} = globalThis.__DASHBOARD_TEST_MOCKS__.icons`
    )
    .replace(
      /import\s+\{\s*apiV1Client\s*\}\s+from\s+'\.\.\/\.\.\/shared\/api\/apiV1'/,
      'const { apiV1Client } = globalThis.__DASHBOARD_TEST_MOCKS__.api'
    )
    .replace('function buildDashboardModel(', 'export function buildDashboardModel(')
}

function loadCommonJsModule(code, filename) {
  const module = { exports: {} }
  const dirname = path.dirname(filename)
  const localRequire = (specifier) => {
    if (specifier === 'react/jsx-runtime') return { jsx, jsxs, Fragment: Symbol.for('react.fragment') }
    throw new Error(`Unexpected require in compiled Dashboard test module: ${specifier}`)
  }
  const script = new vm.Script(`(function (exports, require, module, __filename, __dirname, globalThis) {${code}\n})`, {
    filename,
  })
  script.runInThisContext()(module.exports, localRequire, module, filename, dirname, globalThis)
  return module.exports
}

const icon = () => null
globalThis.__DASHBOARD_TEST_MOCKS__ = {
  react: {
    useEffect: () => {},
    useMemo: (factory) => factory(),
    useState: (initialValue) => [initialValue, () => {}],
  },
  router: { useNavigate: () => () => {} },
  icons: {
    Activity: icon,
    AlertTriangle: icon,
    Clock3: icon,
    Database: icon,
    HardDrive: icon,
    List: icon,
    Network: icon,
    Plus: icon,
    RefreshCw: icon,
    Server: icon,
  },
  api: { apiV1Client: {} },
}

const sourcePath = new URL('../src/pages/dashboard/DashboardPage.jsx', import.meta.url)
const compiled = transformSync(compileDashboardSource(readFileSync(sourcePath, 'utf8')), {
  loader: 'jsx',
  format: 'cjs',
  jsx: 'automatic',
}).code
const { buildDashboardModel } = loadCommonJsModule(compiled, String(sourcePath))

const observedSnapshot = {
  cluster: { cluster_id: 'cluster-a' },
  nodes: [{
    node_id: 'node-a',
    display_name: 'Node A',
    status: 'online',
    cpu_usage_percent: 20,
    memory_usage_percent: 30,
    memory_total_mb: 8192,
    memory_used_mb: 2048,
  }],
  vms: [{ vmid: 101, node_id: 'node-a', status: 'running' }],
  storages: [{ node_id: 'node-a', type: 'nfs', total_gb: 100, free_gb: 60 }],
  networks: [{ node_id: 'node-a', bridge_id: 'vmbr0' }],
  jobs: [{ status: 'running' }],
  risks: [{ level: 'red' }],
  availability: {
    cluster: true,
    nodes: true,
    vms: true,
    storages: true,
    networks: true,
    jobs: true,
    risks: true,
  },
  observation: {
    available: true,
    complete: true,
    sources: {
      storage: { available: true, complete: true },
      network: { available: true, complete: true },
      vm_config: { available: true, complete: true },
      guest_agent: { available: true, complete: true },
      vm_detail: { available: true, complete: true },
    },
  },
}

const observedModel = buildDashboardModel(observedSnapshot)
assert.equal(observedModel.clusterId, 'cluster-a')
assert.equal(observedModel.summary.nodes, '1/1')
assert.equal(observedModel.summary.nodeStatus, '1/1 online')
assert.equal(observedModel.summary.allObservedNodesOnline, true)
assert.equal(observedModel.summary.vms, '1')
assert.equal(observedModel.summary.runningVms, 1)
assert.equal(observedModel.summary.storage, 'NFS')
assert.equal(observedModel.summary.bridges, 1)
assert.equal(observedModel.summary.activeJobs, 1)
assert.equal(observedModel.summary.redRisks, 1)
assert.equal(observedModel.nodeRows[0].vmCount, 1)
assert.equal(observedModel.summary.observationComplete, true)
assert.deepEqual(observedModel.summary.incompleteSources, [])

const failedRefreshModel = buildDashboardModel({
  ...observedSnapshot,
  availability: {
    cluster: false,
    nodes: false,
    vms: false,
    storages: false,
    networks: false,
    jobs: false,
    risks: false,
  },
})
assert.equal(failedRefreshModel.clusterId, 'unavailable')
assert.equal(failedRefreshModel.nodeRows.length, 0, 'Preserved Node rows must not look current after a failed refresh')
assert.equal(failedRefreshModel.summary.nodes, '-')
assert.equal(failedRefreshModel.summary.nodeStatus, 'unavailable')
assert.equal(failedRefreshModel.summary.allObservedNodesOnline, false)
assert.equal(failedRefreshModel.summary.vms, '-')
assert.equal(failedRefreshModel.summary.runningVms, null)
assert.equal(failedRefreshModel.summary.storage, '-')
assert.equal(failedRefreshModel.summary.storageSub, 'storage unavailable')
assert.equal(failedRefreshModel.summary.bridges, null)
assert.equal(failedRefreshModel.summary.activeJobs, null)
assert.equal(failedRefreshModel.summary.redRisks, null)

const partialRefreshModel = buildDashboardModel({
  ...observedSnapshot,
  availability: {
    ...observedSnapshot.availability,
    vms: false,
    storages: false,
    networks: false,
  },
})
assert.equal(partialRefreshModel.nodeRows.length, 1)
assert.equal(partialRefreshModel.nodeRows[0].vmCount, null)
assert.equal(partialRefreshModel.nodeRows[0].vmsAvailable, false)
assert.equal(partialRefreshModel.nodeRows[0].storagesAvailable, false)
assert.equal(partialRefreshModel.nodeRows[0].networksAvailable, false)

const incompleteObservationModel = buildDashboardModel({
  ...observedSnapshot,
  availability: {
    ...observedSnapshot.availability,
    storages: false,
  },
  observation: {
    available: true,
    complete: false,
    sources: {
      storage: { available: false, complete: false, failed_targets: ['node-a'] },
      network: { available: true, complete: true },
      vm_config: { available: true, complete: false, failed_targets: ['node-a:101'] },
      guest_agent: { available: false, complete: false, failed_targets: ['node-a:101'] },
      vm_detail: { available: true, complete: true },
    },
  },
})
assert.equal(incompleteObservationModel.summary.observationComplete, false)
assert.deepEqual(incompleteObservationModel.summary.incompleteSources, ['storage', 'vm_config', 'guest_agent'])
assert.equal(incompleteObservationModel.summary.storage, '-', 'Incomplete storage observation must not look like a valid empty total')

const dashboardSource = readFileSync(sourcePath, 'utf8')
assert.match(dashboardSource, /clusterSummaryWithMeta/)
assert.match(dashboardSource, /listStorageWithMeta/)
assert.match(dashboardSource, /listNetworksWithMeta/)
assert.match(dashboardSource, /meta\?\.availability/)

delete globalThis.__DASHBOARD_TEST_MOCKS__

console.log('dashboard source availability contract exercised')
