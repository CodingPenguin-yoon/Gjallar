"""RED tests for create/preflight/plan approval policy."""

import unittest


class PreflightPolicyTests(unittest.TestCase):
    def _evaluate(self, risks, yellow_ack=False):
        try:
            from app.vm_create.approval import evaluate_approval_gate
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.vm_create.approval.evaluate_approval_gate for Review & Confirm "
                f"policy, but it is missing: {exc}"
            )
        return evaluate_approval_gate(risks=risks, yellow_risk_acknowledged=yellow_ack)

    def test_red_risk_cannot_be_approved_even_with_ack(self):
        decision = self._evaluate([{"level": "red", "code": "bridge_missing"}], yellow_ack=True)
        self.assertFalse(decision.can_approve)
        self.assertFalse(decision.can_execute)
        self.assertIn("red", decision.reason.lower())

    def test_yellow_risk_requires_explicit_ack(self):
        decision = self._evaluate([{"level": "yellow", "code": "dhcp_requires_discovery"}], yellow_ack=False)
        self.assertFalse(decision.can_approve)
        self.assertTrue(decision.requires_yellow_ack)

    def test_green_risk_allows_approval(self):
        decision = self._evaluate([], yellow_ack=False)
        self.assertTrue(decision.can_approve)
        self.assertTrue(decision.can_execute)


if __name__ == "__main__":
    unittest.main()
