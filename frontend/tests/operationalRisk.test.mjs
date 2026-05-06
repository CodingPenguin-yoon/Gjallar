import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  formatRiskPolicyProfile,
  formatRiskScope,
  getRiskCategoryLabel,
  getRiskSeverityTone,
  groupRisksByCategory,
  normalizeRiskThresholds,
  validateRiskThresholdDraft,
  normalizeRiskDashboard,
  sortRiskItems,
} from '../src/utils/operationalRisk.js'

const payload = {
  status: 'warning',
  generated_at: 1700000000,
  summary: {
    total_risks: 3,
    critical: 1,
    warning: 1,
    info: 1,
    affected_nodes: 2,
    affected_vms: 1,
    total_nodes: 3,
    total_vms: 7,
    categories: { storage_capacity: 1, governance: 1, guest_agent: 1 },
  },
  risk_items: [
    { id: 'info', severity: 'info', category: 'governance', scope: 'vm', node: 'node-b', vmid: 20, vm_name: 'vm-b' },
    { id: 'critical', severity: 'critical', category: 'storage_capacity', scope: 'storage', node: 'node-a' },
    { id: 'warning', severity: 'warning', category: 'guest_agent', scope: 'vm', node: 'node-a', vmid: 10, vm_name: 'vm-a' },
  ],
}

const dashboard = normalizeRiskDashboard(payload)
assert.equal(dashboard.summary.totalRisks, 3)
assert.equal(dashboard.summary.affectedNodes, 2)
assert.equal(getRiskSeverityTone('critical').level, 'critical')
assert.equal(getRiskCategoryLabel('long_stopped'), 'Long stopped VM')
assert.equal(getRiskCategoryLabel('governance'), 'Governance')
assert.equal(getRiskCategoryLabel('restore_readiness'), 'Restore readiness')

assert.equal(getRiskCategoryLabel('pbs_datastore_capacity'), 'PBS datastore capacity')
assert.equal(getRiskCategoryLabel('pbs_datastore_health'), 'PBS datastore health')
assert.equal(getRiskCategoryLabel('restore_drill'), 'Restore drill')
assert.equal(getRiskCategoryLabel('guest_ssh_evidence'), 'Guest SSH evidence')
assert.equal(getRiskCategoryLabel('compliance'), 'Compliance')
assert.equal(formatRiskScope({ scope: 'pbs_datastore', datastore: 'pbs-store' }), 'pbs-store')
assert.equal(getRiskSeverityTone('unknown').level, 'info')
assert.deepEqual(sortRiskItems(payload.risk_items).map((item) => item.id), ['critical', 'warning', 'info'])
assert.equal(Object.keys(groupRisksByCategory(payload.risk_items)).length, 3)
assert.equal(formatRiskScope(payload.risk_items[2]), 'node-a/10 vm-a')


const thresholds = normalizeRiskThresholds({
  storage_warning_percent: '85',
  storage_critical_percent: 95,
  stopped_warning_days: '14',
})
assert.equal(thresholds.storageWarningPercent, 85)
assert.equal(thresholds.storageCriticalPercent, 95)
assert.equal(thresholds.stoppedWarningDays, 14)
assert.equal(thresholds.snapshotWarningDays, 14)

assert.deepEqual(validateRiskThresholdDraft({ ...thresholds, storageWarningPercent: 96, storageCriticalPercent: 90 }), {
  valid: false,
  message: 'Storage warning threshold must be lower than or equal to critical threshold.',
})
assert.deepEqual(validateRiskThresholdDraft({ ...thresholds, stoppedWarningDays: 3651, stoppedCriticalDays: 3651 }), {
  valid: false,
  message: 'Day-based thresholds must be 3650 days or lower.',
})
assert.equal(validateRiskThresholdDraft(thresholds).valid, true)

const overrideDashboard = normalizeRiskDashboard({
  status: 'warning',
  summary: {
    total_risks: 1,
    critical: 0,
    warning: 1,
    info: 0,
    acknowledged: 1,
    suppressed: 1,
  },
  risk_items: [
    {
      id: 'vm:node-a/101:backup-recency',
      severity: 'warning',
      override: { status: 'acknowledged', reason: 'accepted', updated_at: 1700000000 },
    },
  ],
  suppressed_risk_items: [
    {
      id: 'storage:node-a:local:capacity',
      severity: 'critical',
      override: { status: 'suppressed', reason: 'lab exception', updated_at: 1700000000 },
    },
  ],
})
assert.equal(overrideDashboard.summary.acknowledged, 1)
assert.equal(overrideDashboard.summary.suppressed, 1)
assert.equal(overrideDashboard.riskItems[0].override.status, 'acknowledged')
assert.equal(overrideDashboard.riskItems[0].override.updatedAt, 1700000000)
assert.equal(overrideDashboard.suppressedRiskItems[0].id, 'storage:node-a:local:capacity')
assert.equal(overrideDashboard.suppressedRiskItems[0].override.status, 'suppressed')

const profileDashboard = normalizeRiskDashboard({
  status: 'warning',
  summary: { total_risks: 1, warning: 1 },
  evidence: {
    rpo_rto_profile_collected: true,
    rpo_rto_profile_vms: 1,
    rpo_rto_profile_sources: { vm_override: 1 },
  },
  risk_items: [
    {
      id: 'vm:node-a/307:restore-readiness',
      severity: 'warning',
      category: 'restore_readiness',
      scope: 'vm',
      node: 'node-a',
      vmid: 307,
      vm_name: 'critical-profile-vm',
      evidence: {
        rpo_rto_profile_id: 'critical',
        rpo_rto_profile_source: 'vm_override',
        rpo_hours: 24,
        restore_drill_max_age_days: 30,
      },
    },
  ],
})
assert.equal(profileDashboard.evidence.rpo_rto_profile_collected, true)
assert.equal(normalizeRiskDashboard({ evidence: { ssh_guest_collected: false, ssh_guest_vms: null, ssh_guest_failed_vms: null } }).evidence.ssh_guest_collected, false)
assert.deepEqual(profileDashboard.riskItems[0].rpoRtoProfile, {
  profileId: 'critical',
  source: 'vm_override',
  rpoHours: 24,
  restoreDrillMaxAgeDays: 30,
})
assert.equal(formatRiskPolicyProfile(profileDashboard.riskItems[0]), 'critical · RPO 24h · drill 30d')
assert.equal(getRiskCategoryLabel('rpo_violation'), 'RPO violation')


const suggestionDashboard = normalizeRiskDashboard({
  status: 'warning',
  summary: { total_risks: 1, warning: 1 },
  risk_items: [
    {
      id: 'vm:node-a/501:backup-coverage',
      severity: 'warning',
      category: 'backup_coverage',
      suggested_actions: [
        {
          action_id: 'review-backup-coverage',
          label: 'Review backup coverage',
          link: '/risks?category=backup_coverage',
          requires_approval: true,
          execution_mode: 'proposal_only',
          mutation_allowed: false,
        },
      ],
    },
  ],
})
assert.equal(suggestionDashboard.riskItems[0].suggestedActions.length, 1)
assert.equal(suggestionDashboard.riskItems[0].suggestedActions[0].actionId, 'review-backup-coverage')
assert.equal(suggestionDashboard.riskItems[0].suggestedActions[0].requiresApproval, true)
assert.equal(suggestionDashboard.riskItems[0].suggestedActions[0].executionMode, 'proposal_only')
assert.equal(suggestionDashboard.riskItems[0].suggestedActions[0].mutationAllowed, false)
assert.equal(suggestionDashboard.riskItems[0].suggestedActions[0].approvalLabel, 'Approval required')

const fallbackSuggestionDashboard = normalizeRiskDashboard({
  status: 'warning',
  summary: { total_risks: 1, warning: 1 },
  risk_items: [{ id: 'risk-with-default-suggestion', suggested_actions: [{}] }],
})
assert.equal(fallbackSuggestionDashboard.riskItems[0].suggestedActions[0].link, '/risks')

const riskDashboardComponentSource = readFileSync(new URL('../src/components/OperationalRiskDashboard.jsx', import.meta.url), 'utf8')
assert.ok(riskDashboardComponentSource.includes("href={action.link || '/risks'}"))
assert.ok(!riskDashboardComponentSource.includes('/operations/risks'))

console.log('operationalRisk tests passed')
