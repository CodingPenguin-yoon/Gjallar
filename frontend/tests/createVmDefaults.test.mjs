import assert from 'node:assert/strict'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const {
  buildCreateVmDefaults,
  normalizeCreateVmProfiles,
  resetHardwareForProfile,
} = await importExpected(
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
assert.equal(defaults.access.sshPublicKey, '')
assert.equal(defaults.access.passwordLogin, false)
assert.equal(defaults.access.requireSshKey, true)
assert.equal(defaults.access.allowPasswordLogin, false)
assert.equal(defaults.access.sshKeySource, 'request_or_backend_default')
assert.deepEqual(
  defaults.profileOptions.filter((option) => option.createEnabled).map((option) => option.profileId),
  ['general-vm', 'runtime-server', 'development-vm'],
)
assert.deepEqual(defaults.profileOptions.map((option) => option.profileId), ['general-vm', 'runtime-server', 'development-vm'])
assert.deepEqual(defaults.profileOptions.map((option) => option.displayNameKo), ['범용 VM', '서비스 실행용 VM', '개발/테스트용 VM'])
assert.deepEqual(defaults.profileOptions[0].hardware.cpu, { default: 2, min: 1, max: 8 })
assert.deepEqual(defaults.profileOptions[1].hardware, {
  cpu: { default: 4, min: 2, max: 16 },
  memoryMb: { default: 8192, min: 4096, max: 65536 },
  diskGb: { default: 100, min: 80, max: 1000 },
})
assert.equal('networkId' in defaults.profileOptions[0], false)
assert.equal('network' in defaults.profileOptions[0], false)
assert.deepEqual(normalizeCreateVmProfiles([]), [])
assert.deepEqual(normalizeCreateVmProfiles({ profiles: [] }), [])

defaults.profileOptions[0].createEnabled = false
const nextDefaults = buildCreateVmDefaults()
assert.equal(nextDefaults.profileOptions[0].createEnabled, true)

const normalized = normalizeCreateVmProfiles([
  {
    id: 'runtime-server',
    profile_id: 'runtime-server',
    display_name: 'Runtime Server',
    display_name_ko: '서비스 실행용 VM',
    enabled: true,
    create_enabled: true,
    hardware: {
      cpu: { default: 4, min: 2, max: 16 },
      memory_mb: { default: 8192, min: 4096, max: 65536 },
      disk_gb: { default: 100, min: 80, max: 1000 },
    },
    template_requirements: { require_cloud_init: true, require_qemu_guest_agent: true },
    access_recommendations: {
      default_user: 'yoon',
      require_ssh_key: true,
      allow_password_login: false,
      allow_user_override: true,
      ssh_key_source: 'request_or_backend_default',
    },
    source: 'static_seed',
    management: 'read_only',
  },
])
assert.equal(normalized[0].profileId, 'runtime-server')
assert.equal(normalized[0].displayNameKo, '서비스 실행용 VM')
assert.equal(normalized[0].hardware.memoryMb.default, 8192)
assert.equal(normalized[0].accessRecommendations.requireSshKey, true)
assert.equal(normalized[0].accessRecommendations.sshKeySource, 'request_or_backend_default')

const wrapped = normalizeCreateVmProfiles({
  profiles: [
    {
      id: 'development-vm',
      profile_id: 'development-vm',
      display_name: 'Development VM',
      display_name_ko: '개발/테스트용 VM',
      enabled: true,
      create_enabled: true,
      hardware: {
        cpu: { default: 2, min: 1, max: 12 },
        memory_mb: { default: 4096, min: 2048, max: 32768 },
        disk_gb: { default: 50, min: 50, max: 500 },
      },
    },
  ],
})
assert.equal(wrapped[0].profileId, 'development-vm')
assert.equal(wrapped[0].displayNameKo, '개발/테스트용 VM')
assert.equal(wrapped[0].hardware.cpu.max, 12)

assert.deepEqual(
  resetHardwareForProfile(defaults.profileOptions[1]),
  { cpu: 4, memoryMb: 8192, diskGb: 100 },
)
assert.deepEqual(
  resetHardwareForProfile(defaults.profileOptions[0], 80),
  { cpu: 2, memoryMb: 4096, diskGb: 80 },
)

console.log('createVmDefaults RED contract exercised')
