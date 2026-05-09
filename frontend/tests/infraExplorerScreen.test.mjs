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
      /import\s+\{\s*([\s\S]*?)\s*\}\s+from\s+'lucide-react'/,
      `const {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
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
        ip_addresses: ['192.168.2.141'],
        memory_mb: 4096,
        disk_gb: 40,
      },
    ]
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
assert.equal(model.summary.totalVms, 1)
assert.equal(model.nodes[0].name, 'Yoonman Server 2')
assert.equal(model.nodes[0].vms[0].name, 'app-01')
assert.equal(model.nodes[0].vms[0].readOnly, true)
assert.deepEqual(model.nodes[0].vms[0].allowedActions, [])

const sourcePath = new URL('../src/components/InstanceList.jsx', import.meta.url)
const instanceListSource = readFileSync(sourcePath, 'utf8')
assert.match(instanceListSource, /apiV1Client/)
assert.match(instanceListSource, /loadInfraExplorerModel/)
assert.doesNotMatch(instanceListSource, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'InstanceList must not import the legacy /api client')
assert.match(
  instanceListSource,
  /<table className="[^"]*table-fixed[^"]*"/,
  'InstanceList VM table must use fixed table layout'
)
assert.match(
  instanceListSource,
  /<colgroup>[\s\S]*?<col className="w-\[28%\] min-w-\[14rem\]" \/>[\s\S]*?<col className="w-\[12%\] min-w-\[8rem\]" \/>[\s\S]*?<col className="w-\[24%\] min-w-\[12rem\]" \/>[\s\S]*?<col className="w-\[8%\] min-w-\[4\.5rem\]" \/>[\s\S]*?<col className="w-\[10%\] min-w-\[6rem\]" \/>[\s\S]*?<col className="w-\[10%\] min-w-\[6rem\]" \/>[\s\S]*?<col className="w-\[8%\] min-w-\[5rem\]" \/>[\s\S]*?<\/colgroup>/,
  'InstanceList VM table must define stable column widths with a colgroup'
)
assert.match(
  instanceListSource,
  /<div className="truncate font-medium text-slate-950" title=\{vm\.name\}>/,
  'InstanceList VM name must truncate without expanding the column'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-slate-600" title=\{vmIpLabel\}>[\s\S]*?<div className="truncate">{vmIpLabel}<\/div>/,
  'InstanceList IP cell must truncate without expanding the column'
)
assert.match(
  instanceListSource,
  /const cpuLabel = formatNumber\(vm\.cpuCores\)/,
  'InstanceList must build a CPU display label inside the VM row map'
)
assert.match(
  instanceListSource,
  /const memoryLabel = `\$\{formatNumber\(vm\.memoryGb, 1\)\} GB`/,
  'InstanceList must build a Memory display label inside the VM row map'
)
assert.match(
  instanceListSource,
  /const diskLabel = `\$\{formatNumber\(vm\.diskGb, 1\)\} GB`/,
  'InstanceList must build a Disk display label inside the VM row map'
)
assert.match(
  instanceListSource,
  /const templateLabel = vm\.template \? 'Yes' : 'No'/,
  'InstanceList must build a Template display label inside the VM row map'
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
  /<td className="px-4 py-2 text-right text-slate-600" title=\{diskLabel\}>[\s\S]*?<div className="truncate">{diskLabel}<\/div>/,
  'InstanceList Disk cell must truncate without expanding the column'
)
assert.match(
  instanceListSource,
  /<td className="px-4 py-2 text-center text-slate-600" title=\{templateLabel\}>[\s\S]*?<div className="truncate">{templateLabel}<\/div>/,
  'InstanceList Template cell must truncate without expanding the column'
)

const compiled = transformSync(compileInstanceListSource(instanceListSource), {
  loader: 'jsx',
  format: 'cjs',
  jsx: 'automatic',
}).code

const hookHarness = createHookHarness()
globalThis.__INSTANCE_LIST_TEST_MOCKS__ = {
  reactHooks: hookHarness.hooks,
  icons: {
    AlertTriangle: icon('AlertTriangle'),
    ChevronDown: icon('ChevronDown'),
    ChevronRight: icon('ChevronRight'),
    Loader2: icon('Loader2'),
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
assert.match(html, /Manage\/read-only infrastructure instances/)
assert.match(html, /Refresh/)
assert.match(html, /Yoonman Server 2/)
assert.match(html, /yoonmanserver3/)
assert.match(html, /1 instances/)
assert.match(html, /0 instances/)
assert.match(html, /aria-expanded="true"/)
assert.match(html, /data-icon="ChevronDown"/)
assert.match(html, /Online/)
assert.match(html, /app-01/)
assert.match(html, /VMID 141/)
assert.match(html, /192\.168\.2\.141/)

for (const heading of ['Name', 'Status', 'IP', 'CPU', 'Memory', 'Disk', 'Template']) {
  assert.match(html, new RegExp(`>${heading}<`), `InstanceList must show ${heading} in the grouped inventory table`)
}

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
  'Actions',
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
  'start instance',
  'stop instance',
]) {
  assert.ok(!html.toLowerCase().includes(blocked.toLowerCase()), `InstanceList read-only slice must not expose ${blocked}`)
}

delete globalThis.__INSTANCE_LIST_TEST_MOCKS__

console.log('infraExplorerScreen RED contract exercised')
