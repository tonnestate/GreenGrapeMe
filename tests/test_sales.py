import unittest
from greengrapeme.sales import Evidence, Opportunity, SalesTeam, Status


def identity():
    return Evidence("registry", "https://example.invalid/company/1", "same legal entity confirmed", "COMPANY_IDENTITY")


def signal():
    return Evidence("news", "https://example.invalid/news/1", "announced office expansion", "BUYING_SIGNAL")


def lead(*, evidence=None, verified=True, suppressed=False, lead_id="lead-1"):
    return Opportunity(lead_id, "Example GmbH", "offer-1",
                       tuple(evidence if evidence is not None else [identity(), signal()]),
                       verified_company=verified, suppressed=suppressed)


class Source:
    def __init__(self, *items):
        self.items = items

    def discover(self):
        return iter(self.items)


class SalesTeamTests(unittest.TestCase):
    def test_sourced_qualified_opportunity_creates_only_review_draft(self):
        result = SalesTeam().evaluate(lead())
        self.assertEqual(result.status, Status.QUALIFIED)
        self.assertEqual(result.actions[0].state, "DRAFT_PENDING_REVIEW")
        self.assertIn("NO_SENDING_AUTHORITY", result.actions[0].reason)
        self.assertEqual(len(result.evidence_refs), 2)

    def test_suppression_blocks_all_actions(self):
        result = SalesTeam().evaluate(lead(suppressed=True))
        self.assertEqual(result.status, Status.REJECTED)
        self.assertEqual(result.actions, ())

    def test_unverified_company_needs_review(self):
        result = SalesTeam().evaluate(lead(verified=False))
        self.assertEqual(result.reason, "IDENTITY_NOT_VERIFIED")
        self.assertEqual(result.actions, ())

    def test_signal_without_evidence_cannot_be_claimed(self):
        result = SalesTeam().evaluate(lead(evidence=[identity()]))
        self.assertEqual(result.reason, "NO_SOURCED_BUYING_SIGNAL")

    def test_conflicting_evidence_needs_review(self):
        conflict = Evidence("other", "https://example.invalid/conflict", "disputed legal company", "CONFLICT")
        result = SalesTeam().evaluate(lead(evidence=[identity(), signal(), conflict]))
        self.assertEqual(result.status, Status.NEEDS_REVIEW)
        self.assertEqual(result.reason, "SOURCE_CONFLICT")

    def test_missing_source_claim_is_rejected_at_boundary(self):
        with self.assertRaises(ValueError):
            Evidence("", "ref", "claim", "OTHER")

    def test_duplicate_opportunity_id_is_not_silently_processed(self):
        with self.assertRaisesRegex(ValueError, "duplicate opportunity id"):
            SalesTeam().run(Source(lead(), lead()))

    def test_source_integration_contract_returns_bounded_decisions(self):
        out = SalesTeam().run(Source(lead(), lead(lead_id="lead-2", suppressed=True)))
        self.assertEqual([x.status for x in out], [Status.QUALIFIED, Status.REJECTED])


if __name__ == "__main__":
    unittest.main()
