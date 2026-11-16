from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.onboarding import readiness, save_business
from intelligent_ordering.utils.business import BUSINESS_FIELDS, get_business_profile


class TestBusinessOnboarding(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.original = get_business_profile()

    def tearDown(self):
        frappe.set_user("Administrator")
        settings = frappe.get_doc("Website Settings")
        for key, field in BUSINESS_FIELDS.items():
            settings.set(field, self.original[key])
        settings.save(ignore_permissions=True)
        super().tearDown()

    def test_public_identity_persists_and_is_audited(self):
        result = save_business(
            "Pilot Business", "support@example.test", "+254712345678", "Nairobi",
        )
        self.assertEqual(result["business"]["name"], "Pilot Business")
        self.assertEqual(get_business_profile()["email"], "support@example.test")
        self.assertTrue(frappe.db.exists("Admin Audit Log", {
            "event_type": "Business settings updated", "reference_doctype": "Website Settings",
            "reference_name": "Website Settings",
        }))
        with self.assertRaises(frappe.ValidationError):
            save_business("Pilot Business", "invalid-email")
        self.assertEqual(get_business_profile()["email"], "support@example.test")

    def test_desk_edits_share_validation(self):
        settings = frappe.get_doc("Website Settings")
        settings.smarto_business_name = "Pilot Business"
        settings.smarto_contact_email = "invalid-email"
        with self.assertRaises(frappe.ValidationError):
            settings.save(ignore_permissions=True)

    def test_business_admin_can_read_but_not_save(self):
        user = self._user("Business Admin")
        frappe.set_user(user)
        self.assertIn("checks", readiness())
        with self.assertRaises(frappe.PermissionError):
            save_business("Unauthorized", "support@example.test")

    def test_system_manager_can_save_without_general_website_manager_role(self):
        user = self._user("System Manager")
        frappe.set_user(user)
        self.assertNotIn("Website Manager", frappe.get_roles())
        self.assertEqual(save_business("Managed Store", phone="+254712345678")["business"]["name"],
                         "Managed Store")

    def test_customer_and_operational_staff_cannot_read_or_save(self):
        for role in ("Customer", "Order Manager", "Finance Manager", "Delivery Staff"):
            frappe.set_user("Administrator")
            user = self._user(role)
            frappe.set_user(user)
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                readiness()
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                save_business("Unauthorized", "support@example.test")

    def test_report_does_not_certify_production_or_return_secrets(self):
        with patch.dict(frappe.conf, {"gemini": {"enabled": True, "api_key": "do-not-return"}}):
            result = readiness()
        self.assertNotIn("do-not-return", repr(result))
        self.assertTrue(all(check["status"] == "not_verified" for check in result["manual_checks"]))

    def _user(self, role):
        email = f"onboarding-{frappe.generate_hash(length=10)}@example.test"
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": "Onboarding",
            "enabled": 1, "send_welcome_email": 0,
            "user_type": "Website User" if role == "Customer" else "System User",
            "roles": [{"role": role}],
        }).insert(ignore_permissions=True)
        return email
