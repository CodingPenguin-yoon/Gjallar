import assert from 'node:assert/strict'
import { buildTaskBoardSummary, describeTaskTarget } from '../src/utils/taskBoardSummary.js'

const tasks = [
  { task_id: 'a', status: 'Running', metadata: { server_name: 'web-01', server_id: 'pve-01' } },
  { task_id: 'b', status: 'Failed', metadata: { vm_name: 'db-01', vm_node: 'pve-02' } },
  { task_id: 'c', status: 'Success', archived: true, metadata: {} },
]
const summary = buildTaskBoardSummary(tasks)
assert.equal(summary.total, 3)
assert.equal(summary.live, 1)
assert.equal(summary.failed, 1)
assert.equal(summary.done, 2)
assert.equal(summary.archived, 1)
assert.equal(describeTaskTarget(tasks[0]), 'web-01 @ pve-01')
assert.equal(describeTaskTarget(tasks[1]), 'db-01 @ pve-02')

console.log('taskBoardSummary tests passed')
