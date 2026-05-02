import assert from "node:assert/strict"
import {
  buildInventorySummary,
  getInstanceOperationalSignals,
} from "../src/utils/inventorySummary.js"

const instances = [
  { name: "app-1", status: "running", primary_ip: "192.168.1.10", cpu_cores: 2, memory_gb: 4, disk_gb: 50 },
  { name: "db-1", status: "stopped", cpu: 4, memory: 8, disks: [{ size_gb: 100 }, { size_gb: 50 }] },
  { name: "worker-1", status: "running", cpu_cores: 1, memory_gb: 2, disk_gb: 20 },
]

const summary = buildInventorySummary(instances)
assert.equal(summary.total, 3)
assert.equal(summary.running, 2)
assert.equal(summary.stopped, 1)
assert.equal(summary.visibleIpCount, 1)
assert.equal(summary.missingIpCount, 2)
assert.equal(summary.cpuCores, 7)
assert.equal(summary.memoryGb, 14)
assert.equal(summary.diskGb, 220)

assert.deepEqual(
  getInstanceOperationalSignals({ status: "running", primary_ip: null }),
  [{ tone: "warning", label: "No IP visible", detail: "Running VM has no discovered IP address" }]
)
assert.deepEqual(getInstanceOperationalSignals({ status: "stopped", primary_ip: null }), [])
