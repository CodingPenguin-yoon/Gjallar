import assert from 'node:assert/strict'
import { buildCreateVmDefaults, hardwareFromTemplate, normalizeCreateVmProfiles, resetHardwareForProfile } from '../src/utils/createVmDefaults.js'

const defaults = buildCreateVmDefaults()
assert.equal(defaults.creationMode, 'template')
assert.equal(defaults.profileId, '')
assert.equal(defaults.access.cloudInitUser, '')
assert.deepEqual(defaults.profileOptions, [])
assert.deepEqual(defaults.hardware, { cpu: '', memoryMb: '', diskGb: '' })
assert.equal(defaults.access.requireSshKey, true)
assert.equal(defaults.access.allowPasswordLogin, false)
assert.deepEqual(hardwareFromTemplate({ cpu: 6, memoryMb: 12288, diskGb: 80 }), { cpu: 6, memoryMb: 12288, diskGb: 80 })

const profile = {
  profile_id: 'custom', display_name: 'Custom', enabled: true,
  hardware: { cpu: { default: 6, min: 2, max: 12 }, memory_mb: { default: 12288, min: 2048, max: 32768 }, disk_gb: { default: 80, min: 50, max: 500 } },
  access_recommendations: { default_user: 'operator', require_ssh_key: true },
  template_requirements: { require_cloud_init: true, require_qemu_guest_agent: false },
}
const [normalized] = normalizeCreateVmProfiles({ profiles: [profile] })
assert.equal(normalized.profileId, 'custom')
assert.deepEqual(normalized.hardware.cpu, profile.hardware.cpu)
assert.equal(normalized.accessRecommendations.defaultUser, 'operator')
assert.equal(normalized.templateRequirements.requireQemuGuestAgent, false)
assert.deepEqual(resetHardwareForProfile(normalized, 100), { cpu: 6, memoryMb: 12288, diskGb: 100 })
assert.deepEqual(normalizeCreateVmProfiles([]), [])
assert.deepEqual(normalizeCreateVmProfiles([{ profile_id: 'missing-policy' }]), [])
assert.deepEqual(normalizeCreateVmProfiles([normalized]), [normalized])
console.log('template defaults and optional persisted presets contract exercised')
