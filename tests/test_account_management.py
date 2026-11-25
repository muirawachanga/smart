import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class AccountError(Exception):
    pass


class OutgoingEmailError(Exception):
    pass


def load_api():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.session = types.SimpleNamespace(user="admin@example.test")
    frappe.get_roles = Mock(return_value=["System Manager"])
    frappe.PermissionError = frappe.ValidationError = AccountError
    frappe.OutgoingEmailError = OutgoingEmailError
    frappe.throw = Mock(side_effect=lambda message, error: (_ for _ in ()).throw(error(message)))
    frappe.clear_messages = Mock()
    frappe.get_doc = Mock()
    frappe.get_list = Mock(return_value=[])
    frappe.get_all = Mock(return_value=[])
    frappe.db = Mock()
    frappe.db.exists.side_effect = lambda doctype, *args: doctype == "Role"
    checkout = types.ModuleType("intelligent_ordering.api.checkout")
    checkout._save_customer_profile = Mock()
    audit = types.ModuleType("intelligent_ordering.utils.audit")
    audit.record_admin_event = Mock()
    utils = types.ModuleType("frappe.utils")
    utils.escape_html = lambda value: value
    utils.validate_email_address = lambda value, throw: value
    sessions = types.ModuleType("frappe.sessions")
    sessions.clear_sessions = Mock()
    modules = {
        "frappe": frappe, "frappe.utils": utils, "frappe.sessions": sessions,
        "intelligent_ordering.api.checkout": checkout, "intelligent_ordering.utils.audit": audit,
    }
    spec = importlib.util.spec_from_file_location(
        "accounts_under_test", Path(__file__).parents[1] / "intelligent_ordering/api/accounts.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, frappe, modules


class TestAccountManagement(unittest.TestCase):
    def setUp(self):
        self.api, self.frappe, self.modules = load_api()
        self.user = Mock()
        self.user.name = "person@example.test"
        self.user.enabled = 1
        self.user.modified = "2026-11-17 11:00:00"
        self.role = "Inventory Manager"
        self.user.get.side_effect = lambda field, default=None: (
            [types.SimpleNamespace(role=self.role)] if field == "roles" else None
        )
        self.frappe.get_doc.return_value = self.user

    def test_only_system_manager_can_read_create_update_or_invite(self):
        for role in ("Business Admin", "Store Manager", "Inventory Manager", "Customer", "Delivery Staff"):
            self.frappe.get_roles.return_value = [role]
            for operation in (
                self.api.list_accounts,
                lambda: self.api.create_account("test@example.test", "Test", "+254712345678", "Customer"),
                lambda: self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified),
                lambda: self.api.send_invitation(self.user.name),
            ):
                with self.subTest(role=role), self.assertRaises(AccountError):
                    operation()
        self.frappe.session.user = "Guest"
        self.frappe.get_roles.return_value = ["System Manager"]
        with self.assertRaises(AccountError):
            self.api.list_accounts()
        self.frappe.get_doc.assert_not_called()
        self.frappe.get_list.assert_not_called()

    def test_customer_creation_reuses_profile_and_does_not_record_fabricated_consent(self):
        self.role = "Customer"
        with patch.dict(sys.modules, self.modules):
            result = self.api.create_account("Customer@Example.test", "Customer Name", "+254712345678", "Customer")
        doc = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(doc["roles"], [{"role": "Customer"}])
        self.assertEqual(doc["user_type"], "Website User")
        self.assertEqual(doc["email"], "customer@example.test")
        self.assertNotIn("new_password", doc)
        self.assertNotIn("password", result)
        self.user.insert.assert_called_once_with()
        self.user.send_welcome_mail_to_user.assert_called_once_with()
        self.modules["intelligent_ordering.api.checkout"]._save_customer_profile.assert_called_once()
        self.frappe.db.set_value.assert_called_once_with(
            "Customer Profile", self.modules["intelligent_ordering.api.checkout"]._save_customer_profile.return_value.name,
            "contact_verification_required", 1,
        )
        self.assertEqual(self.frappe.get_doc.call_count, 1)

    def test_staff_creation_has_only_requested_role_and_no_customer_profile(self):
        self.api.create_account("staff@example.test", "Staff Name", "+254712345678", "Inventory Manager")
        doc = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(doc["roles"], [{"role": "Inventory Manager"}])
        self.assertEqual(doc["user_type"], "Website User")
        self.modules["intelligent_ordering.api.checkout"]._save_customer_profile.assert_not_called()

    def test_finance_and_business_admin_creation_retain_desk_user_type(self):
        for role in ("Finance Manager", "Business Admin"):
            self.role = role
            self.api.create_account("staff@example.test", "Staff Name", "+254712345678", role)
            self.assertEqual(self.frappe.get_doc.call_args.args[0]["user_type"], "System User")

    def test_cannot_grant_privileged_or_unknown_roles(self):
        for role in ("System Manager", "Administrator", "Website Manager", "unknown"):
            with self.subTest(role=role), self.assertRaises(AccountError):
                self.api.create_account("staff@example.test", "Staff", "+254712345678", role)
        self.frappe.get_doc.assert_not_called()

    def test_outgoing_mail_failure_is_not_reported_as_success(self):
        self.user.send_welcome_mail_to_user.side_effect = OutgoingEmailError("private SMTP details")
        for operation in (
            lambda: self.api.create_account("staff@example.test", "Staff", "+254712345678", "Inventory Manager"),
            lambda: self.api.send_invitation(self.user.name),
        ):
            with self.subTest(operation=operation), self.assertRaises(AccountError) as raised:
                operation()
            self.assertIn("default outgoing Email Account", str(raised.exception))
            self.assertNotIn("private SMTP details", str(raised.exception))
        self.assertEqual(self.frappe.clear_messages.call_count, 2)
        self.modules["intelligent_ordering.utils.audit"].record_admin_event.assert_not_called()

    def test_unexpected_mail_errors_are_not_suppressed(self):
        self.user.send_welcome_mail_to_user.side_effect = RuntimeError("Unexpected error")
        with self.assertRaisesRegex(RuntimeError, "Unexpected error"):
            self.api.send_invitation(self.user.name)

    def test_native_permission_failures_are_not_bypassed(self):
        self.user.insert.side_effect = AccountError("No create permission")
        with self.assertRaisesRegex(AccountError, "No create permission"):
            self.api.create_account("staff@example.test", "Staff", "+254712345678", "Inventory Manager")
        self.user.send_welcome_mail_to_user.assert_not_called()
        self.user.check_permission.side_effect = AccountError("No write permission")
        with self.assertRaisesRegex(AccountError, "No write permission"):
            self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified)
        self.user.save.assert_not_called()

    def test_unexpected_defaults_and_disabled_roles_cannot_grant_access(self):
        self.user.get.side_effect = lambda field, default=None: (
            [types.SimpleNamespace(role=value) for value in ("Inventory Manager", "System Manager")]
            if field == "roles" else None
        )
        with self.assertRaisesRegex(AccountError, "defaults"):
            self.api.create_account("staff@example.test", "Staff", "+254712345678", "Inventory Manager")
        self.user.send_welcome_mail_to_user.assert_not_called()
        with self.assertRaisesRegex(AccountError, "protected"):
            self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified)
        self.frappe.db.exists.return_value = False
        self.frappe.db.exists.side_effect = None
        with self.assertRaisesRegex(AccountError, "disabled"):
            self.api.create_account("staff@example.test", "Staff", "+254712345678", "Inventory Manager")

    def test_update_uses_native_write_checks_and_revokes_sessions(self):
        with patch.dict(sys.modules, self.modules):
            self.api.update_access(self.user.name, "Order Manager", "1", self.user.modified)
        self.user.check_permission.assert_called_once_with("write")
        self.user.set.assert_called_once_with("roles", [{"role": "Order Manager"}])
        self.user.save.assert_called_once_with()
        self.modules["frappe.sessions"].clear_sessions.assert_called_once_with(user=self.user.name, force=True)

    def test_stale_self_custom_and_customer_conversion_changes_are_rejected(self):
        with self.assertRaisesRegex(AccountError, "changed"):
            self.api.update_access(self.user.name, "Order Manager", 1, "old")
        self.role = "Customer"
        with self.assertRaisesRegex(AccountError, "separate"):
            self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified)
        self.role = "System Manager"
        with self.assertRaisesRegex(AccountError, "protected"):
            self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified)
        self.role = "Order Manager"
        self.user.name = self.frappe.session.user
        with self.assertRaisesRegex(AccountError, "protected"):
            self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified)
        self.user.save.assert_not_called()

    def test_active_rider_cannot_be_disabled_or_lose_their_role(self):
        self.role = "Delivery Staff"
        self.frappe.db.exists.side_effect = lambda doctype, *args: doctype in {"Role", "Delivery"}
        with self.assertRaisesRegex(AccountError, "assignments"):
            self.api.update_access(self.user.name, "Delivery Staff", "0", self.user.modified)
        with self.assertRaisesRegex(AccountError, "assignments"):
            self.api.update_access(self.user.name, "Order Manager", 1, self.user.modified)
        self.user.save.assert_not_called()

    def test_resend_never_returns_password_setup_link_and_disabled_accounts_are_denied(self):
        self.user.send_welcome_mail_to_user.return_value = "https://example.test/update-password?key=private"
        result = self.api.send_invitation(self.user.name)
        self.assertNotIn("private", repr(result))
        self.assertIn("queued", result["message"])
        self.user.enabled = 0
        with self.assertRaises(AccountError):
            self.api.send_invitation(self.user.name)


if __name__ == "__main__":
    unittest.main()
