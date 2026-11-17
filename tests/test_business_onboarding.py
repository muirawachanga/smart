import importlib.util
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from intelligent_ordering.utils.mpesa import DarajaClient


ROOT = Path(__file__).parents[1]


class OnboardingError(Exception):
    pass


def load_modules():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.session = types.SimpleNamespace(user="admin@example.test")
    frappe.get_roles = Mock(return_value=["System Manager"])
    frappe.PermissionError = frappe.ValidationError = OnboardingError
    frappe.throw = Mock(side_effect=lambda message, error: (_ for _ in ()).throw(error(message)))
    frappe.conf = {"developer_mode": 1}
    settings = {}
    frappe.get_cached_doc = Mock(return_value=settings)
    frappe.get_meta = Mock(return_value=types.SimpleNamespace(has_field=lambda field: True))
    audit = types.ModuleType("intelligent_ordering.utils.audit")
    audit.record_admin_event = Mock()
    policies = types.ModuleType("intelligent_ordering.api.policies")
    policies.POLICIES = {"terms": "Terms and Conditions", "privacy": "Privacy Policy",
                         "refund": "Refund Policy", "delivery": "Delivery Policy"}
    policies.current_policy = Mock(return_value=None)

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    with patch.dict(sys.modules, {"frappe": frappe, "intelligent_ordering.utils.audit": audit,
                                  "intelligent_ordering.api.policies": policies}):
        business = load("business_under_test", "intelligent_ordering/utils/business.py")
        with patch.dict(sys.modules, {"intelligent_ordering.utils.business": business}):
            onboarding = load("onboarding_under_test", "intelligent_ordering/api/onboarding.py")
    return onboarding, business, frappe, settings, policies, audit


class TestBusinessOnboarding(unittest.TestCase):
    def setUp(self):
        self.api, self.business, self.frappe, self.settings, self.policies, self.audit = load_modules()
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
            CREATE TABLE `tabProduct` (name TEXT, category TEXT, enabled INTEGER, currency TEXT);
            CREATE TABLE `tabProduct Category` (name TEXT, enabled INTEGER);
            CREATE TABLE `tabStock Warehouse` (name TEXT, status TEXT);
            CREATE TABLE `tabStock Balance` (product TEXT, warehouse TEXT, available_quantity REAL);
            CREATE TABLE `tabDelivery Area` (enabled INTEGER, currency TEXT);
            CREATE TABLE `tabUser` (name TEXT, enabled INTEGER, user_type TEXT);
            CREATE TABLE `tabHas Role` (parent TEXT, parenttype TEXT, role TEXT);
        """)
        self.frappe.db = types.SimpleNamespace(
            sql=lambda query: self.connection.execute(query).fetchall(),
            get_single_value=Mock(return_value=0),
        )

    def configure(self):
        self.settings.update({
            "smarto_business_name": "Test Shop", "smarto_contact_email": "help@example.test",
            "smarto_contact_phone": "", "smarto_business_address": "Nairobi",
        })
        self.frappe.conf = {
            "host_name": "https://shop.example.test", "developer_mode": 0,
            "mpesa": {"environment": "Production", "consumer_key": "private-key",
                      "consumer_secret": "private-secret", "shortcode": "123456", "passkey": "private-passkey",
                      "callback_url": "https://shop.example.test/api/method/intelligent_ordering.api.payments.callback"},
        }
        self.frappe.db.get_single_value.return_value = 1
        self.policies.current_policy.return_value = {"name": "approved-policy"}
        self.connection.executescript("""
            INSERT INTO `tabProduct Category` VALUES ('Food', 1);
            INSERT INTO `tabProduct` VALUES ('Milk', 'Food', 1, 'KES');
            INSERT INTO `tabStock Warehouse` VALUES ('Main', 'Active');
            INSERT INTO `tabStock Balance` VALUES ('Milk', 'Main', 5);
            INSERT INTO `tabDelivery Area` VALUES (1, 'KES');
            INSERT INTO `tabUser` VALUES ('staff@example.test', 1, 'System User');
            INSERT INTO `tabHas Role` VALUES ('staff@example.test', 'User', 'Order Manager');
        """)

    def checks(self):
        return {item["key"]: item["status"] for item in self.api.readiness()["checks"]}

    def test_scoped_permissions_prevent_reads_and_writes_for_other_roles(self):
        for role in ("Customer", "Store Manager", "Finance Manager", "Delivery Staff"):
            self.frappe.get_roles.return_value = [role]
            with self.subTest(role=role), self.assertRaises(OnboardingError):
                self.api.readiness()
            with self.subTest(role=role), self.assertRaises(OnboardingError):
                self.api.save_business("Shop", "help@example.test")
        self.frappe.get_roles.return_value = ["System Manager"]
        self.frappe.session.user = "Guest"
        with self.assertRaises(OnboardingError):
            self.api.readiness()
        self.frappe.session.user = "admin@example.test"
        self.frappe.get_roles.return_value = ["Business Admin"]
        self.api.readiness()
        with self.assertRaises(OnboardingError):
            self.api.save_business("Shop", "help@example.test")

    def test_configuration_never_certifies_manual_work_or_exposes_secrets(self):
        self.configure()
        with patch.object(DarajaClient, "_json", side_effect=AssertionError("No provider calls")):
            result = self.api.readiness()
        self.assertEqual(result["blocking_count"], 0)
        self.assertTrue(all(item["status"] == "not_verified" for item in result["manual_checks"]))
        self.assertIn("never certifies", result["notice"])
        self.assertNotIn("private-secret", repr(result))
        self.assertNotIn("private-key", repr(result))
        self.assertNotIn("private-passkey", repr(result))

    def test_catalog_stock_area_and_staff_checks_use_actual_records(self):
        self.configure()
        self.connection.execute("UPDATE `tabStock Warehouse` SET status = 'Inactive'")
        self.connection.execute("UPDATE `tabDelivery Area` SET currency = 'USD'")
        self.connection.execute("UPDATE `tabUser` SET enabled = 0")
        checks = self.checks()
        self.assertEqual(checks["stock"], "blocked")
        self.assertEqual(checks["areas"], "blocked")
        self.assertEqual(checks["staff"], "blocked")
        self.connection.execute("UPDATE `tabProduct Category` SET enabled = 0")
        self.assertEqual(self.checks()["catalog"], "blocked")

    def test_website_staff_count_as_named_staff_without_customer_role_confusion(self):
        self.configure()
        self.connection.execute("UPDATE `tabUser` SET user_type = 'Website User'")
        self.assertEqual(self.checks()["staff"], "configured")
        self.connection.execute("UPDATE `tabHas Role` SET role = 'Customer'")
        self.assertEqual(self.checks()["staff"], "blocked")

    def test_cross_site_callbacks_sandbox_and_paused_scheduler_are_blocked(self):
        self.configure()
        self.frappe.conf["mpesa"]["callback_url"] = (
            "https://other.example.test/api/method/intelligent_ordering.api.payments.callback")
        self.assertEqual(self.checks()["payments"], "blocked")
        self.frappe.conf["mpesa"]["environment"] = "Sandbox"
        self.frappe.conf["pause_scheduler"] = 1
        checks = self.checks()
        self.assertEqual(checks["payments"], "blocked")
        self.assertEqual(checks["scheduler"], "blocked")
        self.frappe.conf["host_name"] = "https://["
        self.assertEqual(self.checks()["https"], "blocked")

    def test_save_uses_existing_settings_and_only_public_fields(self):
        doc = Mock()
        self.frappe.get_doc = Mock(return_value=doc)
        self.api.save_business("  Test Shop ", "help@example.test", "", "Nairobi")
        self.frappe.get_doc.assert_called_once_with("Website Settings")
        doc.set.assert_any_call("smarto_business_name", "Test Shop")
        self.assertEqual(doc.set.call_count, 4)
        doc.save.assert_called_once_with(ignore_permissions=True)
        self.frappe.get_meta.return_value.has_field = lambda field: False
        with self.assertRaisesRegex(OnboardingError, "migration"):
            self.api.save_business("Shop", "help@example.test")
        self.assertEqual(doc.save.call_count, 1)

    def test_profile_validation_and_desk_updates_share_validation_and_audit(self):
        for changes in ({"name": ""}, {"email": "", "phone": ""}, {"email": "not-an-email"},
                        {"phone": "javascript:alert(1)"}, {"address": "x" * 501}, {"name": []}):
            values = {"name": "Shop", "email": "help@example.test", "phone": "", "address": ""}
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.business.validate_profile(values)
        self.configure()
        doc = Mock(name="settings")
        doc.name = "Website Settings"
        doc.get.side_effect = self.settings.get
        doc.get_doc_before_save.return_value = {}
        self.business.validate_business_settings(doc)
        self.business.audit_business_settings(doc)
        event = self.audit.record_admin_event.call_args.args
        self.assertIn("smarto_business_name", event[-1])
        self.assertNotIn("help@example.test", repr(event))
        context = {}
        self.business.update_website_context(context)
        self.assertEqual(context["smarto_business"]["name"], "Test Shop")
        self.assertEqual(set(context["smarto_business"]), {"name", "email", "phone", "address"})


if __name__ == "__main__":
    unittest.main()
