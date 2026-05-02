import assert from "node:assert/strict"
import {
  buildLifecycleConfirmation,
  getInstanceDisplayName,
  getLifecycleActionPolicy,
  requiresTypedConfirmation,
} from "../src/utils/lifecycleSafety.js"

assert.equal(getInstanceDisplayName({ name: "web-01", vmid: 101 }), "web-01")
assert.equal(getInstanceDisplayName({ server_name: "db-01", vmid: 102 }), "db-01")
assert.equal(getInstanceDisplayName({ vmid: 103 }), "VM 103")

assert.deepEqual(getLifecycleActionPolicy("start"), {
  action: "start",
  label: "Start",
  severity: "low",
  typedConfirmation: false,
})

assert.equal(getLifecycleActionPolicy("stop").severity, "high")
assert.equal(getLifecycleActionPolicy("reboot").severity, "medium")
assert.equal(getLifecycleActionPolicy("terminate").severity, "critical")
assert.equal(requiresTypedConfirmation("terminate"), true)
assert.equal(requiresTypedConfirmation("stop"), false)

const confirmation = buildLifecycleConfirmation({
  instance: { name: "web-01", node: "pve-a", vmid: 101, status: "running" },
  action: "stop",
})
assert.equal(confirmation.title, "Stop VM web-01?")
assert.equal(confirmation.confirmText, "Stop")
assert.match(confirmation.message, /force power off/i)
assert.match(confirmation.message, /pve-a\/101/)

const deleteConfirmation = buildLifecycleConfirmation({
  instance: { name: "web-01", node: "pve-a", vmid: 101, status: "running" },
  action: "terminate",
})
assert.equal(deleteConfirmation.requiredTypedValue, "web-01")
assert.match(deleteConfirmation.message, /permanently delete/i)
