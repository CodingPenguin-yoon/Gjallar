import assert from 'node:assert/strict'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { evaluateRiskApprovalPolicy } = await importExpected(
  '../src/utils/riskPolicy.js',
  'MVP risk approval utility',
)

const redDecision = evaluateRiskApprovalPolicy({
  risks: [{ level: 'red', code: 'ip_collision' }],
  yellowRiskAcknowledged: true,
})
assert.equal(redDecision.canApprove, false)
assert.equal(redDecision.canExecute, false)
assert.match(redDecision.reason, /red/i)

const yellowDecision = evaluateRiskApprovalPolicy({
  risks: [{ level: 'yellow', code: 'dhcp_requires_discovery' }],
  yellowRiskAcknowledged: false,
})
assert.equal(yellowDecision.canApprove, false)
assert.equal(yellowDecision.requiresYellowAck, true)

const greenDecision = evaluateRiskApprovalPolicy({ risks: [], yellowRiskAcknowledged: false })
assert.equal(greenDecision.canApprove, true)
assert.equal(greenDecision.canExecute, true)

const whitespaceRedDecision = evaluateRiskApprovalPolicy({
  risks: [{ level: ' red ', code: 'ip_collision' }],
  yellowRiskAcknowledged: true,
})
assert.equal(whitespaceRedDecision.canApprove, false)
assert.equal(whitespaceRedDecision.canExecute, false)
assert.match(whitespaceRedDecision.reason, /red/i)

const unknownDecision = evaluateRiskApprovalPolicy({
  risks: [{ level: 'critical', code: 'unknown_risk_level' }],
  yellowRiskAcknowledged: true,
})
assert.equal(unknownDecision.canApprove, false)
assert.equal(unknownDecision.canExecute, false)
assert.match(unknownDecision.reason, /unknown|unsupported|malformed/i)

const uppercaseYellowDecision = evaluateRiskApprovalPolicy({
  risks: [{ level: ' YELLOW ', code: 'dhcp_requires_discovery' }],
  yellowRiskAcknowledged: false,
})
assert.equal(uppercaseYellowDecision.canApprove, false)
assert.equal(uppercaseYellowDecision.requiresYellowAck, true)

const nonArrayRiskDecision = evaluateRiskApprovalPolicy({
  risks: 'red',
  yellowRiskAcknowledged: true,
})
assert.equal(nonArrayRiskDecision.canApprove, false)
assert.equal(nonArrayRiskDecision.canExecute, false)
assert.match(nonArrayRiskDecision.reason, /malformed|unknown|array/i)

const nonStringLevelDecision = evaluateRiskApprovalPolicy({
  risks: [{ level: ['green'], code: 'malformed_level' }],
  yellowRiskAcknowledged: true,
})
assert.equal(nonStringLevelDecision.canApprove, false)
assert.equal(nonStringLevelDecision.canExecute, false)
assert.match(nonStringLevelDecision.reason, /malformed|unknown/i)


const nullRisksDecision = evaluateRiskApprovalPolicy({
  risks: null,
  yellowRiskAcknowledged: true,
})
assert.equal(nullRisksDecision.canApprove, false)
assert.equal(nullRisksDecision.canExecute, false)
assert.match(nullRisksDecision.reason, /malformed|unknown|array/i)

console.log('riskPolicy RED contract exercised')
