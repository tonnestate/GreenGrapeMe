from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.mango_binding import MangoMissionBinding
from greengrapeme.missions import SalesMissionEngine
from greengrapeme.operations import SalesWorkspace


class MangoHostFake:
    def __init__(self, workspace, response=None):
        self.workspace = str(Path(workspace).resolve())
        self.calls = []
        self.response = response

    def attached_workspace(self):
        return self.workspace

    def enter_work(self, **kwargs):
        self.calls.append(kwargs)
        if self.response is None and kwargs.get("work_ref") is not None:
            value = self._default()
            value["disposition"] = "EXISTING_WORK_BOUND"
            return value
        return self.response if self.response is not None else self._default()

    @staticmethod
    def _default():
        return {
            "project": {"entity_id": "project-canonical"},
            "family": {"entity_id": "family-canonical"},
            "work_identity": {"entity_id": "work-canonical",
                              "family_id": "family-canonical",
                              "project_id": "project-canonical"},
            "normative_baseline": {"entity_id": "baseline-canonical"},
            "spec": None, "spec_admitted": False,
            "work": {
                "plan": {"entity_id": "plan-canonical"},
                "slice": {"entity_id": "slice-canonical"}
            },
            "disposition": "NEW_WORK_ADMITTED",
            "admission": {"identity_role": "DEDUP_HINT_ONLY"},
            "persistence": {"identity": "CANONICAL", "working_state": "PROGRESSIVE"},
        }


class MangoWorkBindingTests(unittest.TestCase):
    def test_actual_mango_shape_bound_once_to_authorized_tenant_mission(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            m = SalesMissionEngine(store)
            m.create("tenant-1", "mission-1", "offer", "Research evidence", "B2B")
            m.create("tenant-2", "mission-1", "offer", "Research evidence", "B2B")
            binder = MangoMissionBinding(store)
            backend = MangoHostFake(d)
            opts = {"actor_id": "trusted-actor",
                    "current_user_request": "Find relevant B2B customers",
                    "authorized_workspace": d,
                    "host_authorized": True,
                    "backend": backend}
            first = binder.admit("tenant-1", "mission-1", **opts)
            second = binder.admit("tenant-1", "mission-1", **opts)
            self.assertEqual(first, second)
            self.assertEqual(first["mango_family_id"], "family-canonical")
            self.assertEqual(first["mango_work_id"], "work-canonical")
            self.assertEqual(first["mango_normative_baseline_id"], "baseline-canonical")
            self.assertIsNone(first["mango_spec_id"])
            self.assertIs(first["spec_admitted"], False)
            self.assertEqual(first["admission_disposition"], "NEW_WORK_ADMITTED")
            self.assertEqual(first["mango_slice_id"], "slice-canonical")
            self.assertEqual(first["truth_level"], "CANONICAL_UNVERIFIED")
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(backend.calls[0]["actor_id"], "trusted-actor")
            self.assertIsNone(binder.status("tenant-2", "mission-1"))

    def test_real_mango_candidate_is_not_silently_admitted(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            candidate = {
                "project": {"entity_id": "project-canonical"},
                "family": {"entity_id": "family-canonical"},
                "work_identity": {"entity_id": "work-canonical"},
                "disposition": "EXISTING_WORK_CANDIDATE",
                "requires_explicit_work_ref": True,
            }
            binder = MangoMissionBinding(store)
            with self.assertRaisesRegex(ValueError, "not newly/explicitly"):
                binder.admit("t", "m", actor_id="a",
                    current_user_request="Find customers", authorized_workspace=d,
                    host_authorized=True, backend=MangoHostFake(d, candidate))
            self.assertEqual(binder.status("t", "m")["state"], "ADMISSION_UNCERTAIN")

    def test_mango_cannot_claim_spec_without_separate_spec_admission(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            actual = MangoHostFake(d).enter_work()
            actual["spec_admitted"] = True
            binder = MangoMissionBinding(store)
            with self.assertRaisesRegex(ValueError, "persistence boundary"):
                binder.admit("t", "m", actor_id="a",
                    current_user_request="Find customers", authorized_workspace=d,
                    host_authorized=True, backend=MangoHostFake(d, actual))
            self.assertEqual(binder.status("t", "m")["state"], "ADMISSION_UNCERTAIN")

    def test_explicit_mango_work_ref_reused_for_next_sales_batch(self):
        with TemporaryDirectory() as d:
            store=SalesWorkspace(Path(d)/"db")
            engine=SalesMissionEngine(store)
            engine.create("t","batch-one","offer","Find","B2B")
            engine.create("t","batch-two","offer","Find","B2B")
            binder=MangoMissionBinding(store)
            host=MangoHostFake(d)
            args={"actor_id":"a","current_user_request":"Find customers",
                  "authorized_workspace":d,"host_authorized":True,"backend":host}
            first=binder.admit("t","batch-one",**args)
            self.assertEqual(first["mango_work_id"],"work-canonical")
            second=binder.admit("t","batch-two",work_ref=first["mango_work_id"],**args)
            self.assertEqual(second["mango_work_id"],first["mango_work_id"])
            self.assertEqual(second["admission_disposition"],"EXISTING_WORK_BOUND")
            self.assertEqual(host.calls[1]["work_ref"],"work-canonical")

    def test_work_ref_mismatch_is_not_silent_rebinding(self):
        with TemporaryDirectory() as d:
            store=SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t","m","offer","Find","B2B")
            binder=MangoMissionBinding(store)
            host=MangoHostFake(d)
            with self.assertRaisesRegex(ValueError,"explicitly selected canonical work"):
                binder.admit("t","m",actor_id="a",
                    current_user_request="Find customers",
                    authorized_workspace=d,host_authorized=True,
                    backend=host,work_ref="unrelated-work-id")
            self.assertEqual(binder.status("t","m")["state"],"ADMISSION_UNCERTAIN")

    def test_host_authorization_is_mandatory_and_no_work_created(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            fake = MangoHostFake(d)
            with self.assertRaises(PermissionError):
                MangoMissionBinding(store).admit("t", "m", actor_id="a",
                    current_user_request="Find customers",
                    authorized_workspace=d, host_authorized=False, backend=fake)
            self.assertEqual(fake.calls, [])

    def test_cross_workspace_binding_is_denied(self):
        with TemporaryDirectory() as d, TemporaryDirectory() as other:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            fake = MangoHostFake(other)
            with self.assertRaisesRegex(PermissionError, "workspace"):
                MangoMissionBinding(store).admit("t", "m", actor_id="a",
                    current_user_request="Find customers",
                    authorized_workspace=d, host_authorized=True, backend=fake)
            self.assertEqual(fake.calls, [])

    def test_conflicting_authority_input_requires_reconciliation(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            binder = MangoMissionBinding(store)
            fake = MangoHostFake(d)
            kwargs = {"actor_id": "a", "authorized_workspace": d,
                      "host_authorized": True, "backend": fake}
            binder.admit("t", "m", current_user_request="Find customers", **kwargs)
            with self.assertRaisesRegex(ValueError, "reconcile"):
                binder.admit("t", "m", current_user_request="Different work", **kwargs)
            self.assertEqual(len(fake.calls), 1)

    def test_unverified_or_rejected_mango_response_never_creates_binding(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            binder = MangoMissionBinding(store)
            opts = {"actor_id": "a", "current_user_request": "Find customers",
                    "authorized_workspace": d, "host_authorized": True}
            with self.assertRaises(RuntimeError):
                binder.admit("t", "m", backend=MangoHostFake(d, {"ok": False}), **opts)
            uncertain = binder.status("t", "m")
            self.assertEqual(uncertain["state"], "ADMISSION_UNCERTAIN")
            self.assertTrue(uncertain["requires_canonical_reconciliation"])
            # A second call cannot duplicate a possibly admitted canonical work.
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                binder.admit("t", "m", backend=MangoHostFake(d, {"authority": "WRONG"}), **opts)
            self.assertEqual(binder.status("t", "m")["state"], "ADMISSION_UNCERTAIN")

    def test_canonical_admission_exception_is_fenced_before_retry(self):
        class UncertainHost(MangoHostFake):
            def enter_work(self, **kwargs):
                self.calls.append(kwargs)
                raise TimeoutError("canonical response lost")

        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            SalesMissionEngine(store).create("t", "m", "offer", "Research", "B2B")
            binder = MangoMissionBinding(store)
            host = UncertainHost(d)
            opts = {"actor_id": "a", "current_user_request": "Find customers",
                    "authorized_workspace": d, "host_authorized": True, "backend": host}
            with self.assertRaises(TimeoutError):
                binder.admit("t", "m", **opts)
            self.assertEqual(binder.status("t", "m")["state"], "ADMISSION_UNCERTAIN")
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                binder.admit("t", "m", **opts)
            self.assertEqual(len(host.calls), 1)

    def test_mission_not_found_does_not_create_canonical_work(self):
        with TemporaryDirectory() as d:
            store = SalesWorkspace(Path(d)/"db")
            fake = MangoHostFake(d)
            with self.assertRaisesRegex(ValueError, "unknown mission"):
                MangoMissionBinding(store).admit("tenant", "missing",
                    actor_id="actor", current_user_request="Find customers",
                    authorized_workspace=d, host_authorized=True, backend=fake)
            self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
