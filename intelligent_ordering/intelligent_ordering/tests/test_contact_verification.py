from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api import contact_verification, customers
from intelligent_ordering.utils import contact_verification as verification


class TestContactVerification(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.user = f"contacts-{frappe.generate_hash(length=12)}@example.test"
        frappe.get_doc({
            "doctype": "User", "email": self.user, "first_name": "Contact Verification",
            "enabled": 1, "user_type": "Website User", "send_welcome_email": 0,
            "roles": [{"role": "Customer"}],
        }).insert(ignore_permissions=True)
        self.profile = frappe.get_doc({
            "doctype": "Customer Profile", "user": self.user,
            "full_name": "Contact Verification", "phone": "+254712345678",
        }).insert(ignore_permissions=True)
        frappe.db.set_value("Customer Profile", self.profile.name, "contact_verification_required", 1)
        frappe.set_user(self.user)

    def tearDown(self):
        frappe.set_user("Administrator")
        for channel in ("email", "phone"):
            frappe.cache.delete_value(verification._key(self.user, channel))
        super().tearDown()

    def test_real_profile_proof_changes_and_checkout_requirement(self):
        with (
            patch.object(verification, "_configuration", return_value={"environment": "sandbox"}),
            patch.object(verification, "_submit", return_value=("Submitted", "test-id", "")),
            patch.object(verification.secrets, "randbelow", return_value=12345),
            patch.object(verification.secrets, "token_urlsafe", return_value="email-token"),
            patch("frappe.sendmail"),
        ):
            contact_verification.request("phone")
            contact_verification.request("email")
        with self.assertRaises(frappe.ValidationError):
            verification.require_verified_contacts(self.user, self.profile.phone)
        contact_verification.confirm("phone", "012345")
        contact_verification.confirm("email", "email-token")
        proof = customers.get_profile()["verification"]
        self.assertTrue(proof["email_verified"])
        self.assertTrue(proof["phone_verified"])
        verification.require_verified_contacts(self.user, self.profile.phone)
        with self.assertRaises(frappe.ValidationError):
            contact_verification.confirm("phone", "012345")
        customers.save_profile("Contact Verification", "+254700000000")
        self.assertFalse(customers.get_profile()["verification"]["phone_verified"])
        with self.assertRaises(frappe.ValidationError):
            verification.require_verified_contacts(self.user, "+254700000000")

    def test_native_profile_save_cannot_fabricate_proof_or_remove_requirement(self):
        frappe.set_user("Administrator")
        profile = frappe.get_doc("Customer Profile", self.profile.name)
        profile.verified_email = self.user
        profile.email_verified_at = frappe.utils.now_datetime()
        profile.verified_phone = profile.phone
        profile.phone_verified_at = frappe.utils.now_datetime()
        profile.contact_verification_required = 0
        profile.save(ignore_permissions=True)
        profile.reload()
        self.assertFalse(profile.verified_email)
        self.assertFalse(profile.verified_phone)
        self.assertEqual(profile.contact_verification_required, 1)

    def test_guest_and_staff_without_customer_role_cannot_issue_or_confirm(self):
        frappe.set_user("Administrator")
        staff = f"contacts-staff-{frappe.generate_hash(length=12)}@example.test"
        frappe.get_doc({
            "doctype": "User", "email": staff, "first_name": "Staff",
            "enabled": 1, "user_type": "System User", "send_welcome_email": 0,
            "roles": [{"role": "System Manager"}],
        }).insert(ignore_permissions=True)
        for user in ("Guest", staff):
            frappe.set_user(user)
            for operation in (lambda: contact_verification.request("email"),
                              lambda: contact_verification.confirm("phone", "012345")):
                with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
                    operation()
