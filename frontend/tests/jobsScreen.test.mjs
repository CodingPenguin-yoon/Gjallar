import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { loadJobsScreenModel } = await importExpected(
  '../src/utils/jobsScreen.js',
  'Jobs/Runs screen loader'
)

const calls = []
const fakeClient = {
  async listJobs() {
    calls.push('listJobs')
    return [
      {
        job_id: 'job-plan',
        job_type: 'vm_create',
        status: 'completed',
        target_id: 'general-vm:web-01',
        risk_level: 'green',
        artifact_count: 2,
        risk_count: 0,
        progress_percent: 100,
        message: 'VM 생성이 완료되었습니다.',
        steps: [{ id: 'create', label: 'VM 생성', status: 'completed', message: 'done' }],
        started_at: '2026-05-09T14:00:00+09:00',
        finished_at: '2026-05-09T14:01:00+09:00',
        artifacts_url: '/api/v1/jobs/job-plan/artifacts',
      },
      {
        job_id: 'job-risk',
        job_type: 'vm_create_preflight',
        status: 'blocked',
        target_id: 'general-vm:db-01',
        risk_level: 'red',
        artifact_count: 1,
        risk_count: 2,
      },
    ]
  },
  async getJob(jobId) {
    calls.push(`getJob:${jobId}`)
    return {
      job_id: jobId,
      job_type: 'vm_create',
      status: 'completed',
      target_id: 'general-vm:web-01',
      risk_level: 'green',
      artifact_count: 2,
      risk_count: 0,
      progress_percent: 100,
      message: 'VM 생성이 완료되었습니다.',
      steps: [{ id: 'create', label: 'VM 생성', status: 'completed', message: 'done' }],
      started_at: '2026-05-09T14:00:00+09:00',
      finished_at: '2026-05-09T14:01:00+09:00',
      details: {
        vm_name: 'web-01',
        vmid: 120,
        target_node_id: 'node-a',
        storage_id: 'local-lvm',
        template_id: 'ubuntu-template',
        hardware: { cpu_cores: 2, memory_mb: 4096, disk_gb: 50 },
        access: {
          cloud_init_user: 'yoon1',
          ssh_key_fingerprint: 'SHA256:test',
          password_login_disabled: true,
        },
        network: {
          bridge_id: 'vmbr0',
          ip_mode: 'static',
          static_ip: '192.168.2.150',
          prefix: 24,
          gateway: '192.168.2.1',
        },
        proxmox_preview: {
          clone: { template_node: 'node-a', template_vmid: 9000, storage: 'local-lvm' },
          config: {
            cores: 2,
            memory: 4096,
            agent: 'enabled=1',
            ciuser: 'yoon1',
            sshkeys: '[REDACTED]',
            net0: 'virtio,bridge=vmbr0',
            ipconfig0: 'ip=192.168.2.150/24,gw=192.168.2.1',
          },
        },
        proxmox_create: {
          status: 'completed',
          task: { exitstatus: 'OK' },
          resize: { action: 'not_needed', requested_disk_gb: 50 },
          observed_after: {
            status: 'stopped',
            post_check_status: 'completed',
            fingerprint: { hash: 'sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef' },
          },
        },
      },
    }
  },
  async listJobArtifacts(jobId) {
    calls.push(`listJobArtifacts:${jobId}`)
    return [
      { artifact_id: 'plan-json', kind: 'plan', path: 'db://job-artifacts/plan-json', storage_backend: 'db', checksum: 'sha256:abc' },
      { artifact_id: 'review-md', kind: 'review', path: 'db://job-artifacts/review-md', storage_backend: 'db', checksum: 'sha256:def' },
    ]
  },
  async getTasks() {
    calls.push('getTasks')
    throw new Error('legacy getTasks must not be called')
  },
  createTaskEventStream() {
    calls.push('createTaskEventStream')
    throw new Error('legacy task event stream must not be opened')
  },
  async archiveTask() {
    calls.push('archiveTask')
    throw new Error('legacy archiveTask must not be called')
  },
}

const model = await loadJobsScreenModel(fakeClient, { selectedJobId: 'job-plan' })
assert.deepEqual(calls, ['listJobs', 'getJob:job-plan', 'listJobArtifacts:job-plan'])
assert.equal(model.readOnly, true)
assert.deepEqual(model.allowedActions, [])
assert.equal(model.summary.total, 2)
assert.equal(model.summary.completed, 1)
assert.equal(model.summary.blocked, 1)
assert.equal(model.selectedJob.id, 'job-plan')
assert.equal(model.selectedJob.readOnly, true)
assert.deepEqual(model.selectedJob.allowedActions, [])
assert.equal(model.selectedJob.progressPercent, 100)
assert.equal(model.selectedJob.message, 'VM 생성이 완료되었습니다.')
assert.equal(model.selectedJob.steps[0].label, 'VM 생성')
assert.equal(model.selectedJob.vmSummary.title, 'web-01 생성 요약')
assert.equal(model.selectedJob.vmSummary.subtitle, 'VMID 120 · node-a')
assert.equal(model.selectedJob.vmSummary.sections[1].items.find((item) => item.label === '메모리').value, '4 GB')
assert.equal(model.selectedJob.vmSummary.sections[2].items.find((item) => item.label === '브릿지').value, 'vmbr0')
assert.equal(model.selectedJob.vmSummary.sections[2].items.find((item) => item.label === '요청 IP').value, '192.168.2.150/24')
assert.equal(model.selectedJob.vmSummary.sections[2].items.find((item) => item.label === '관찰 IP').value, '아직 관찰되지 않음')
assert.equal(model.selectedJob.vmSummary.sections[3].items.find((item) => item.label === 'QEMU agent').value, '활성화 요청')
assert.equal(model.artifacts.length, 2)
assert.deepEqual(model.artifacts.map((artifact) => artifact.id), ['plan-json', 'review-md'])
assert.equal(model.artifacts[0].readOnly, true)
assert.equal(model.artifacts[0].storageBackend, 'db')
assert.deepEqual(model.artifacts[0].allowedActions, [])

const drsModel = await loadJobsScreenModel({
  async listJobs() {
    return [
      {
        job_id: 'drs-mig-1',
        job_type: 'drs_migration',
        status: 'needs_reconciliation',
        target_id: 'node-a->node-b:101',
        risk_level: 'yellow',
        artifact_count: 4,
      },
    ]
  },
  async getJob() {
    return {
      job_id: 'drs-mig-1',
      job_type: 'drs_migration',
      status: 'needs_reconciliation',
      target_id: 'node-a->node-b:101',
      risk_level: 'yellow',
      details: {
        approval_packet_id: 'drsap-1',
        recommendation_id: 'drs-rec-1',
        vm_identity_id: 'vmid-1',
        source_node_id: 'node-a',
        target_node_id: 'node-b',
        proxmox_upid: 'UPID:node-a:0001:migrate',
        task_result: 'ok',
        task_status: { status: 'stopped', exitstatus: 'OK' },
        task_exitstatus: 'OK',
        post_check_status: 'needs_reconciliation',
        reconciliation_reason: 'fingerprint_mismatch',
        operation_lock_ids: ['lock-a', 'lock-b'],
        runnable: false,
        proxmox_mutation_enabled: true,
        side_effects: ['drs_operation_locks_acquired', 'proxmox_migrate_invoked', 'proxmox_task_polled'],
        drs_evidence: {
          read_only: true,
          allowed_actions: [],
          current_mutation_controls: [],
          runnable: false,
          approval_packet: {
            id: 'drsap-1',
            status: 'approved',
            warning_acknowledged: false,
            warning_codes: [],
          },
          recommendation_id: 'drs-rec-1',
          vm: { identity_id: 'vmid-1', vmid: 101 },
          route: { source_node_id: 'node-a', target_node_id: 'node-b' },
          actors: {
            approved: { user_id: 'operator-1', username: 'operator', role: 'operator' },
            executed: { user_id: 'operator-2', username: 'executor', role: 'operator' },
          },
          execution_acknowledgement: { field: 'drs_live_migration_acknowledged', value: true },
          final_precheck_summary: {
            status: 'would_pass',
            would_be_executable: true,
            blockers: [],
            check_statuses: {
              identity: { status: 'pass' },
              policy: { status: 'pass' },
              route: { status: 'warning' },
              proxmox_active_task: { status: 'not_collected' },
            },
            criteria_details: [
              { code: 'migration_policy_allowed', status: 'pass', authority: 'gjallar_drs_gate', category: 'policy_gate', action_blocked: 'none' },
              { code: 'proxmox_active_task_not_collected', status: 'not_collected', authority: 'proxmox_final_technical_gate', category: 'technical_gate', action_blocked: 'execute' },
            ],
            advisory_signals: [
              { code: 'route_unknown', status: 'warning', authority: 'advisor_prefilter_signal', category: 'advisory', action_blocked: 'none' },
            ],
            technical_gate_status: {
              authority: 'proxmox_final_technical_gate',
              category: 'technical_gate',
              status: 'not_collected',
              action_blocked: 'execute',
              criteria: ['proxmox_active_task_not_collected'],
            },
          },
          live_precheck: {
            status: 'pass',
            blockers: [],
            check_statuses: {
              proxmox_active_task: { status: 'pass' },
              proxmox_cluster_quorum: { status: 'pass' },
            },
          },
          operation_lock: {
            lock_ids: ['lock-a', 'lock-b'],
            checked_scopes: [{ scope_type: 'vm_identity', scope_key: 'cluster-a|vm_identity|vmid-1' }],
            locks: [
              { operation_lock_id: 'lock-a', status: 'reconciliation_required', scope_type: 'vm_identity', reason: 'fingerprint_mismatch' },
              { operation_lock_id: 'lock-b', status: 'reconciliation_required', scope_type: 'route', reason: 'fingerprint_mismatch' },
            ],
          },
          task: {
            upid: 'UPID:node-a:0001:migrate',
            node: 'node-a',
            result: 'ok',
            status: 'stopped',
            exitstatus: 'OK',
            log_excerpt: [{ n: 1, t: 'migration done' }],
          },
          post_check: {
            status: 'needs_reconciliation',
            blockers: ['fingerprint_mismatch'],
            expected: { target_node_id: 'node-b', vmid: 101, power_state: 'running', stable_fingerprint: 'sha256:expected-fingerprint' },
            observed: { node_id: 'node-b', vmid: 101, power_state: 'running', stable_fingerprint: 'sha256:observed-fingerprint' },
            fingerprint: { expected: 'sha256:expected-fingerprint', observed: 'sha256:observed-fingerprint', matches: false },
          },
          reconciliation: {
            required: true,
            reason: 'fingerprint_mismatch',
            events: [{ event_id: 'drsrec-1', status: 'open', reason: 'fingerprint_mismatch' }],
            resolved_events: [{ event_id: 'drsrec-0', status: 'resolved', reason: 'resolved_after_verified_post_check' }],
          },
          historical_execution: {
            proxmox_mutation_recorded: true,
            side_effects: ['drs_operation_locks_acquired', 'proxmox_migrate_invoked', 'proxmox_task_polled'],
          },
        },
      },
    }
  },
  async listJobArtifacts() {
    return [
      {
        artifact_id: 'artifact_drs_final_precheck',
        type: 'drs_final_precheck',
        path: 'db://job-artifacts/artifact_drs_final_precheck',
        storage_backend: 'db',
        size_bytes: 2048,
        checksum: 'sha256:final',
      },
      {
        artifact_id: 'artifact_drs_migration_execution',
        type: 'drs_migration_execution',
        path: 'db://job-artifacts/artifact_drs_migration_execution',
        storage_backend: 'db',
        size_bytes: 4096,
        checksum: 'sha256:execution',
      },
    ]
  },
}, { selectedJobId: 'drs-mig-1' })

assert.equal(drsModel.selectedJob.type, 'drs_migration')
assert.equal(drsModel.selectedJob.drsMigrationSummary.title, 'DRS migration summary')
const drsSummary = drsModel.selectedJob.drsMigrationSummary
const drsSection = (title) => drsSummary.sections.find((section) => section.title === title)
const drsValue = (title, label) => drsSection(title).items.find((item) => item.label === label).value
assert.equal(drsValue('Read-only state', 'Read-only evidence'), '예')
assert.equal(drsValue('Read-only state', 'Allowed actions'), '-')
assert.equal(drsValue('Read-only state', 'Current mutation controls'), '-')
assert.equal(drsValue('Approval / intent', 'Approval packet'), 'drsap-1')
assert.equal(drsValue('Approval / intent', 'Packet status'), 'approved')
assert.equal(drsValue('Approval / intent', 'Recommendation'), 'drs-rec-1')
assert.equal(drsValue('Approval / intent', 'VM identity'), 'vmid-1')
assert.equal(drsValue('Approval / intent', 'VMID'), '101')
assert.equal(drsValue('Approval / intent', 'Approved actor'), 'operator')
assert.equal(drsValue('Approval / intent', 'Executed actor'), 'executor')
assert.equal(drsValue('Approval / intent', 'Execution acknowledgement'), 'drs_live_migration_acknowledged=예')
assert.match(drsValue('Final pre-check', 'Check statuses'), /proxmox_active_task: not_collected/)
assert.match(drsValue('Final pre-check', 'Technical gate'), /proxmox_final_technical_gate/)
assert.match(drsValue('Final pre-check', 'Criteria statuses'), /migration_policy_allowed: pass/)
assert.match(drsValue('Final pre-check', 'Advisory signals'), /route_unknown: warning/)
assert.equal(drsValue('Historical execution evidence', 'Recorded Proxmox mutation'), '예')
assert.match(drsValue('Historical execution evidence', 'Side effects'), /proxmox_migrate_invoked/)
assert.equal(drsValue('Historical execution evidence', 'Proxmox UPID'), 'UPID:node-a:0001:migrate')
assert.equal(drsValue('Historical execution evidence', 'Task node'), 'node-a')
assert.equal(drsValue('Historical execution evidence', 'Task result'), 'ok')
assert.equal(drsValue('Historical execution evidence', 'Task status'), 'stopped')
assert.equal(drsValue('Historical execution evidence', 'Task exitstatus'), 'OK')
assert.equal(drsValue('Historical execution evidence', 'Task log excerpt'), 'migration done')
assert.match(drsValue('Locks / reconciliation', 'Operation lock ids'), /lock-a, lock-b/)
assert.match(drsValue('Locks / reconciliation', 'Lock records'), /reconciliation_required/)
assert.equal(drsValue('Locks / reconciliation', 'Post-check status'), 'needs_reconciliation')
assert.match(drsValue('Locks / reconciliation', 'Post-check blockers'), /fingerprint_mismatch/)
assert.match(drsValue('Locks / reconciliation', 'Fingerprint'), /아니오/)
assert.equal(drsValue('Locks / reconciliation', 'Reconciliation required'), '예')
assert.equal(drsValue('Locks / reconciliation', 'Reconciliation reason'), 'fingerprint_mismatch')
assert.match(drsValue('Locks / reconciliation', 'Reconciliation events'), /drsrec-1:open:fingerprint_mismatch/)
assert.match(drsValue('Locks / reconciliation', 'Resolved events'), /drsrec-0:resolved:resolved_after_verified_post_check/)
assert.deepEqual(drsSummary.artifacts.map((artifact) => artifact.type), ['drs_final_precheck', 'drs_migration_execution'])
assert.deepEqual(drsSummary.artifacts.map((artifact) => artifact.id), ['artifact_drs_final_precheck', 'artifact_drs_migration_execution'])
assert.equal(drsSummary.artifacts[0].storageBackend, 'db')
assert.equal(drsSummary.artifacts[0].sizeBytes, 2048)
assert.equal(drsSummary.artifacts[0].checksum, 'sha256:final')
assert.equal(drsSummary.artifacts[0].path, undefined)

const source = readFileSync(new URL('../src/components/TaskBoard.jsx', import.meta.url), 'utf8')
assert.match(source, /apiV1Client/)
assert.match(source, /loadJobsScreenModel/)
assert.match(source, /진행 상황/)
assert.match(source, /생성 VM 요약/)
assert.match(source, /DRS migration summary/)
assert.match(source, /useSearchParams/)
assert.doesNotMatch(source, /artifact\.path/, 'Jobs screen must not render internal artifact storage paths')
assert.doesNotMatch(source, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'TaskBoard must not import the legacy /api client')
assert.doesNotMatch(source, /executeDrsMigrationJob|reconcilePreviewDrsMigrationJob|createDrsApprovalPacket/, 'Jobs screen must not expose DRS mutation controls')
assert.doesNotMatch(source, /recordPostCreateReadinessEvidence|postCreateReadinessEvidence|post-create-readiness-evidence/, 'Jobs screen must not expose post-create readiness mutation controls')

const forbidden = (...parts) => parts.join('')
for (const blocked of [
  forbidden('create', 'TaskEventStream'),
  forbidden('archive', 'Task'),
  forbidden('get', 'Tasks'),
  forbidden('get', 'TaskDetail'),
  forbidden('Event', 'Source'),
  forbidden('/api/', 'tasks'),
  forbidden('/api/', 'logs'),
  forbidden('/api/', 'status'),
  forbidden('tf_', 'apply'),
  forbidden('Terraform', ' apply'),
  forbidden('Archive'),
  forbidden('delete'),
  forbidden('terminate'),
  forbidden('Power'),
  forbidden('window.', 'confirm'),
  forbidden('window.', 'prompt'),
]) {
  assert.ok(!source.toLowerCase().includes(blocked.toLowerCase()), `Jobs screen must not expose legacy/destructive term: ${blocked}`)
}

const failureModel = await loadJobsScreenModel({
  async listJobs() {
    return [{ job_id: 'job-failed', job_type: 'vm_create', status: 'failed', target_id: 'yoonserver3:web-02' }]
  },
  async getJob() {
    return {
      job_id: 'job-failed',
      job_type: 'vm_create',
      status: 'failed',
      target_id: 'yoonserver3:web-02',
      details: {
        vm_name: 'web-02',
        vmid: 134,
        target_node_id: 'yoonserver3',
        storage_id: 'server3-storage',
        network: { bridge_id: 'vmbr0', ip_mode: 'dhcp' },
        proxmox_preview: {
          clone: { template_node: 'yoonmanserver', target: 'yoonserver3', storage: 'server3-storage' },
          config: { ipconfig0: 'ip=dhcp', net0: 'virtio,bridge=vmbr0' },
        },
        proxmox_create: {
          status: 'failed',
          task: {
            response_json: {
              message: "storage 'server3-storage' is not available on node 'yoonmanserver'\n",
            },
          },
        },
      },
    }
  },
  async listJobArtifacts() {
    return []
  },
}, { selectedJobId: 'job-failed' })

assert.equal(failureModel.selectedJob.vmSummary.sections[2].items.find((item) => item.label === '요청 IP').value, 'DHCP 요청')
assert.equal(failureModel.selectedJob.vmSummary.sections[2].items.find((item) => item.label === '관찰 IP').value, '생성 실패로 미확인')
assert.equal(failureModel.selectedJob.vmSummary.advice.title, '스토리지 조합 확인 필요')
assert.match(failureModel.selectedJob.vmSummary.advice.message, /server3-storage/)
assert.ok(failureModel.selectedJob.vmSummary.advice.actions.some((action) => action.includes('yoonmanserver')))

const bootVerifiedModel = await loadJobsScreenModel({
  async listJobs() {
    return [{ job_id: 'job-boot', job_type: 'vm_create', status: 'completed', target_id: 'node-a:web-03' }]
  },
  async getJob() {
    return {
      job_id: 'job-boot',
      job_type: 'vm_create',
      status: 'completed',
      target_id: 'node-a:web-03',
      details: {
        vm_name: 'web-03',
        vmid: 135,
        target_node_id: 'node-a',
        storage_id: 'nas-server',
        template_id: 'ubuntu-template',
        power_policy: 'boot_and_verify',
        network: { bridge_id: 'vmbr0', ip_mode: 'dhcp' },
        proxmox_preview: {
          clone: { template_node: 'node-a', target: 'node-a', storage: 'nas-server' },
          config: { agent: 'enabled=1', ciuser: 'yoon2', ipconfig0: 'ip=dhcp', net0: 'virtio,bridge=vmbr0' },
        },
        proxmox_create: {
          status: 'completed',
          start_task: { exitstatus: 'OK' },
          observed_after: {
            status: 'running',
            post_check_status: 'completed',
            power_policy: 'boot_and_verify',
            guest_agent: { available: true, ip_addresses: ['192.168.2.151'] },
            ip_addresses: ['192.168.2.151'],
            primary_ip: '192.168.2.151',
            cloud_init: { success: true, status: 'done' },
            boot_verification: { success: true, primary_ip: '192.168.2.151' },
          },
        },
      },
    }
  },
  async listJobArtifacts() {
    return []
  },
}, { selectedJobId: 'job-boot' })

assert.equal(bootVerifiedModel.selectedJob.vmSummary.sections[2].items.find((item) => item.label === '관찰 IP').value, '192.168.2.151')
assert.equal(bootVerifiedModel.selectedJob.vmSummary.sections[3].items.find((item) => item.label === 'Agent 관찰').value, '확인됨 (192.168.2.151)')
assert.equal(bootVerifiedModel.selectedJob.vmSummary.sections[3].items.find((item) => item.label === 'Cloud-init 확인').value, '완료')
assert.equal(bootVerifiedModel.selectedJob.vmSummary.sections[4].items.find((item) => item.label === '생성 후 상태').value, '부팅 후 확인')
assert.equal(bootVerifiedModel.selectedJob.vmSummary.sections[4].items.find((item) => item.label === 'Post-check').value, '부팅 확인 완료')

console.log('jobsScreen RED contract exercised')
