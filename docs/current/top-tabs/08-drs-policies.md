# VM Instances / DRS Policies

평가일: 2026-06-04

## 구현 수준

현재 DRS Policies는 canonical `/instances/drs-policies` route의 VM Instances subtab이다. It is the dedicated frontend surface for manual per-VM DRS migration policy review/edit. Inventory(`/instances`) no longer loads DRS policy coverage, shows a DRS Policy column, renders policy warnings/success messages, or owns the policy review modal.

Policy coverage is visible to authenticated viewers. Update controls and modal submission are gated by operator/admin capability through `canManageDrsPolicies`.

## 구현 API/endpoints

- `GET /api/v1/drs/policies`
- `GET /api/v1/drs/policies/{vm_identity_id}`
- `PUT /api/v1/drs/policies/{vm_identity_id}`

The frontend keeps the backend API unchanged. Per-VM and bulk writes continue through `submitDrsPolicyUpdate` using the `vm_identity_id`, selected policy/reason, `policy_change_acknowledged=true`, and `expected_observation` guard. Browser-controlled actor/source/updated_by/operator_id fields are not sent.

## 관련 파일

- Frontend: [frontend/src/components/DrsPoliciesScreen.jsx](../../../frontend/src/components/DrsPoliciesScreen.jsx), [frontend/src/components/DrsPolicyReviewModal.jsx](../../../frontend/src/components/DrsPolicyReviewModal.jsx), [frontend/src/utils/drsAdvisor.js](../../../frontend/src/utils/drsAdvisor.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js), [frontend/src/App.jsx](../../../frontend/src/App.jsx)
- Tests: [frontend/tests/drsPoliciesScreen.test.mjs](../../../frontend/tests/drsPoliciesScreen.test.mjs), [frontend/tests/appNavigation.test.mjs](../../../frontend/tests/appNavigation.test.mjs), [frontend/tests/authFlow.test.mjs](../../../frontend/tests/authFlow.test.mjs), [frontend/tests/drsAdvisor.test.mjs](../../../frontend/tests/drsAdvisor.test.mjs)

## 현재 구현

The screen renders current policy coverage counts and a table of VM identity, current locator, policy value/reason, observation guard, policy blockers, write state, and writable-row bulk selection. Writable rows can open `DrsPolicyReviewModal` or be selected for a compact bulk policy change modal; blocked identities remain visible with disabled update controls and blocker reasons.

After a successful per-VM or bulk policy save, the screen refreshes DRS policy coverage so the table reflects the latest backend state. Bulk save clears successfully updated rows from selection, keeps failed rows selected, and reports partial failures. Policy changes do not start migration, approve migration, or write Proxmox tags; `allowed` is only a prerequisite for later DRS review.

## DRS Advisor 기준 gaps

Richer policy rule/full metadata editing and deeper metadata completeness workflow remain deferred. DRS execution remains separate from this screen.
