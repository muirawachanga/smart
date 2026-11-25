import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class TestStaffMFA(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.session = types.SimpleNamespace(user="Administrator")
        self.frappe.local = types.SimpleNamespace(site="pilot.example.test")
        self.frappe.get_roles = Mock(return_value=[])
        self.frappe.ValidationError = self.frappe.PermissionError = ValueError
        self.frappe.throw = Mock(side_effect=lambda message, error: (_ for _ in ()).throw(error(message)))
        self.frappe.db = Mock()
        self.frappe.db.exists.return_value = True
        self.frappe.get_all = Mock(return_value=[])
        self.settings = types.SimpleNamespace(
            enable_two_factor_auth=0, two_factor_method="", otp_issuer_name="",
            bypass_2fa_for_retricted_ip_users=0,
        )
        self.roles = {}

        def save_settings(**kwargs):
            self.roles.setdefault("All", types.SimpleNamespace(two_factor_auth=0, save=Mock()))
            self.roles["All"].two_factor_auth = 1

        self.settings.save = Mock(side_effect=save_settings)

        def get_doc(doctype, name=None):
            if doctype == "System Settings":
                return self.settings
            return self.roles.setdefault(name, types.SimpleNamespace(two_factor_auth=0, save=Mock()))

        self.frappe.get_doc = Mock(side_effect=get_doc)
        audit = types.ModuleType("intelligent_ordering.utils.audit")
        audit.record_admin_event = Mock()
        self.audit = audit.record_admin_event
        path = Path(__file__).parents[1] / "intelligent_ordering/utils/staff_mfa.py"
        spec = importlib.util.spec_from_file_location("staff_mfa_under_test", path)
        self.mfa = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": self.frappe, audit.__name__: audit}):
            spec.loader.exec_module(self.mfa)

    def test_preview_does_not_change_settings_or_roles(self):
        result = self.mfa.configure(["Finance Manager"])
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["roles"], ["Finance Manager"])
        self.settings.save.assert_not_called()
        self.frappe.db.savepoint.assert_not_called()

    def test_activation_requires_site_confirmation_and_verified_email(self):
        for kwargs in ({}, {"confirmation": "wrong", "email_verified": True},
                       {"confirmation": "pilot.example.test"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.mfa.configure(["Finance Manager"], activate=True, **kwargs)
        self.settings.save.assert_not_called()

    def test_activation_undoes_frappe_all_role_default_and_adds_only_pilot(self):
        result = self.mfa.configure(
            ["Finance Manager"], activate=True, confirmation="pilot.example.test", email_verified=True,
        )
        self.assertEqual(result["status"], "activated")
        self.assertEqual(self.settings.two_factor_method, "OTP App")
        self.assertEqual(self.roles["All"].two_factor_auth, 0)
        self.assertEqual(self.roles["Finance Manager"].two_factor_auth, 1)
        self.assertNotIn("Customer", self.roles)
        self.audit.assert_called_once()

    def test_invalid_roles_and_non_admin_are_rejected(self):
        for roles in ([], "Finance Manager", ["Customer"], ["All"], [{}]):
            with self.subTest(roles=roles), self.assertRaises(ValueError):
                self.mfa.configure(roles)
        self.frappe.session.user = "staff@example.test"
        with self.assertRaises(ValueError):
            self.mfa.configure(["Finance Manager"])
        self.settings.save.assert_not_called()

    def test_existing_broader_policy_is_not_silently_disabled(self):
        self.settings.enable_two_factor_auth = 1
        self.settings.two_factor_method = "OTP App"
        self.frappe.get_all.return_value = ["All"]
        with self.assertRaises(ValueError):
            self.mfa.configure(["Finance Manager"])
        self.settings.save.assert_not_called()

    def test_later_stages_keep_existing_staff_roles(self):
        self.settings.enable_two_factor_auth = 1
        self.settings.two_factor_method = "OTP App"
        self.frappe.get_all.return_value = ["Finance Manager"]
        self.assertEqual(self.mfa.configure(["Order Manager"])["roles"],
                         ["Finance Manager", "Order Manager"])

    def test_existing_sms_bypass_or_customer_policy_requires_manual_review(self):
        self.settings.enable_two_factor_auth = 1
        for method, bypass, roles in (
            ("SMS", 0, ["Finance Manager"]),
            ("OTP App", 1, ["Finance Manager"]),
            ("OTP App", 0, ["Customer"]),
        ):
            self.settings.two_factor_method = method
            self.settings.bypass_2fa_for_retricted_ip_users = bypass
            self.frappe.get_all.return_value = roles
            with self.subTest(method=method, bypass=bypass, roles=roles), self.assertRaises(ValueError):
                self.mfa.configure(["Order Manager"])
        self.settings.save.assert_not_called()

    def test_failed_activation_rolls_back_and_propagates_error(self):
        self.audit.side_effect = RuntimeError("audit failed")
        with self.assertRaisesRegex(RuntimeError, "audit failed"):
            self.mfa.configure(
                ["Finance Manager"], activate=True, confirmation="pilot.example.test", email_verified=True,
            )
        self.frappe.db.rollback.assert_called_once_with(save_point="smarto_staff_mfa")
