"""Business-critical precedence when a source replays an inbound message ID."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity


class ReplaySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SalesWorkspace(Path(self.temp.name) / "sales.db")
        account = Opportunity(
            "account-0001", "Example GmbH", "offer", (
                Evidence("registry", "https://example.org/company",
                         "Original source identity", "COMPANY_IDENTITY"),
                Evidence("news", "https://example.org/news",
                         "Announced expansion", "BUYING_SIGNAL"),
            ), verified_company=True)
        self.store.ingest("tenant-a", [account])
        self.store.ingest("tenant-a", [
            Opportunity("account-0002", "Another GmbH", "offer", ())])
        self.store.run_cycle("tenant-a")

    def _reply(self, text, *, opportunity="account-0001",
               message_id="message-00001", subject=""):
        return self.store.ingest_reply(
            "tenant-a", opportunity, message_id, text, subject=subject)

    def _stored_state(self):
        with self.store._db() as db:
            result = db.execute(
                "SELECT result FROM inbox WHERE tenant=? AND message_id=?",
                ("tenant-a", "message-00001")).fetchone()
            escalations = db.execute(
                "SELECT count(*) FROM audit WHERE tenant=? AND "
                "event='REPLAYED_REPLY_SAFETY_ESCALATED'",
                ("tenant-a",)).fetchone()[0]
            return result["result"], escalations

    def test_later_optout_with_same_message_id_blocks_all_sales_work(self):
        self.assertEqual(self._reply("Thanks, please send the proposal."),
                         "NEEDS_CLASSIFICATION")
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 0)
        self.assertEqual(
            self._reply("Bitte keine weiteren E-Mails."),
            "OPT_OUT")
        self.assertEqual(self._stored_state(), ("OPT_OUT", 1))
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 1)
        relevant = [
            x for x in self.store.queue("tenant-a")
            if x["opportunity_id"] == "account-0001"]
        self.assertTrue(relevant)
        self.assertTrue(all(x["state"] == "BLOCKED" for x in relevant))
        self.assertEqual(
            self._reply("Thanks, please send the proposal."),
            "OPT_OUT")
        self.assertEqual(self._stored_state(), ("OPT_OUT", 1))
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 1)

    def test_privacy_request_escalates_existing_optout_without_demoting(self):
        self.assertEqual(self._reply("Stop contacting me."), "OPT_OUT")
        self.assertEqual(self._reply("Delete my data."), "PRIVACY_REVIEW")
        self.assertEqual(self._stored_state(), ("PRIVACY_REVIEW", 1))
        self.assertEqual(self._reply("Hi again."), "PRIVACY_REVIEW")
        self.assertEqual(self._stored_state(), ("PRIVACY_REVIEW", 1))
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 1)

    def test_bounced_transport_id_can_upgrade_to_customer_optout(self):
        self.assertEqual(
            self._reply("", subject="Mail delivery failed"),
            "BOUNCE")
        self.assertEqual(self._reply("Please unsubscribe me."), "OPT_OUT")
        self.assertEqual(self._stored_state(), ("OPT_OUT", 1))
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 1)

    def test_cross_account_replay_denied_and_does_not_suppress_another(self):
        self.assertEqual(self._reply("Thanks."), "NEEDS_CLASSIFICATION")
        with self.assertRaisesRegex(ValueError, "another opportunity"):
            self._reply("Stop emailing me.", opportunity="account-0002")
        self.assertEqual(self._stored_state(), ("NEEDS_CLASSIFICATION", 0))
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 0)

    def test_repeated_safety_replay_is_idempotent(self):
        self.assertEqual(self._reply("Okay."), "NEEDS_CLASSIFICATION")
        self.assertEqual(self._reply("Stop emailing me."), "OPT_OUT")
        self.assertEqual(self._reply("Stop emailing me."), "OPT_OUT")
        self.assertEqual(self._stored_state(), ("OPT_OUT", 1))


if __name__ == "__main__":
    unittest.main()
