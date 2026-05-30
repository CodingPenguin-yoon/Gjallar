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
      /import\s+\{\s*useEffect,\s*useState\s*\}\s+from\s+'react'/,
      'const { useEffect, useState } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.reactHooks'
    )
    .replace(
      /import\s+\{\s*useNavigate\s*\}\s+from\s+'react-router-dom'/,
      'const { useNavigate } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.router'
    )
    .replace(
      /import\s+\{\s*([\s\S]*?)\s*\}\s+from\s+'lucide-react'/,
      `const {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Loader2,
  Play,
  RefreshCw,
  Server,
} = globalThis.__INSTANCE_LIST_TEST_MOCKS__.icons`
    )
    .replace(
      /import\s+DrsPolicyReviewModal\s+from\s+'\.\/DrsPolicyReviewModal'/,
      'const DrsPolicyReviewModal = globalThis.__INSTANCE_LIST_TEST_MOCKS__.drsPolicyModal'
    )
    .replace(
      /import\s+\{\s*apiV1Client\s*\}\s+from\s+'..\/services\/apiV1'/,
      'const { apiV1Client } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.api'
    )
    .replace(
      /import\s+\{\s*authFailureMessage\s*\}\s+from\s+'..\/utils\/auth'/,
      'const { authFailureMessage } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.auth'
    )
    .replace(
      /import\s+\{\s*formatDrsBlocker,\s*loadDrsPolicyCoverage,\s*submitDrsPolicyUpdate\s*\}\s+from\s+'..\/utils\/drsAdvisor'/,
      'const { formatDrsBlocker, loadDrsPolicyCoverage, submitDrsPolicyUpdate } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.drs'
    )
    .replace(
      /import\s+\{\s*loadInfraExplorerModel\s*\}\s+from\s+'..\/utils\/infraExplorerScreen'/,
      'const { loadInfraExplorerModel } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.loader'
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

const { loadInfraExplorerModel } = await importExpected(
  '../src/utils/infraExplorerScreen.js',
  'Infra Explorer screen loader'
)

const calls = []
const startCalls = []
const policyLoadCalls = []
const policyUpdateCalls = []
const fakeClient = {
  async listNodes() {
    calls.push('listNodes')
    return [
      { node_id: 'yoonmanserver2', name: 'yoonmanserver2', display_name: 'Yoonman Server 2', status: 'online' },
      { node_id: 'yoonmanserver3', name: 'yoonmanserver3', status: 'online' },
    ]
  },
  async listVms() {
    calls.push('listVms')
    return [
      {
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
      },
      {
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
      },
    ]
  },
  async startVm(nodeId, vmid, payload) {
    startCalls.push({ nodeId, vmid, payload })
    return { job_id: 'vm-start-node-a-142' }
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

const policyCoverage = {
  items: [
    {
      vmIdentityId: 'identity-141',
      identityConfidence: 'high',
      identityStatus: 'active',
      currentLocator: {
        clusterId: 'cluster-a',
        nodeId: 'yoonmanserver2',
        vmid: 141,
        name: 'app-01',
        powerState: 'running',
      },
      expectedObservation: {
        clusterId: 'cluster-a',
        nodeId: 'yoonmanserver2',
        vmid: 141,
        observedAt: '2026-05-31T01:02:03Z',
        fingerprintHash: 'hash-141',
      },
      expectedObservationPayload: {
        cluster_id: 'cluster-a',
        node_id: 'yoonmanserver2',
        vmid: 141,
        observed_at: '2026-05-31T01:02:03Z',
        fingerprint_hash: 'hash-141',
      },
      policy: { value: 'allowed', reason: 'ops classified', source: 'manual' },
      policyWriteAllowed: true,
      policyWriteBlockers: [],
    },
    {
      vmIdentityId: 'identity-142',
      identityConfidence: 'uncertain',
      identityStatus: 'active',
      currentLocator: {
        clusterId: 'cluster-a',
        nodeId: 'yoonmanserver2',
        vmid: 142,
        name: 'stopped-app',
        powerState: 'stopped',
      },
      expectedObservation: {
        clusterId: 'cluster-a',
        nodeId: 'yoonmanserver2',
        vmid: 142,
        observedAt: '2026-05-31T01:02:03Z',
        fingerprintHash: 'hash-142',
      },
      expectedObservationPayload: {
        cluster_id: 'cluster-a',
        node_id: 'yoonmanserver2',
        vmid: 142,
        observed_at: '2026-05-31T01:02:03Z',
        fingerprint_hash: 'hash-142',
      },
      policy: { value: 'restricted', reason: 'identity uncertain', source: 'default' },
      policyWriteAllowed: false,
      policyWriteBlockers: ['vm_identity_uncertain'],
    },
  ],
  coverage: { totalNonTemplateVms: 2, writeAllowedCount: 1 },
}

const model = await loadInfraExplorerModel(fakeClient)
assert.deepEqual(calls.sort(), ['listNodes', 'listVms'])
assert.equal(model.readOnly, true)
assert.deepEqual(model.allowedActions, [])
assert.equal(model.summary.totalNodes, 2)
assert.equal(model.summary.totalVms, 2)
assert.equal(model.summary.visibleIpCount, 1)
assert.equal(model.summary.guestAgentCount, 1)
assert.equal(model.nodes[0].name, 'Yoonman Server 2')
assert.equal(model.nodes[0].vms[0].name, 'app-01')
assert.equal(model.nodes[0].vms[0].readOnly, true)
assert.deepEqual(model.nodes[0].vms[0].allowedActions, [])
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

const sourcePath = new URL('../src/components/InstanceList.jsx', import.meta.url)
const instanceListSource = readFileSync(sourcePath, 'utf8')
assert.match(instanceListSource, /apiV1Client/)
assert.match(instanceListSource, /loadInfraExplorerModel/)
assert.match(instanceListSource, /loadDrsPolicyCoverage/)
assert.match(instanceListSource, /submitDrsPolicyUpdate/)
assert.match(instanceListSource, /DrsPolicyReviewModal/)
assert.match(instanceListSource, /useNavigate/)
assert.match(instanceListSource, /apiV1Client\.startVm/)
assert.match(instanceListSource, /canStartVms/)
assert.match(instanceListSource, /canManageDrsPolicies/)
assert.match(instanceListSource, /expectedObservation:\s*item\.expectedObservationPayload/)
assert.match(instanceListSource, /vmIdentityId/)
assert.match(instanceListSource, /DRS policy context is unavailable\. VM inventory remains available\./)
assert.doesNotMatch(instanceListSource, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'InstanceList must not import the legacy /api client')
assert.doesNotMatch(instanceListSource, /actor:|updated_by:|operator_id|source:/, 'InstanceList DRS policy writes must not send a browser actor/source/operator')
assert.match(
  instanceListSource,
  /<table className="[^"]*table-fixed[^"]*"/,
  'InstanceList VM table must use fixed table layout'
)
assert.match(
  instanceListSource,
  /<colgroup>[\s\S]*?<col className="w-\[15%\] min-w-\[12rem\]" \/>[\s\S]*?<col className="w-\[7%\] min-w-\[6rem\]" \/>[\s\S]*?<col className="w-\[13%\] min-w-\[10rem\]" \/>[\s\S]*?<col className="w-\[6%\] min-w-\[4rem\]" \/>[\s\S]*?<col className="w-\[7%\] min-w-\[5rem\]" \/>[\s\S]*?<col className="w-\[24%\] min-w-\[21rem\]" \/>[\s\S]*?<col className="w-\[9%\] min-w-\[8rem\]" \/>[\s\S]*?<col className="w-\[11%\] min-w-\[10rem\]" \/>[\s\S]*?<col className="w-\[8%\] min-w-\[7rem\]" \/>[\s\S]*?<\/colgroup>/,
  'InstanceList VM table must define stable column widths with a colgroup'
)
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
  /<td className="px-4 py-2 text-slate-600">[\s\S]*?<SignalStack vm=\{vm\} \/>/,
  'InstanceList Signals cell must show guest-agent and storage evidence'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-slate-600">[\s\S]*?<DrsPolicyStatus item=\{policyItem\} coverageUnavailable=\{Boolean\(policyCoverageWarning\)\} \/>/,
  'InstanceList DRS Policy cell must show joined policy coverage'
)
assert.match(
  instanceListSource,
  /aria-label=\{`Review DRS policy for \$\{vm\.name\}`\}/,
  'InstanceList must render a row Review action for DRS policy'
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
  router: { useNavigate: () => (path) => navigateCalls.push(path) },
  icons: {
    AlertTriangle: icon('AlertTriangle'),
    ChevronDown: icon('ChevronDown'),
    ChevronRight: icon('ChevronRight'),
    ClipboardCheck: icon('ClipboardCheck'),
    Loader2: icon('Loader2'),
    Play: icon('Play'),
    RefreshCw: icon('RefreshCw'),
    Server: icon('Server'),
  },
  api: { apiV1Client: fakeClient },
  auth: { authFailureMessage: (error, fallback) => error?.message || fallback },
  loader: { loadInfraExplorerModel: async () => model },
  drs: {
    formatDrsBlocker: (code) => String(code).replaceAll('_', ' '),
    loadDrsPolicyCoverage: async () => {
      policyLoadCalls.push('loadDrsPolicyCoverage')
      return policyCoverage
    },
    submitDrsPolicyUpdate: async (client, vmIdentityId, payload) => {
      policyUpdateCalls.push({ client, vmIdentityId, payload })
      return {
        vmIdentityId,
        auditEventId: 'audit-141',
        newPolicy: { value: payload.policy },
      }
    },
  },
  drsPolicyModal: ({ item, onSubmit }) => jsxs('div', {
    'data-testid': 'drs-policy-modal',
    children: [
      `DRS policy modal for ${item.currentLocator.name}`,
      jsx('button', {
        type: 'button',
        'data-testid': 'confirm-drs-policy',
        onClick: () => onSubmit(item, {
          policy: 'blocked',
          reason: 'operator reviewed from inventory',
          acknowledged: true,
        }),
        children: 'Save policy',
      }),
    ],
  }),
}

const compiledModule = loadCommonJsModule(compiled, String(sourcePath))
const InstanceList = compiledModule.default

hookHarness.beginRender()
InstanceList({})
await hookHarness.flushEffects()

hookHarness.beginRender()
let tree = InstanceList({})
let html = renderToStaticMarkup(tree)

assert.match(html, /Instances/)
assert.match(html, /Inspect infrastructure instances/)
assert.match(html, /Refresh/)
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
assert.match(html, /scsi0/)
assert.match(html, /local-lvm: vm-141-disk-0/)
assert.match(html, /boot/)
assert.match(html, /raw/)
assert.match(html, /discard/)
assert.match(html, /local-lvm/)
assert.match(html, /DRS policy review is visible/)
assert.match(html, /allowed/)
assert.match(html, /identity high/)
assert.match(html, /restricted/)
assert.match(html, /identity uncertain/)
assert.match(html, /write blocked: vm identity uncertain/)
assert.ok(policyLoadCalls.length >= 1, 'InstanceList must load supplemental DRS policy coverage')

for (const heading of ['Name', 'Status', 'IP', 'CPU', 'Memory', 'Disk', 'Signals', 'DRS Policy', 'Actions']) {
  assert.match(html, new RegExp(`>${heading}<`), `InstanceList must show ${heading} in the grouped inventory table`)
}

const viewerReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for app-01'
)
assert.ok(viewerReviewButton, 'Expected a DRS policy review control for each VM row')
assert.equal(viewerReviewButton.props.disabled, true, 'Viewer role must not be able to update DRS policy from inventory')

hookHarness.beginRender()
tree = InstanceList({ canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
const writableReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for app-01'
)
assert.ok(writableReviewButton, 'Expected an enabled DRS policy review control for writable policy identities')
assert.equal(writableReviewButton.props.disabled, false)
const blockedReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for stopped-app'
)
assert.ok(blockedReviewButton, 'Expected a disabled DRS policy review control for blocked policy identities')
assert.equal(blockedReviewButton.props.disabled, true)
assert.match(blockedReviewButton.props.title, /vm identity uncertain/)
writableReviewButton.props.onClick()

hookHarness.beginRender()
tree = InstanceList({ canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.match(html, /DRS policy modal for app-01/)
const policyModal = findElement(
  tree,
  (element) => element.props?.item?.vmIdentityId === 'identity-141' && typeof element.props?.onSubmit === 'function'
)
assert.ok(policyModal, 'Expected policy review modal submit props')
await policyModal.props.onSubmit(policyModal.props.item, {
  policy: 'blocked',
  reason: 'operator reviewed from inventory',
  acknowledged: true,
})
assert.equal(policyUpdateCalls.length, 1)
assert.equal(policyUpdateCalls[0].vmIdentityId, 'identity-141')
assert.deepEqual(policyUpdateCalls[0].payload, {
  policy: 'blocked',
  reason: 'operator reviewed from inventory',
  policyChangeAcknowledged: true,
  expectedObservation: policyCoverage.items[0].expectedObservationPayload,
})
assert.doesNotMatch(JSON.stringify(policyUpdateCalls[0].payload), /app-01|currentLocator|nodeId|actor|source|operator_id|updated_by/)

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
assert.deepEqual(navigateCalls, ['/jobs?job=vm-start-node-a-142'])

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
  'shutdown',
  'reboot',
  'stop instance',
]) {
  assert.ok(!html.toLowerCase().includes(blocked.toLowerCase()), `InstanceList read-only slice must not expose ${blocked}`)
}

const failureHarness = createHookHarness()
globalThis.__INSTANCE_LIST_TEST_MOCKS__ = {
  reactHooks: failureHarness.hooks,
  router: { useNavigate: () => (path) => navigateCalls.push(path) },
  icons: {
    AlertTriangle: icon('AlertTriangle'),
    ChevronDown: icon('ChevronDown'),
    ChevronRight: icon('ChevronRight'),
    ClipboardCheck: icon('ClipboardCheck'),
    Loader2: icon('Loader2'),
    Play: icon('Play'),
    RefreshCw: icon('RefreshCw'),
    Server: icon('Server'),
  },
  api: { apiV1Client: fakeClient },
  auth: { authFailureMessage: (error, fallback) => error?.message || fallback },
  loader: { loadInfraExplorerModel: async () => model },
  drs: {
    formatDrsBlocker: (code) => String(code).replaceAll('_', ' '),
    loadDrsPolicyCoverage: async () => {
      throw new Error('DRS policies unavailable')
    },
    submitDrsPolicyUpdate: async () => {
      throw new Error('policy update should not run without policy context')
    },
  },
  drsPolicyModal: () => jsx('div', { children: 'unexpected policy modal' }),
}
const FailureInstanceList = loadCommonJsModule(compiled, `${String(sourcePath)}?drs-policy-failure`).default
failureHarness.beginRender()
FailureInstanceList({ canManageDrsPolicies: true })
await failureHarness.flushEffects()
failureHarness.beginRender()
tree = FailureInstanceList({ canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.match(html, /DRS policy context is unavailable\. VM inventory remains available\. DRS policies unavailable/)
assert.match(html, /app-01/, 'Inventory must still render when DRS policy context fails')
const unavailableReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for app-01'
)
assert.ok(unavailableReviewButton, 'Expected disabled policy review control when supplemental policy context fails')
assert.equal(unavailableReviewButton.props.disabled, true)

delete globalThis.__INSTANCE_LIST_TEST_MOCKS__

console.log('infraExplorerScreen RED contract exercised')
