
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
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
      { node_id: 'yoonmanserver2', name: 'yoonmanserver2', status: 'online' },
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
assert.equal(model.nodes[0].vms[0].name, 'app-01')
assert.equal(model.nodes[0].vms[0].readOnly, true)
assert.deepEqual(model.nodes[0].vms[0].allowedActions, [])

const instanceListSource = readFileSync(new URL('../src/components/InstanceList.jsx', import.meta.url), 'utf8')
assert.match(instanceListSource, /apiV1Client/)
assert.match(instanceListSource, /loadInfraExplorerModel/)
assert.doesNotMatch(instanceListSource, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'InstanceList must not import the legacy /api client')

const forbidden = (...parts) => parts.join('')
for (const blocked of [
  forbidden('perform', 'InstanceAction'),
  forbidden('terminate', 'Instance'),
  forbidden('update', 'InstanceResources'),
  forbidden('Trash', '2'),
  forbidden('Pencil'),
  forbidden('Power'),
  forbidden('Rotate', 'Ccw'),
  forbidden('Play'),
  forbidden('Square'),
  forbidden('window.', 'confirm'),
  forbidden('window.', 'prompt'),
  forbidden('delete'),
  forbidden('terminate'),
  forbidden('resize'),
  forbidden('force stop'),
  forbidden('reset'),
  forbidden('shut', 'down'),
  forbidden('re', 'boot'),
  forbidden('start', ' instance'),
  forbidden('stop', ' instance'),
]) {
  assert.ok(!instanceListSource.toLowerCase().includes(blocked.toLowerCase()), `InstanceList read-only slice must not expose ${blocked}`)
}

console.log('infraExplorerScreen RED contract exercised')
