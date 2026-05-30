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
        status: 'pending',
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
      status: 'pending',
      target_id: 'node-a->node-b:101',
      risk_level: 'yellow',
      details: {
        approval_packet_id: 'drsap-1',
        recommendation_id: 'drs-rec-1',
        vm_identity_id: 'vmid-1',
        source_node_id: 'node-a',
        target_node_id: 'node-b',
        proxmox_upid: '',
        task_result: 'not_started',
        task_status: { status: 'pending' },
        task_exitstatus: '',
        post_check_status: 'not_started',
        reconciliation_reason: '',
        operation_lock_ids: ['lock-a', 'lock-b'],
        runnable: false,
        proxmox_mutation_enabled: false,
        side_effects: [],
      },
    }
  },
  async listJobArtifacts() {
    return []
  },
}, { selectedJobId: 'drs-mig-1' })

assert.equal(drsModel.selectedJob.type, 'drs_migration')
assert.equal(drsModel.selectedJob.drsMigrationSummary.title, 'DRS migration summary')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[0].items.find((item) => item.label === 'Approval packet').value, 'drsap-1')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[0].items.find((item) => item.label === 'Recommendation').value, 'drs-rec-1')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[0].items.find((item) => item.label === 'VM identity').value, 'vmid-1')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[1].items.find((item) => item.label === 'Runnable').value, '아니오')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[1].items.find((item) => item.label === 'Proxmox mutation enabled').value, '아니오')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[1].items.find((item) => item.label === 'Side effects').value, '-')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[1].items.find((item) => item.label === 'Task status').value, 'pending')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[2].items.find((item) => item.label === 'Post-check status').value, 'not_started')
assert.equal(drsModel.selectedJob.drsMigrationSummary.sections[2].items.find((item) => item.label === 'Operation locks').value, 'lock-a, lock-b')

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
