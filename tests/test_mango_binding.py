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
        return self.response if self.response is not None else {
            "project": {"entity_id": "project-canonical"},
            "family": {"entity_id": "family-canonical"},
            "spec": {"entity_id": "spec-canonical"},
            "work": {
                "plan": {"entity_id": "plan-canonical"},
                "slice": {"entity_id": "slice-canonical"}
            },
            "authority": "USER_INTENT_RELAYED_BY_CLIENT",
            "truth_level": "CANONICAL_UNVERIFIED",
            "discovery_promoted": False,
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
            self.assertEqual(first["mango_slice_id"], "slice-canonical")
            self.assertEqual(first["truth_level"], "CANONICAL_UNVERIFIED")
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(backend.calls[0]["actor_id"], "trusted-actor")
            self.assertIsNone(binder.status("tenant-2", "mission-1"))

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
            self.assertIsNone(binder.status("t", "m"))
            with self.assertRaises(ValueError):
                binder.admit("t", "m", backend=MangoHostFake(d, {"authority": "WRONG"}), **opts)
            self.assertIsNone(binder.status("t", "m"))

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
