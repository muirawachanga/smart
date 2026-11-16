import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import check_password
from unittest.mock import patch

from intelligent_ordering.api import customers, policies
from intelligent_ordering.utils.authentication import login_destination
from intelligent_ordering.utils.staff_pages import require_staff_page


class TestAuthentication(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.email = f"auth-{frappe.generate_hash(length=12)}@example.test"
        self.password = f"SmartO-{frappe.generate_hash(length=32)}-9!"
        self.versions = {}
        for kind in ("Terms and Conditions", "Privacy Policy"):
            self.versions[kind] = frappe.get_doc({
                "doctype": "SmartO Policy Version", "policy_type": kind,
                "title": kind, "version": frappe.generate_hash(length=12),
                "status": "Published", "content": "Integration-test policy content.",
            }).insert()

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def register(self, **extra):
        frappe.set_user("Guest")
        values = {
            "email": self.email, "full_name": "Authentication Test Customer",
            "phone": "+254700000000", "password": self.password,
            "confirm_password": self.password,
            "terms_version": policies.current_policy("terms").name,
            "privacy_version": policies.current_policy("privacy").name,
            "accept_terms": 1, "acknowledge_privacy": 1,
        }
        values.update(extra)
        with patch("frappe.core.doctype.user.user.is_signup_disabled", return_value=False):
            return customers.register(**values)

    def test_registration_creates_real_password_backed_customer_and_auditable_consent(self):
        self.register()
        self.assertEqual(check_password(self.email, self.password), self.email)
        user = frappe.get_doc("User", self.email)
        self.assertEqual({row.role for row in user.roles}, {"Customer"})
        self.assertEqual(user.user_type, "Website User")
        self.assertTrue(frappe.db.exists("Customer Profile", {"user": self.email}))
        record = frappe.get_doc("SmartO Policy Acceptance", {"user": self.email})
        self.assertEqual(record.terms_version, policies.current_policy("terms").name)
        self.assertEqual(record.privacy_version, policies.current_policy("privacy").name)
        self.assertTrue(record.accepted_at)
        self.assertFalse(record.marketing_consent)
        frappe.set_user(self.email)
        self.assertEqual(login_destination("/checkout"), "/checkout")
        self.assertEqual(login_destination("/dashboard/admin"), "/")
        self.assertEqual(login_destination(), "/")
        self.assertEqual(login_destination("/account"), "/account")
        with self.assertRaises(frappe.PermissionError):
            require_staff_page(frappe._dict(), "admin")

    def test_missing_acceptance_and_duplicate_registration_do_not_create_extra_accounts(self):
        with self.assertRaises(frappe.ValidationError):
            self.register(accept_terms=0)
        self.assertFalse(frappe.db.exists("User", self.email))
        self.register()
        with self.assertRaises(frappe.ValidationError):
            self.register()
        self.assertEqual(frappe.db.count("SmartO Policy Acceptance", {"user": self.email}), 1)

    def test_new_policy_publication_preserves_old_acceptance_and_published_content(self):
        self.register()
        old = frappe.db.get_value("SmartO Policy Acceptance", {"user": self.email}, "terms_version")
        frappe.set_user("Administrator")
        policy = frappe.get_doc("SmartO Policy Version", old)
        policy.content = "Attempted rewrite"
        with self.assertRaises(frappe.ValidationError):
            policy.save()
        self.assertEqual(frappe.db.get_value("SmartO Policy Acceptance", {"user": self.email}, "terms_version"), old)
