import assert from 'node:assert/strict'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { buildCreateVmDefaults } = await importExpected(
  '../src/utils/createVmDefaults.js',
  'Create VM default contract utility',
)

const defaults = buildCreateVmDefaults()
assert.equal(defaults.profileId, 'general-vm')
assert.equal(defaults.hardware.cpu, 2)
assert.equal(defaults.hardware.memoryMb, 4096)
assert.equal(defaults.hardware.diskGb, 50)
assert.equal(defaults.network.ipMode, 'static')
assert.equal(defaults.network.prefix, '')
assert.equal(defaults.network.gateway, '')
assert.equal('networkId' in defaults.network, false)
assert.equal('nodeBridges' in defaults.network, false)
assert.equal(defaults.access.cloudInitUser, 'yoon')
assert.equal(defaults.access.passwordLogin, false)
assert.deepEqual(
  defaults.profileOptions.filter((option) => option.createEnabled).map((option) => option.profileId),
  ['general-vm'],
)

defaults.profileOptions[0].createEnabled = false
const nextDefaults = buildCreateVmDefaults()
assert.equal(nextDefaults.profileOptions[0].createEnabled, true)

console.log('createVmDefaults RED contract exercised')
