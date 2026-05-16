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
  Loader2,
  Play,
  RefreshCw,
  Server,
} = globalThis.__INSTANCE_LIST_TEST_MOCKS__.icons`
    )
    .replace(
      /import\s+\{\s*apiV1Client\s*\}\s+from\s+'..\/services\/apiV1'/,
      'const { apiV1Client } = globalThis.__INSTANCE_LIST_TEST_MOCKS__.api'
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
assert.match(instanceListSource, /useNavigate/)
assert.match(instanceListSource, /apiV1Client\.startVm/)
assert.doesNotMatch(instanceListSource, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'InstanceList must not import the legacy /api client')
assert.match(
  instanceListSource,
  /<table className="[^"]*table-fixed[^"]*"/,
  'InstanceList VM table must use fixed table layout'
)
assert.match(
  instanceListSource,
  /<colgroup>[\s\S]*?<col className="w-\[17%\] min-w-\[12rem\]" \/>[\s\S]*?<col className="w-\[8%\] min-w-\[6rem\]" \/>[\s\S]*?<col className="w-\[15%\] min-w-\[11rem\]" \/>[\s\S]*?<col className="w-\[6%\] min-w-\[4rem\]" \/>[\s\S]*?<col className="w-\[7%\] min-w-\[5rem\]" \/>[\s\S]*?<col className="w-\[28%\] min-w-\[22rem\]" \/>[\s\S]*?<col className="w-\[11%\] min-w-\[8rem\]" \/>[\s\S]*?<col className="w-\[8%\] min-w-\[6rem\]" \/>[\s\S]*?<\/colgroup>/,
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
    Loader2: icon('Loader2'),
    Play: icon('Play'),
    RefreshCw: icon('RefreshCw'),
    Server: icon('Server'),
  },
  api: { apiV1Client: fakeClient },
  loader: { loadInfraExplorerModel: async () => model },
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

delete globalThis.__INSTANCE_LIST_TEST_MOCKS__

console.log('infraExplorerScreen RED contract exercised')
