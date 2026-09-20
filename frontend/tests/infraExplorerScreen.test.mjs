import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { renderToStaticMarkup } from 'react-dom/server'
import { jsx, jsxs } from 'react/jsx-runtime'

async function importExpected(modulePath, description) {
  try {
    return await import(modulePath)
  } catch (error) {
    assert.fail(`Expected ${description} at ${modulePath}, but it is missing or invalid: ${error.message}`)
  }
}

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
      useRef(initialValue) {
        const index = cursor
        if (state[index] === undefined) state[index] = { current: initialValue }
        cursor += 1
        return state[index]
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
        await effect()
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

function compileInstanceListSource(source) {
  return source
    .replace(
      /import\s+\{\s*useEffect,\s*useRef,\s*useState\s*\}\s+from\s+'react'/,
      'const { useEffect, useRef, useState } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.reactHooks'
    )
    .replace(
      /import\s+\{\s*Link,\s*useNavigate,\s*useSearchParams\s*\}\s+from\s+'react-router-dom'/,
      'const { Link, useNavigate, useSearchParams } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.router'
    )
    .replace(
      /import\s+\{\s*([\s\S]*?)\s*\}\s+from\s+'lucide-react'/,
      `const {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  Network,
  Play,
  Power,
  Plus,
  RefreshCw,
  Server,
  Terminal,
} = globalThis.__INSTANCE_LIST_TEST_MOCKS__.icons`
    )
    .replace(
      /import\s+\{\s*apiV1Client\s*\}\s+from\s+'..\/..\/..\/shared\/api\/apiV1'/,
      'const { apiV1Client } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.api'
    )
    .replace(
      /import\s+\{\s*authFailureMessage\s*\}\s+from\s+'..\/..\/..\/shared\/auth\/permissions'/,
      'const { authFailureMessage } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.auth'
    )
    .replace(
      /import\s+\{\s*insightFindingPath,\s*normalizeVmid,\s*vmDetailPath\s*\}\s+from\s+'..\/..\/..\/shared\/navigation\/targetPaths'/,
      'const { insightFindingPath, normalizeVmid, vmDetailPath } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.targetPaths'
    )
    .replace(
      /import\s+\{\s*formatOperationTime,\s*operationStatusTone\s*\}\s+from\s+'\.\.\/\.\.\/\.\.\/entities\/operation\/model'/,
      'const { formatOperationTime, operationStatusTone } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.operation'
    )
    .replace(
      /import\s+\{\s*loadInfraExplorerModel,\s*operationIdFromActionError,\s*operationResultDestination,?\s*\}\s+from\s+'\.\/model'/,
      'const { loadInfraExplorerModel, operationIdFromActionError, operationResultDestination } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.loader'
    )
}

function findElement(node, predicate) {
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

const {
  buildWorkloadCockpitModel,
  loadInfraExplorerModel,
  operationIdFromActionError,
  operationResultDestination,
} = await importExpected(
  '../src/utils/infraExplorerScreen.js',
  'Infra Explorer screen loader'
)
const { formatOperationTime, operationStatusTone } = await importExpected(
  '../src/entities/operation/model.js',
  'Operation display helpers'
)
const { insightFindingPath, normalizeVmid, vmDetailPath } = await importExpected(
  '../src/shared/navigation/targetPaths.js',
  'Exact target navigation helpers'
)

const calls = []
const startCalls = []
const shutdownCalls = []
const operationLookups = []
const fakeClient = {
  async listNodesWithMeta() {
    calls.push('listNodesWithMeta')
    return {
      data: [
        { node_id: 'yoonmanserver2', name: 'yoonmanserver2', display_name: 'Yoonman Server 2', status: 'online' },
        { node_id: 'yoonmanserver3', name: 'yoonmanserver3', status: 'online' },
      ],
      meta: { source: 'live_read_only', observed_at: '2026-08-25T01:00:00Z', freshness: 'fresh' },
    }
  },
  async listVmsWithMeta() {
    calls.push('listVmsWithMeta')
    return {
      data: [{
        vmid: 141,
        name: 'app-01',
        node_id: 'yoonmanserver2',
        status: 'running',
        ip_addresses: ['172.17.0.1', '192.168.2.141', '172.18.0.1'],
        guest_agent: { available: true, ip_addresses: ['172.17.0.1', '192.168.2.141', '172.18.0.1'] },
        tags: ['owner:platform', 'env:dev'],
        cpu: 2,
        memory_mb: 4096,
        disk_gb: 40,
        storage_id: 'local-lvm',
        disks: [
          {
            device: 'scsi0',
            bus: 'scsi',
            index: 0,
            size_gb: 40,
            storage_id: 'local-lvm',
            volume_id: 'local-lvm:vm-141-disk-0',
            volume: 'vm-141-disk-0',
            boot: true,
            format: 'raw',
            discard: 'on',
          },
        ],
      }, {
        vmid: 142,
        name: 'stopped-app',
        node_id: 'yoonmanserver2',
        status: 'stopped',
        ip_addresses: [],
        guest_agent: { available: false, ip_addresses: [] },
        tags: ['owner:platform'],
        cpu: 2,
        memory_mb: 4096,
        disk_gb: 40,
        storage_id: 'local-lvm',
        disks: [],
      }],
      meta: { source: 'live_read_only', observed_at: '2026-08-25T01:00:01Z', freshness: 'fresh' },
    }
  },
  async getInsights() {
    calls.push('getInsights')
    return {
      generated_at: '2026-08-25T01:00:02Z',
      status: 'attention',
      sections: {
        readiness: {
          status: 'attention',
          available: true,
          source: 'live_read_only',
          observed_at: '2026-08-25T01:00:01Z',
          freshness: 'fresh',
          rule_version: 'operational-readiness.v1',
          summary: { finding_count: 250, returned_finding_count: 2, truncated: true },
          findings: [{
            finding_id: 'finding-vm-141',
            severity: 'warning',
            status: 'active',
            code: 'guest_agent_unavailable',
            title: 'app-01 readiness',
            message: 'Guest-agent evidence needs review.',
            target: { type: 'proxmox_vm', id: 'vmid:141' },
            source: 'live_read_only',
            observed_at: '2026-08-25T01:00:01Z',
            freshness: 'fresh',
            rule_version: 'operational-readiness.v1',
            evidence: { vmid: 141 },
          }, {
            finding_id: 'finding-vm-999',
            severity: 'critical',
            status: 'active',
            code: 'unrelated_workload',
            title: 'another workload readiness',
            message: 'This finding belongs to another VM.',
            target: { type: 'proxmox_vm', id: 'vmid:999' },
            source: 'live_read_only',
            observed_at: '2026-08-25T01:00:01Z',
            freshness: 'fresh',
            rule_version: 'operational-readiness.v1',
            evidence: { vmid: 999 },
          }],
        },
        placement: {
          status: 'attention',
          available: true,
          source: 'drs_advisor',
          observed_at: '2026-08-25T00:59:00Z',
          freshness: 'recorded',
          rule_version: 'placement.v1',
          summary: { finding_count: 1 },
          findings: [{
            finding_id: 'placement-vm-141',
            severity: 'critical',
            status: 'active',
            code: 'placement_pressure',
            title: 'app-01 placement pressure',
            message: 'Placement evidence needs review.',
            target: { type: 'proxmox_vm', id: 'vmid:141' },
            source: 'drs_advisor',
            observed_at: '2026-08-25T00:59:00Z',
            freshness: 'recorded',
            rule_version: 'placement.v1',
            evidence: { vmid: 141 },
          }],
        },
      },
    }
  },
  async listOperations(filters) {
    calls.push(`listOperations:${filters.limit}`)
    return [{
      operation_id: 'vm-start-older-141',
      operation_type: 'vm_start',
      execution_mode: 'managed_api',
      status: 'succeeded',
      target_type: 'proxmox_vm',
      target_id: 'vmid:141',
      updated_at: '2026-08-25T00:58:00Z',
    }, {
      operation_id: 'vm-shutdown-existing-141',
      operation_type: 'vm_shutdown',
      execution_mode: 'managed_api',
      status: 'succeeded',
      target_type: 'proxmox_vm',
      target_id: 'vmid:141',
      updated_at: '2026-08-25T01:02:00Z',
    }]
  },
  async getOperation(operationId) {
    operationLookups.push(operationId)
    return { operation: { operation_id: operationId } }
  },
  async startVm(nodeId, vmid, payload) {
    startCalls.push({ nodeId, vmid, payload })
    return { job_id: 'vm-start-node-a-142' }
  },
  async shutdownVm(nodeId, vmid, payload) {
    shutdownCalls.push({ nodeId, vmid, payload })
    return { job_id: 'vm-shutdown-node-a-141' }
  },
  async getInstances() {
    calls.push('getInstances')
    throw new Error('legacy getInstances must not be called')
  },
  async getServers() {
    calls.push('getServers')
    throw new Error('legacy getServers must not be called')
  },
}

const model = await loadInfraExplorerModel(fakeClient)
assert.deepEqual(calls.sort(), ['getInsights', 'listNodesWithMeta', 'listOperations:200', 'listVmsWithMeta'])
assert.equal(model.readOnly, true)
assert.deepEqual(model.allowedActions, [])
assert.equal(model.summary.totalNodes, 2)
assert.equal(model.summary.totalVms, 2)
assert.equal(model.summary.visibleIpCount, 1)
assert.equal(model.summary.guestAgentCount, 1)
assert.equal(model.nodes[0].name, 'Yoonman Server 2')
assert.equal(model.nodes[0].vms[0].name, 'app-01')
assert.equal(model.nodes[0].vms[0].readOnly, true)
assert.deepEqual(model.nodes[0].vms[0].allowedActions, ['shutdown'])
assert.equal(model.nodes[0].vms[1].name, 'stopped-app')
assert.deepEqual(model.nodes[0].vms[1].allowedActions, ['start'])
assert.equal(model.nodes[0].vms[0].storageId, 'local-lvm')
assert.equal(model.nodes[0].vms[0].disks[0].device, 'scsi0')
assert.equal(model.nodes[0].vms[0].disks[0].storageId, 'local-lvm')
assert.equal(model.nodes[0].vms[0].disks[0].volume, 'vm-141-disk-0')
assert.equal(model.nodes[0].vms[0].guestAgent.available, true)
assert.equal(model.nodes[0].vms[0].primaryIp, '192.168.2.141')
assert.deepEqual(model.nodes[0].vms[0].hiddenIpAddresses, ['172.17.0.1', '172.18.0.1'])
assert.equal(model.nodes[0].vms[0].hiddenIpCount, 2)
assert.deepEqual(model.observations, [
  { scope: 'Nodes', source: 'live_read_only', observedAt: '2026-08-25T01:00:00Z', freshness: 'fresh' },
  { scope: 'VMs', source: 'live_read_only', observedAt: '2026-08-25T01:00:01Z', freshness: 'fresh' },
])
assert.equal(model.context.insightsAvailable, true)
assert.equal(model.context.insightsStatus, 'available')
assert.deepEqual(model.context.unavailableInsightCategories, [])
assert.deepEqual(model.context.uncertainInsightCategories, [])
assert.equal(model.context.insightsTruncated, true)
assert.deepEqual(model.context.truncatedInsightCategories, ['readiness'])
assert.equal(model.context.operationsAvailable, true)
assert.equal(model.context.operationsStatus, 'available')
assert.equal(model.context.operationWindow, 200)
assert.equal(model.summary.relatedFindingCount, 2)
assert.equal(model.summary.workloadsWithRecentOperations, 1)
assert.deepEqual(model.nodes[0].vms[0].relatedFindings.map((finding) => finding.id), [
  'placement-vm-141',
  'finding-vm-141',
])
assert.equal(model.nodes[0].vms[0].recentOperation.id, 'vm-shutdown-existing-141')
assert.equal(model.nodes[0].vms[1].relatedFindings.length, 0)
assert.equal(model.nodes[0].vms[1].recentOperation, null)

const degradedModel = await loadInfraExplorerModel({
  ...fakeClient,
  async getInsights() {
    throw new Error('Insights unavailable')
  },
  async listOperations() {
    throw new Error('Operations unavailable')
  },
})
assert.equal(degradedModel.summary.totalVms, 2, 'Optional context failures must not hide inventory')
assert.equal(degradedModel.context.insightsAvailable, false)
assert.equal(degradedModel.context.insightsStatus, 'unavailable')
assert.deepEqual(degradedModel.context.unavailableInsightCategories, ['readiness', 'placement'])
assert.equal(degradedModel.context.operationsAvailable, false)
assert.equal(degradedModel.summary.relatedFindingCount, 0)
assert.equal(degradedModel.summary.workloadsWithRecentOperations, 0)

const partialInsightsModel = buildWorkloadCockpitModel({
  insights: {
    sections: {
      readiness: {
        status: 'ready', available: true, source: 'live_read_only', observed_at: '2026-08-25T01:00:00Z',
        freshness: 'fresh', rule_version: 'operational-readiness.v1', summary: { finding_count: 0 }, findings: [],
      },
      placement: {
        status: 'unavailable', available: false, source: 'unavailable', observed_at: null,
        freshness: 'unavailable', rule_version: 'placement.v1', summary: { finding_count: 0 }, findings: [],
      },
    },
  },
})
assert.equal(partialInsightsModel.context.insightsAvailable, false)
assert.equal(partialInsightsModel.context.insightsStatus, 'partial')
assert.deepEqual(partialInsightsModel.context.unavailableInsightCategories, ['placement'])
assert.deepEqual(partialInsightsModel.context.uncertainInsightCategories, [])

const uncertainInsightsModel = buildWorkloadCockpitModel({
  insights: {
    sections: {
      readiness: {
        status: 'unknown', available: true, source: 'live_read_only', observed_at: '2026-08-25T01:00:00Z',
        freshness: 'fresh', rule_version: 'operational-readiness.v1', summary: { finding_count: 0 }, findings: [],
      },
      placement: {
        status: 'ready', available: true, source: 'drs_advisor', observed_at: '2026-08-25T01:00:00Z',
        freshness: 'recorded', rule_version: 'placement.v1', summary: { finding_count: 0 }, findings: [],
      },
    },
  },
})
assert.equal(uncertainInsightsModel.context.insightsAvailable, false)
assert.equal(uncertainInsightsModel.context.insightsStatus, 'partial')
assert.deepEqual(uncertainInsightsModel.context.unavailableInsightCategories, [])
assert.deepEqual(uncertainInsightsModel.context.uncertainInsightCategories, ['readiness'])

const canonicalDestination = await operationResultDestination({
  async getOperation() {
    return { operation: { operation_id: 'op/a' } }
  },
}, 'op/a')
assert.deepEqual(canonicalDestination, {
  path: '/operations/op%2Fa',
  compatibilityFallback: false,
})

const notFoundError = new Error('Operation not found')
notFoundError.status = 404
const compatibilityDestination = await operationResultDestination({
  async getOperation() {
    throw notFoundError
  },
}, 'legacy/a')
assert.deepEqual(compatibilityDestination, {
  path: '/operations/jobs?job=legacy%2Fa&compatibility=operation',
  compatibilityFallback: true,
})

const lookupError = new Error('Operation API unavailable')
lookupError.status = 500
const unavailableDestination = await operationResultDestination({
  async getOperation() {
    throw lookupError
  },
}, 'op-500')
assert.equal(unavailableDestination.path, null)
assert.equal(unavailableDestination.compatibilityFallback, false)
assert.equal(unavailableDestination.lookupError, lookupError)
assert.equal(operationIdFromActionError({ details: { operation_id: 'op-direct' } }), 'op-direct')
assert.equal(operationIdFromActionError({ details: { details: { job_id: 'op-nested' } } }), 'op-nested')

let resolveInsights
let resolveOperations
let presentedInventory = null
const pendingInsights = new Promise((resolve) => {
  resolveInsights = resolve
})
const pendingOperations = new Promise((resolve) => {
  resolveOperations = resolve
})
const progressiveLoad = loadInfraExplorerModel({
  async listNodesWithMeta() {
    return { data: [], meta: { source: 'live_read_only', observed_at: '2026-08-25T02:00:00Z', freshness: 'fresh' } }
  },
  async listVmsWithMeta() {
    return { data: [], meta: { source: 'live_read_only', observed_at: '2026-08-25T02:00:01Z', freshness: 'fresh' } }
  },
  getInsights() {
    return pendingInsights
  },
  listOperations() {
    return pendingOperations
  },
}, {
  onInventoryLoaded(nextModel) {
    presentedInventory = nextModel
  },
})

await new Promise((resolve) => setImmediate(resolve))
assert.ok(presentedInventory, 'Required inventory must render before optional context settles')
assert.equal(presentedInventory.context.insightsStatus, 'loading')
assert.equal(presentedInventory.context.operationsStatus, 'loading')

resolveInsights({
  sections: {
    readiness: {
      status: 'ready', available: true, source: 'live_read_only', observed_at: '2026-08-25T02:00:01Z',
      freshness: 'fresh', rule_version: 'operational-readiness.v1', summary: { finding_count: 0 }, findings: [],
    },
    placement: {
      status: 'ready', available: true, source: 'drs_advisor', observed_at: '2026-08-25T02:00:01Z',
      freshness: 'recorded', rule_version: 'placement.v1', summary: { finding_count: 0 }, findings: [],
    },
  },
})
resolveOperations([])
const progressiveModel = await progressiveLoad
assert.equal(progressiveModel.context.insightsStatus, 'available')
assert.equal(progressiveModel.context.operationsStatus, 'available')

const timedOutContextModel = await loadInfraExplorerModel({
  async listNodesWithMeta() {
    return { data: [], meta: {} }
  },
  async listVmsWithMeta() {
    return { data: [], meta: {} }
  },
  getInsights() {
    return new Promise(() => {})
  },
  listOperations() {
    return new Promise(() => {})
  },
}, { contextTimeoutMs: 5 })
assert.equal(timedOutContextModel.context.insightsStatus, 'unavailable')
assert.equal(timedOutContextModel.context.operationsStatus, 'unavailable')

const sourcePath = new URL('../src/features/workloads/inventory/WorkloadInventory.jsx', import.meta.url)
const instanceListSource = readFileSync(sourcePath, 'utf8')
assert.match(instanceListSource, /apiV1Client/)
assert.match(instanceListSource, /loadInfraExplorerModel/)
assert.match(instanceListSource, /useNavigate/)
assert.match(instanceListSource, /apiV1Client\.startVm/)
assert.match(instanceListSource, /apiV1Client\.shutdownVm/)
assert.match(instanceListSource, /operationResultDestination\(apiV1Client,/)
assert.match(instanceListSource, /unknown\/stale:/, 'Unknown or stale Insight sections must not render as a healthy zero')
assert.match(instanceListSource, /Retry Operation detail/, 'Temporary Operation lookup failures must retain a visible retry path')
assert.match(instanceListSource, /operationIdFromActionError\(error\)/, 'Recorded action errors with an Operation id must use the common detail handoff')
assert.match(instanceListSource, /formatOperationTime\(recentOperation\.updatedAt \|\| recentOperation\.createdAt\)/)
assert.match(instanceListSource, /operationStatusTone\(recentOperation\.status\)/)
assert.match(instanceListSource, /canMutateVms/)
assert.doesNotMatch(instanceListSource, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'InstanceList must not import the legacy /api client')
assert.match(
  instanceListSource,
  /<table className="[^"]*table-fixed[^"]*"/,
  'InstanceList VM table must use fixed table layout'
)
const tableColumns = [...instanceListSource.matchAll(/<col className="w-\[(\d+)%\]/g)].map(match => Number(match[1]))
assert.equal(tableColumns.length, 8, 'VM table keeps all eight information columns')
assert.equal(tableColumns.reduce((sum, width) => sum + width, 0), 100)
assert.ok(tableColumns[1] >= 10 && tableColumns[4] >= 9, 'Status and memory columns have readable widths')
assert.match(
  instanceListSource,
  /function DiskStack\(\{ vm \}\)/,
  'InstanceList must render disk detail rows with a dedicated disk stack'
)
assert.match(
  instanceListSource,
  /function IpStack\(\{ vm \}\)/,
  'InstanceList must render guest IP evidence with a dedicated IP stack'
)
assert.match(
  instanceListSource,
  /hiddenIpCount/,
  'InstanceList must collapse secondary IP evidence behind a count'
)
assert.match(
  instanceListSource,
  /setExpanded\(\(current\) => !current\)/,
  'InstanceList IP count must toggle the collapsed IP details'
)
assert.match(
  instanceListSource,
  /function SignalStack\(\{ vm \}\)/,
  'InstanceList must render guest-agent and storage signals'
)
assert.match(
  instanceListSource,
  /<div className="truncate font-medium text-slate-950" title=\{vm\.name\}>/,
  'InstanceList VM name must truncate without expanding the column'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-slate-600" title=\{vmIpLabel\}>[\s\S]*?<IpStack vm=\{vm\} \/>/,
  'InstanceList IP cell must render guest IP evidence without expanding the column'
)
assert.match(
  instanceListSource,
  /const cpuLabel = formatNumber\(vm\.cpuCores\)/,
  'InstanceList must build a CPU display label inside the VM row map'
)
assert.match(
  instanceListSource,
  /const memoryLabel = formatGb\(vm\.memoryGb\)/,
  'InstanceList must build a Memory display label inside the VM row map'
)
assert.match(
  instanceListSource,
  /const diskLabel = vm\.disks\.length > 0[\s\S]*?: formatGb\(vm\.diskGb\)/,
  'InstanceList must build a Disk display label inside the VM row map'
)
assert.match(
  instanceListSource,
  /<DiskStack vm=\{vm\} \/>/,
  'InstanceList must render disk devices, sizes, storage and volume details'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-right text-slate-600" title=\{cpuLabel\}>[\s\S]*?<div className="truncate">{cpuLabel}<\/div>/,
  'InstanceList CPU cell must truncate without expanding the column'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-right text-slate-600" title=\{memoryLabel\}>[\s\S]*?<div className="truncate">{memoryLabel}<\/div>/,
  'InstanceList Memory cell must truncate without expanding the column'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-slate-600" title=\{diskLabel\}>[\s\S]*?<DiskStack vm=\{vm\} \/>/,
  'InstanceList Disk cell must render a stable disk stack without expanding the column'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-slate-600">[\s\S]*?<WorkloadContextStack vm=\{vm\} navigate=\{navigate\} \/>/,
  'InstanceList Signals cell must combine inventory signals with workload findings and Operations'
)

const compiled = transformSync(compileInstanceListSource(instanceListSource), {
  loader: 'jsx',
  format: 'cjs',
  jsx: 'automatic',
}).code

const hookHarness = createHookHarness()
const navigateCalls = []
globalThis.__INSTANCE_LIST_TEST_MOCKS__ = {
  reactHooks: hookHarness.hooks,
  router: {
    Link: ({ to, children, ...props }) => jsx('a', { ...props, href: to, children }),
    useNavigate: () => (path) => navigateCalls.push(path),
    useSearchParams: () => [new URLSearchParams(), () => {}],
  },
  icons: {
    AlertTriangle: icon('AlertTriangle'),
    ChevronDown: icon('ChevronDown'),
    ChevronRight: icon('ChevronRight'),
    Loader2: icon('Loader2'),
    Network: icon('Network'),
    Play: icon('Play'),
    Power: icon('Power'),
    Plus: icon('Plus'),
    RefreshCw: icon('RefreshCw'),
    Server: icon('Server'),
    Terminal: icon('Terminal'),
  },
  api: { apiV1Client: fakeClient },
  auth: { authFailureMessage: (error, fallback) => error?.message || fallback },
  targetPaths: { insightFindingPath, normalizeVmid, vmDetailPath },
  operation: { formatOperationTime, operationStatusTone },
  loader: {
    loadInfraExplorerModel: async () => model,
    operationIdFromActionError,
    operationResultDestination,
  },
}

const compiledModule = loadCommonJsModule(compiled, String(sourcePath))
const InstanceList = compiledModule.default

hookHarness.beginRender()
InstanceList({})
await hookHarness.flushEffects()

hookHarness.beginRender()
let tree = InstanceList({})
let html = renderToStaticMarkup(tree)

assert.match(html, /가상머신/)
assert.match(html, /대상을 선택해 필요한 작업/)
assert.match(html, /새로고침/)
assert.match(html, /Yoonman Server 2/)
assert.match(html, /yoonmanserver3/)
assert.match(html, /2 instances/)
assert.match(html, /0 instances/)
assert.match(html, /aria-expanded="true"/)
assert.match(html, /data-icon="ChevronDown"/)
assert.match(html, /Online/)
assert.match(html, /app-01/)
assert.match(html, /VMID 141/)
assert.match(html, /stopped-app/)
assert.match(html, /VMID 142/)
assert.match(html, /aria-label="Start stopped-app"/)
assert.match(html, /data-icon="Play"/)
assert.match(html, /aria-label="Gracefully shut down app-01"/)
assert.match(html, /data-icon="Power"/)
assert.match(html, /192\.168\.2\.141/)
assert.match(html, />\+2</)
assert.match(html, /aria-label="Show 2 additional IP addresses"/)
assert.doesNotMatch(html, /172\.17\.0\.1/)
assert.doesNotMatch(html, /172\.18\.0\.1/)
assert.match(html, /owner:platform/)
assert.match(html, /env:dev/)
assert.match(html, /running \/ total/)
assert.match(html, /IP visibility/)
assert.match(html, /Guest agent/)
assert.match(html, /Nodes observation/)
assert.match(html, /VMs observation/)
assert.match(html, /live_read_only · fresh/)
assert.match(html, /Insights: 2 findings linked to listed workloads in the current response; truncated: readiness/)
assert.match(html, /Operations: 1 workloads linked within the latest 200/)
assert.match(html, /2 findings · placement_pressure/)
assert.match(html, /VM Shutdown · succeeded/)
assert.match(html, /scsi0/)
assert.match(html, /local-lvm: vm-141-disk-0/)
assert.match(html, /boot/)
assert.match(html, /raw/)
assert.match(html, /discard/)
assert.match(html, /local-lvm/)

assert.match(instanceListSource, /navigate\(insightFindingPath\(primaryFinding\)\)/)
assert.match(instanceListSource, /navigate\(`\/operations\/\$\{encodeURIComponent\(recentOperation\.id\)\}`\)/)

for (const heading of ['Name', 'Status', 'IP', 'CPU', 'Memory', 'Disk', 'Signals', 'Actions']) {
  assert.match(html, new RegExp(`>${heading}<`), `InstanceList must show ${heading} in the grouped inventory table`)
}

const startButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Start stopped-app'
)
assert.ok(startButton, 'Expected a start control for stopped non-template VMs')
startButton.props.onClick()

hookHarness.beginRender()
tree = InstanceList({})
html = renderToStaticMarkup(tree)
assert.match(html, /Start VM/)
assert.match(html, /Current status/)
assert.match(html, /Stopped/)
assert.match(html, /I acknowledge this will start the stopped VM on Proxmox/)

const checkbox = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.type === 'checkbox'
)
assert.ok(checkbox, 'Expected VM start acknowledgement checkbox')
checkbox.props.onChange({ target: { checked: true } })

hookHarness.beginRender()
tree = InstanceList({})
const confirmStart = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['data-testid'] === 'confirm-vm-start'
)
assert.ok(confirmStart, 'Expected VM start confirmation button')
await confirmStart.props.onClick()
assert.equal(startCalls.length, 1)
assert.equal(startCalls[0].nodeId, 'yoonmanserver2')
assert.equal(startCalls[0].vmid, 142)
assert.equal(startCalls[0].payload.vm_start_acknowledged, true)
assert.equal(startCalls[0].payload.expected_name, 'stopped-app')
assert.equal(startCalls[0].payload.expected_status, 'stopped')
assert.match(startCalls[0].payload.idempotency_key, /^infra-explorer:start:yoonmanserver2:142:/)
assert.deepEqual(operationLookups, ['vm-start-node-a-142'])
assert.deepEqual(navigateCalls, ['/operations/vm-start-node-a-142'])

hookHarness.beginRender()
tree = InstanceList({})
html = renderToStaticMarkup(tree)

const shutdownButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Gracefully shut down app-01'
)
assert.ok(shutdownButton, 'Expected a graceful shutdown control for running non-template VMs')
shutdownButton.props.onClick()

hookHarness.beginRender()
tree = InstanceList({})
html = renderToStaticMarkup(tree)
assert.match(html, /Graceful Shutdown/)
assert.match(html, /will not force-stop or reboot/)
assert.match(html, /I acknowledge this will gracefully shut down the running VM on Proxmox/)

const shutdownAck = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.['data-testid'] === 'vm-shutdown-acknowledgement'
)
assert.ok(shutdownAck, 'Expected VM shutdown acknowledgement checkbox')
shutdownAck.props.onChange({ target: { checked: true } })

hookHarness.beginRender()
tree = InstanceList({})
const confirmShutdown = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['data-testid'] === 'confirm-vm-shutdown'
)
assert.ok(confirmShutdown, 'Expected VM shutdown confirmation button')
await confirmShutdown.props.onClick()
assert.equal(shutdownCalls.length, 1)
assert.equal(shutdownCalls[0].nodeId, 'yoonmanserver2')
assert.equal(shutdownCalls[0].vmid, 141)
assert.equal(shutdownCalls[0].payload.vm_shutdown_acknowledged, true)
assert.equal(shutdownCalls[0].payload.expected_name, 'app-01')
assert.equal(shutdownCalls[0].payload.expected_status, 'running')
assert.match(shutdownCalls[0].payload.idempotency_key, /^infra-explorer:shutdown:yoonmanserver2:141:/)
assert.deepEqual(operationLookups, ['vm-start-node-a-142', 'vm-shutdown-node-a-141'])
assert.deepEqual(navigateCalls, [
  '/operations/vm-start-node-a-142',
  '/operations/vm-shutdown-node-a-141',
])

hookHarness.beginRender()
tree = InstanceList({})
html = renderToStaticMarkup(tree)

const toggle = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-controls'] === 'instance-group-yoonmanserver2'
)
assert.ok(toggle, 'Expected an expand/collapse control for each server group')
toggle.props.onClick()

hookHarness.beginRender()
tree = InstanceList({})
html = renderToStaticMarkup(tree)

assert.match(html, /aria-expanded="false"/)
assert.match(html, /data-icon="ChevronRight"/)
assert.doesNotMatch(html, /instance-group-yoonmanserver2"><div class="overflow-x-auto">/, 'Collapsed groups must hide their table contents')

for (const blocked of [
  'performInstanceAction',
  'terminateInstance',
  'updateInstanceResources',
  'delete',
  'terminate',
  'resize',
  'force stop',
  'reset',
  'reboot',
  'stop instance',
]) {
  assert.ok(!html.toLowerCase().includes(blocked.toLowerCase()), `InstanceList read-only slice must not expose ${blocked}`)
}

delete globalThis.__INSTANCE_LIST_TEST_MOCKS__

console.log('infraExplorerScreen RED contract exercised')
