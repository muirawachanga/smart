import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "intelligent_ordering"


class Invalid(Exception):
    pass


class TestPolicies(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(Invalid(message)))
        self.frappe.ValidationError = Invalid
        self.frappe.db = Mock()
        self.frappe.get_all = Mock()
        self.frappe.get_doc = Mock()
        utils = types.ModuleType("frappe.utils")
        utils.now_datetime = lambda: "2026-11-15 19:00:00"
        document = types.ModuleType("frappe.model.document")
        document.Document = type("Document", (), {})
        self.modules = {"frappe": self.frappe, "frappe.utils": utils, "frappe.model.document": document}

    def load(self, path):
        spec = importlib.util.spec_from_file_location(path.stem + "_policy_test", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, self.modules):
            spec.loader.exec_module(module)
        return module

    def test_no_draft_or_stale_version_can_satisfy_registration_acceptance(self):
        api = self.load(ROOT / "api/policies.py")
        self.frappe.get_all.return_value = []
        with self.assertRaises(Invalid):
            api.require_acceptance("T", "P", "1", "1")
        self.frappe.get_all.side_effect = lambda doctype, **kwargs: [
            types.SimpleNamespace(name="T" if kwargs["filters"]["policy_type"] == "Terms and Conditions" else "P", version="1")
        ]
        for terms, privacy, accept, acknowledge in (
            ("OLD", "P", "1", "1"), ("T", "OLD", "1", "1"),
            ("T", "P", "0", "1"), ("T", "P", "1", "0"),
        ):
            with self.assertRaises(Invalid):
                api.require_acceptance(terms, privacy, accept, acknowledge)
        api.require_acceptance("T", "P", "1", "1")
        self.assertEqual(self.frappe.get_all.call_args.kwargs["filters"]["status"], "Published")

    def test_migration_adds_review_drafts_without_replacing_existing_versions(self):
        api = self.load(ROOT / "api/policies.py")
        existing = {("Terms and Conditions", "published-v1"), ("Privacy Policy", "review-draft")}
        created = []
        original = existing.copy()

        def insert(values):
            created.append(values)
            existing.add((values["policy_type"], values["version"]))

        self.frappe.db.exists.side_effect = lambda doctype, filters: any(
            kind == filters["policy_type"] and version == filters.get("version", version)
            for kind, version in existing
        )
        self.frappe.get_doc.side_effect = lambda values: types.SimpleNamespace(
            insert=lambda **kwargs: insert(values),
        )
        api.ensure_policy_drafts()
        api.ensure_policy_drafts()
        self.assertEqual(len(created), 4)
        self.assertEqual({doc["policy_type"] for doc in created}, set(api.POLICIES.values()))
        self.assertTrue(all(doc["status"] == "Draft" and not doc.get("published_at") for doc in created))
        self.assertTrue(original.issubset(existing))

    def test_policy_requires_review_before_publication(self):
        api = self.load(ROOT / "api/policies.py")
        folder = ROOT / "intelligent_ordering/doctype"
        cls = self.load(folder / "smarto_policy_version/smarto_policy_version.py").SmartOPolicyVersion
        policy = cls()
        policy.name = "terms"
        policy.policy_type = api.POLICIES["terms"]
        policy.version = api.POLICY_DRAFT_VERSION
        policy.status = "Published"
        policy.get_doc_before_save = lambda: types.SimpleNamespace(status="Draft")
        self.frappe.db.exists.return_value = False
        policy.content = api.REVIEW_INSTRUCTIONS + api.POLICY_CONTENT[policy.policy_type]
        with self.assertRaisesRegex(Invalid, "remove its review notice"):
            policy.validate()
        policy.content = api.POLICY_CONTENT[policy.policy_type]
        policy.validate()
        self.assertEqual(policy.published_at, "2026-11-15 19:00:00")

    def test_published_policies_and_acceptance_records_cannot_be_changed_or_deleted(self):
        folder = ROOT / "intelligent_ordering/doctype"
        policy_class = self.load(folder / "smarto_policy_version/smarto_policy_version.py").SmartOPolicyVersion
        policy = policy_class()
        policy.status = "Published"
        policy.get_doc_before_save = lambda: types.SimpleNamespace(status="Published")
        with self.assertRaises(Invalid):
            policy.validate()
        with self.assertRaises(Invalid):
            policy.on_trash()
        acceptance_class = self.load(folder / "smarto_policy_acceptance/smarto_policy_acceptance.py").SmartOPolicyAcceptance
        acceptance = acceptance_class()
        acceptance.is_new = lambda: False
        with self.assertRaises(Invalid):
            acceptance.validate()
        with self.assertRaises(Invalid):
            acceptance.on_trash()

    def test_acceptance_timestamp_is_server_assigned_and_versions_are_published(self):
        folder = ROOT / "intelligent_ordering/doctype"
        cls = self.load(folder / "smarto_policy_acceptance/smarto_policy_acceptance.py").SmartOPolicyAcceptance
        acceptance = cls()
        acceptance.is_new = lambda: True
        acceptance.user = "customer@example.test"
        acceptance.customer = "CUSTOMER-1"
        acceptance.accepted_at = "forged"
        acceptance.get = lambda field: {"terms_version": "T", "privacy_version": "P"}[field]
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.return_value = acceptance.user
        acceptance.validate()
        self.assertEqual(acceptance.accepted_at, "2026-11-15 19:00:00")
        self.frappe.db.get_value.return_value = "other@example.test"
        with self.assertRaises(Invalid):
            acceptance.validate()
