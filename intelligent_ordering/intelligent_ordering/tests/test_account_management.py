from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.accounts import create_account, list_accounts, update_access


class TestAccountManagement(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def create(self, role):
        email = f"accounts-{frappe.generate_hash(length=10)}@example.test"
        with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user") as invite:
            result = create_account(email, "Managed Person", "+254712345678", role)
            invite.assert_called_once()
        return frappe.get_doc("User", result["name"])

    def test_customer_profile_created_without_false_consent(self):
        user = self.create("Customer")
        self.assertEqual(user.user_type, "Website User")
        self.assertEqual({row.role for row in user.roles}, {"Customer"})
        self.assertTrue(frappe.db.exists("Customer Profile", {"user": user.name}))
        self.assertFalse(frappe.db.exists("SmartO Policy Acceptance", {"user": user.name}))
        self.assertTrue(frappe.db.exists("Admin Audit Log", {
            "event_type": "Account invitation requested", "reference_name": user.name,
        }))

    def test_operational_role_update_and_disable_preserve_native_user_lifecycle(self):
        user = self.create("Inventory Manager")
        self.assertEqual(user.user_type, "System User")
        with patch("frappe.sessions.clear_sessions") as clear:
            update_access(user.name, "Order Manager", 0, str(user.modified))
            clear.assert_called_with(user=user.name, force=True)
        user.reload()
        self.assertEqual({row.role for row in user.roles}, {"Order Manager"})
        self.assertEqual(user.enabled, 0)
        self.assertFalse(frappe.db.exists("Customer Profile", {"user": user.name}))

    def test_business_admin_cannot_create_accounts_or_assign_roles(self):
        user = self.create("Business Admin")
        frappe.set_user(user.name)
        with self.assertRaises(frappe.PermissionError):
            list_accounts()
        with self.assertRaises(frappe.PermissionError):
            create_account("denied@example.test", "Denied", "+254712345678", "Order Manager")
