import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { connectionFeatures, permissionGroups } from '../src/pages/settings/proxmoxRegistration.js'
const form = new FormData()
assert.deepEqual(connectionFeatures(form), ['read'])
form.set('power', 'on')
assert.deepEqual(connectionFeatures(form), ['read', 'power'])
assert.equal(permissionGroups.flatMap(([, items]) => items).length, 16)
const source = readFileSync(new URL('../src/pages/settings/ProxmoxSetupPage.jsx', import.meta.url), 'utf8')
assert.match(source, /access_mode: 'cluster', scope: \{\}/)
assert.doesNotMatch(source, /name="(?:nodes|vmids|storages|bridges|create_vmids|clone_vmids|template_vmids)"/)
console.log('proxmox registration feature selection passed')
