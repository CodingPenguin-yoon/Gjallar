import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { renderToStaticMarkup } from 'react-dom/server'
import { jsx, jsxs } from 'react/jsx-runtime'

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

function compileDrsPoliciesSource(source) {
  return source
    .replace(
      /import\s+\{\s*useEffect,\s*useState\s*\}\s+from\s+'react'/,
      'const { useEffect, useState } = globalThis.__DRS_POLICIES_TEST_MOCKS__.reactHooks'
    )
    .replace(
      /import\s+\{\s*([\s\S]*?)\s*\}\s+from\s+'lucide-react'/,
      `const {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  RefreshCw,
  ShieldCheck,
} = globalThis.__DRS_POLICIES_TEST_MOCKS__.icons`
    )
    .replace(
      /import\s+DrsPolicyReviewModal\s+from\s+'\.\/DrsPolicyReviewModal'/,
      'const DrsPolicyReviewModal = globalThis.__DRS_POLICIES_TEST_MOCKS__.drsPolicyModal'
    )
    .replace(
      /import\s+\{\s*apiV1Client\s*\}\s+from\s+'..\/services\/apiV1'/,
      'const { apiV1Client } = globalThis.__DRS_POLICIES_TEST_MOCKS__.api'
    )
    .replace(
      /import\s+\{\s*authFailureMessage\s*\}\s+from\s+'..\/utils\/auth'/,
      'const { authFailureMessage } = globalThis.__DRS_POLICIES_TEST_MOCKS__.auth'
    )
    .replace(
      /import\s+\{\s*formatDrsBlocker,\s*loadDrsPolicyCoverage,\s*submitDrsPolicyUpdate\s*\}\s+from\s+'..\/utils\/drsAdvisor'/,
      'const { formatDrsBlocker, loadDrsPolicyCoverage, submitDrsPolicyUpdate } = globalThis.__DRS_POLICIES_TEST_MOCKS__.drs'
    )
}

const sourcePath = new URL('../src/components/DrsPoliciesScreen.jsx', import.meta.url)
const screenSource = readFileSync(sourcePath, 'utf8')
assert.match(screenSource, /function DrsPoliciesScreen\(\{ currentUser = null, canManageDrsPolicies = false \}\)/)
assert.match(screenSource, /loadDrsPolicyCoverage/)
assert.match(screenSource, /submitDrsPolicyUpdate/)
assert.match(screenSource, /DrsPolicyReviewModal/)
assert.match(screenSource, /BulkDrsPolicyModal/)
assert.match(screenSource, /selectedIds/)
assert.match(screenSource, /policyChangeAcknowledged: acknowledged/)
assert.match(screenSource, /expectedObservation: item\.expectedObservationPayload/)
assert.match(screenSource, /submitDrsPolicyUpdate\(apiV1Client, item\.vmIdentityId/)
assert.doesNotMatch(screenSource, /apiV1Client\.updateDrsPolicy/)
assert.doesNotMatch(screenSource, /actor:|updated_by:|operator_id|source:/)

const coverage = {
  items: [
    {
      vmIdentityId: 'identity-141',
      identityConfidence: 'high',
      identityStatus: 'active',
      currentLocator: {
        clusterId: 'cluster-a',
        nodeId: 'node-a',
        vmid: 141,
        name: 'app-01',
        powerState: 'running',
      },
      expectedObservation: {
        clusterId: 'cluster-a',
        nodeId: 'node-a',
        vmid: 141,
        observedAt: '2026-05-31T01:02:03Z',
        fingerprintHash: 'hash-141',
      },
      expectedObservationPayload: {
        cluster_id: 'cluster-a',
        node_id: 'node-a',
        vmid: 141,
        observed_at: '2026-05-31T01:02:03Z',
        fingerprint_hash: 'hash-141',
      },
      policy: { value: 'allowed', reason: 'ops classified', source: 'manual' },
      policyWriteAllowed: true,
      policyWriteBlockers: [],
      drsBlockerImpact: { policyBlockers: [], recommendationBlockers: [] },
    },
    {
      vmIdentityId: 'identity-142',
      identityConfidence: 'uncertain',
      identityStatus: 'active',
      currentLocator: {
        clusterId: 'cluster-a',
        nodeId: 'node-a',
        vmid: 142,
        name: 'stopped-app',
        powerState: 'stopped',
      },
      expectedObservation: {
        clusterId: 'cluster-a',
        nodeId: 'node-a',
        vmid: 142,
        observedAt: '2026-05-31T01:02:04Z',
        fingerprintHash: 'hash-142',
      },
      expectedObservationPayload: {
        cluster_id: 'cluster-a',
        node_id: 'node-a',
        vmid: 142,
        observed_at: '2026-05-31T01:02:04Z',
        fingerprint_hash: 'hash-142',
      },
      policy: { value: 'restricted', reason: 'identity uncertain', source: 'default' },
      policyWriteAllowed: false,
      policyWriteBlockers: ['vm_identity_uncertain'],
      drsBlockerImpact: { policyBlockers: ['migration_policy_restricted'], recommendationBlockers: [] },
    },
    {
      vmIdentityId: 'identity-143',
      identityConfidence: 'high',
      identityStatus: 'active',
      currentLocator: {
        clusterId: 'cluster-a',
        nodeId: 'node-b',
        vmid: 143,
        name: 'db-01',
        powerState: 'running',
      },
      expectedObservation: {
        clusterId: 'cluster-a',
        nodeId: 'node-b',
        vmid: 143,
        observedAt: '2026-05-31T01:02:05Z',
        fingerprintHash: 'hash-143',
      },
      expectedObservationPayload: {
        cluster_id: 'cluster-a',
        node_id: 'node-b',
        vmid: 143,
        observed_at: '2026-05-31T01:02:05Z',
        fingerprint_hash: 'hash-143',
      },
      policy: { value: 'unknown', reason: '', source: 'default' },
      policyWriteAllowed: true,
      policyWriteBlockers: [],
      drsBlockerImpact: { policyBlockers: [], recommendationBlockers: [] },
    },
  ],
  coverage: {
    totalNonTemplateVms: 3,
    allowedCount: 1,
    unknownCount: 1,
    restrictedCount: 1,
    blockedCount: 0,
    writeAllowedCount: 2,
  },
}

const loadCalls = []
const submitCalls = []
const hookHarness = createHookHarness()
globalThis.__DRS_POLICIES_TEST_MOCKS__ = {
  reactHooks: hookHarness.hooks,
  icons: {
    AlertTriangle: icon('AlertTriangle'),
    CheckCircle2: icon('CheckCircle2'),
    ClipboardCheck: icon('ClipboardCheck'),
    Loader2: icon('Loader2'),
    RefreshCw: icon('RefreshCw'),
    ShieldCheck: icon('ShieldCheck'),
  },
  drsPolicyModal: ({ item, saving, error, result, onCancel, onSubmit }) => jsxs('div', {
    'data-testid': 'drs-policy-modal',
    item,
    'data-saving': saving ? 'true' : 'false',
    error,
    result,
    onCancel,
    onSubmit,
    children: [
      `DRS policy modal for ${item.currentLocator.name}`,
      jsx('button', { type: 'button', children: 'Save policy' }),
    ],
  }),
  api: { apiV1Client: { name: 'api-v1-client' } },
  auth: { authFailureMessage: (error, fallback) => error?.message || fallback },
  drs: {
    formatDrsBlocker: (code) => String(code).replaceAll('_', ' '),
    loadDrsPolicyCoverage: async (client) => {
      loadCalls.push(client)
      return coverage
    },
    submitDrsPolicyUpdate: async (client, vmIdentityId, payload) => {
      submitCalls.push({ client, vmIdentityId, payload })
      return {
        vmIdentityId,
        auditEventId: 'audit-141',
        newPolicy: { value: payload.policy },
      }
    },
  },
}

const compiled = transformSync(compileDrsPoliciesSource(screenSource), {
  loader: 'jsx',
  format: 'cjs',
  jsx: 'automatic',
}).code
const DrsPoliciesScreen = loadCommonJsModule(compiled, String(sourcePath)).default

hookHarness.beginRender()
DrsPoliciesScreen({ currentUser: { role: 'viewer' } })
await hookHarness.flushEffects()

hookHarness.beginRender()
let tree = DrsPoliciesScreen({ currentUser: { role: 'viewer' } })
let html = renderToStaticMarkup(tree)

assert.match(html, /DRS Policies/)
assert.match(html, /Review VM migration policy coverage/)
assert.match(html, /DRS policy review is visible, but updates require operator or admin role/)
assert.match(html, /app-01/)
assert.match(html, /identity-141/)
assert.match(html, /allowed/)
assert.match(html, /ops classified/)
assert.match(html, /hash-141/)
assert.match(html, /stopped-app/)
assert.match(html, /restricted/)
assert.match(html, /vm identity uncertain/)
assert.match(html, /db-01/)
assert.match(html, /Bulk update/)
assert.equal(loadCalls.length, 1)

const viewerReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for app-01'
)
assert.ok(viewerReviewButton)
assert.equal(viewerReviewButton.props.disabled, true, 'Viewer must see policies but not update controls')
const viewerBulkCheckbox = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.['aria-label'] === 'Select app-01 for bulk DRS policy update'
)
assert.ok(viewerBulkCheckbox)
assert.equal(viewerBulkCheckbox.props.disabled, true, 'Viewer must not select rows for bulk DRS policy updates')
const viewerBulkButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Open bulk DRS policy update'
)
assert.ok(viewerBulkButton)
assert.equal(viewerBulkButton.props.disabled, true, 'Viewer must not open bulk DRS policy updates')

hookHarness.beginRender()
tree = DrsPoliciesScreen({ currentUser: { role: 'operator' }, canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.doesNotMatch(html, /updates require operator or admin role/)
const selectAllBulkCheckbox = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.['aria-label'] === 'Select all writable DRS policy rows'
)
assert.ok(selectAllBulkCheckbox)
assert.equal(selectAllBulkCheckbox.props.disabled, false)
const writableReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for app-01'
)
assert.ok(writableReviewButton)
assert.equal(writableReviewButton.props.disabled, false)
const blockedReviewButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Review DRS policy for stopped-app'
)
assert.ok(blockedReviewButton)
assert.equal(blockedReviewButton.props.disabled, true)
assert.match(blockedReviewButton.props.title, /vm identity uncertain/)
const blockedBulkCheckbox = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.['aria-label'] === 'Select stopped-app for bulk DRS policy update'
)
assert.ok(blockedBulkCheckbox)
assert.equal(blockedBulkCheckbox.props.disabled, true, 'Non-writable rows must not be bulk selectable')
assert.match(blockedBulkCheckbox.props.title, /vm identity uncertain/)

writableReviewButton.props.onClick()
hookHarness.beginRender()
tree = DrsPoliciesScreen({ currentUser: { role: 'operator' }, canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.match(html, /DRS policy modal for app-01/)
const modal = findElement(
  tree,
  (element) => element.props?.item?.vmIdentityId === 'identity-141' && typeof element.props?.onSubmit === 'function'
)
assert.ok(modal)
await modal.props.onSubmit(modal.props.item, {
  policy: 'blocked',
  reason: 'operator reviewed from DRS Policies',
  acknowledged: true,
})

assert.equal(submitCalls.length, 1)
assert.equal(submitCalls[0].vmIdentityId, 'identity-141')
assert.deepEqual(submitCalls[0].payload, {
  policy: 'blocked',
  reason: 'operator reviewed from DRS Policies',
  policyChangeAcknowledged: true,
  expectedObservation: coverage.items[0].expectedObservationPayload,
})
assert.doesNotMatch(JSON.stringify(submitCalls[0].payload), /app-01|currentLocator|actor|source|operator_id|updated_by/)
assert.equal(loadCalls.length, 2, 'DRS Policies screen must refresh coverage after save')

hookHarness.beginRender()
tree = DrsPoliciesScreen({ currentUser: { role: 'operator' }, canManageDrsPolicies: true })
selectAllBulkCheckbox.props.onChange()

hookHarness.beginRender()
tree = DrsPoliciesScreen({ currentUser: { role: 'operator' }, canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.match(html, />2<\/span> selected/)
const selectedAppCheckbox = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.['aria-label'] === 'Select app-01 for bulk DRS policy update'
)
const selectedDbCheckbox = findElement(
  tree,
  (element) => element.type === 'input' && element.props?.['aria-label'] === 'Select db-01 for bulk DRS policy update'
)
assert.equal(selectedAppCheckbox.props.checked, true, 'Writable selected rows must be checked')
assert.equal(selectedDbCheckbox.props.checked, true, 'All writable rows must be selectable for bulk')
assert.equal(blockedBulkCheckbox.props.checked, false, 'Blocked rows must not be selected by select-all')
const bulkButton = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Open bulk DRS policy update'
)
assert.ok(bulkButton)
assert.equal(bulkButton.props.disabled, false)

bulkButton.props.onClick()
hookHarness.beginRender()
tree = DrsPoliciesScreen({ currentUser: { role: 'operator' }, canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.match(html, /Bulk DRS Policy Change/)
assert.match(html, /2 selected VMs/)
assert.match(html, /Policy/)
assert.match(html, /Reason/)
assert.match(html, /I reviewed the selected VM observation guards/)
assert.match(html, /Allowed is only a prerequisite/)
assert.match(html, /app-01/)
assert.match(html, /db-01/)
assert.match(html, /Cancel/)
assert.match(html, /Save policies/)
const bulkModal = findElement(
  tree,
  (element) => element.type?.name === 'BulkDrsPolicyModal' && typeof element.props?.onSubmit === 'function'
)
assert.ok(bulkModal)
assert.equal(bulkModal.props.items.length, 2)
await bulkModal.props.onSubmit({
  policy: 'allowed',
  reason: 'bulk reviewed from DRS Policies',
  acknowledged: true,
})

assert.equal(submitCalls.length, 3, 'Bulk save must call submitDrsPolicyUpdate once per selected writable VM')
assert.deepEqual(submitCalls[1], {
  client: { name: 'api-v1-client' },
  vmIdentityId: 'identity-141',
  payload: {
    policy: 'allowed',
    reason: 'bulk reviewed from DRS Policies',
    policyChangeAcknowledged: true,
    expectedObservation: coverage.items[0].expectedObservationPayload,
  },
})
assert.deepEqual(submitCalls[2], {
  client: { name: 'api-v1-client' },
  vmIdentityId: 'identity-143',
  payload: {
    policy: 'allowed',
    reason: 'bulk reviewed from DRS Policies',
    policyChangeAcknowledged: true,
    expectedObservation: coverage.items[2].expectedObservationPayload,
  },
})
for (const call of submitCalls) {
  assert.doesNotMatch(JSON.stringify(call.payload), /app-01|db-01|currentLocator|actor|source|operator_id|updated_by/)
}
assert.equal(loadCalls.length, 3, 'Bulk save must refresh coverage after writes')

hookHarness.beginRender()
tree = DrsPoliciesScreen({ currentUser: { role: 'operator' }, canManageDrsPolicies: true })
html = renderToStaticMarkup(tree)
assert.match(html, />0<\/span> selected/, 'Successful bulk save must clear selected rows')
assert.doesNotMatch(html, /Bulk DRS Policy Change/)
const disabledBulkButtonAfterSave = findElement(
  tree,
  (element) => element.type === 'button' && element.props?.['aria-label'] === 'Open bulk DRS policy update'
)
assert.equal(disabledBulkButtonAfterSave.props.disabled, true)

delete globalThis.__DRS_POLICIES_TEST_MOCKS__

console.log('drsPoliciesScreen RED contract exercised')
