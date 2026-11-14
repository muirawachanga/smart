import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


class AccessError(Exception):
    pass


def load_accounts():
    frappe = types.ModuleType("frappe")
    frappe.local = types.SimpleNamespace(site="smarto.local")
    frappe.conf = {"developer_mode": 1}
    frappe.session = types.SimpleNamespace(user="Administrator")
    frappe.ValidationError = frappe.PermissionError = AccessError
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(AccessError(message)))
    frappe.db = Mock()
    frappe.db.exists.side_effect = lambda doctype, name: doctype == "Role"
    frappe.get_roles = Mock(return_value=["System Manager"])
    frappe.get_doc = Mock()
    frappe.set_user = Mock(side_effect=lambda user: setattr(frappe.session, "user", user))
    path = Path(__file__).parents[1] / "intelligent_ordering/utils/development_accounts.py"
    spec = importlib.util.spec_from_file_location("development_accounts_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe}):
        spec.loader.exec_module(module)
    return module, frappe


class TestDevelopmentAccounts(unittest.TestCase):
    def setUp(self):
        self.accounts, self.frappe = load_accounts()

    def test_requires_development_local_site_and_admin_before_password_prompt(self):
        for conf, user, roles in (
            ({}, "Administrator", ["System Manager"]),
            ({"developer_mode": 1, "host_name": "https://example.com"}, "Administrator", ["System Manager"]),
            ({"developer_mode": 1}, "inventory.test@smarto.local", ["Inventory Manager"]),
        ):
            with self.subTest(conf=conf, user=user):
                self.frappe.conf = conf
                self.frappe.session.user = user
                self.frappe.get_roles.return_value = roles
                with patch("builtins.input") as prompt, self.assertRaises(AccessError):
                    self.accounts.provision()
                prompt.assert_not_called()
                self.frappe.get_doc.assert_not_called()

    def test_creates_eight_real_users_with_exact_roles_and_no_password_in_results(self):
        with patch("builtins.input", return_value="LOCAL-ONLY smarto.local"), patch.object(
            self.accounts.getpass, "getpass", return_value="temporary-test-secret"
        ):
            result = self.accounts.provision()
        docs = [call.args[0] for call in self.frappe.get_doc.call_args_list]
        self.assertEqual(len(docs), 8)
        self.assertTrue(all(doc["doctype"] == "User" and doc["user_type"] == "System User" for doc in docs))
        self.assertEqual(sum(any(row["role"] == "System Manager" for row in doc["roles"]) for doc in docs), 1)
        self.assertNotIn("Administrator", {doc["email"] for doc in docs})
        for email, _, role in self.accounts.TEST_ACCOUNTS:
            doc = next(doc for doc in docs if doc["email"] == email)
            self.assertEqual(doc["roles"], [{"role": value} for value in self.accounts._account_roles(role)])
            self.assertEqual(doc["send_welcome_email"], 0)
        self.assertNotIn("temporary-test-secret", repr(result))

    def test_existing_matching_accounts_are_not_modified_or_password_reset(self):
        role_by_email = {email: role for email, _, role in self.accounts.TEST_ACCOUNTS}
        self.frappe.db.exists.return_value = True
        self.frappe.db.exists.side_effect = None
        self.frappe.get_doc.side_effect = lambda doctype, email: types.SimpleNamespace(
            enabled=1, user_type="System User", role_profile_name="",
            roles=[types.SimpleNamespace(role=role) for role in
                   self.accounts._account_roles(role_by_email[email])],
        )
        with patch("builtins.input", return_value="LOCAL-ONLY smarto.local"), patch.object(
            self.accounts.getpass, "getpass"
        ) as password:
            result = self.accounts.provision()
        password.assert_not_called()
        self.assertTrue(all(row["status"] == "existing; password unchanged" for row in result))
        self.frappe.db.savepoint.assert_not_called()

    def test_conflicting_existing_roles_abort_without_mutations(self):
        self.frappe.db.exists.side_effect = None
        self.frappe.db.exists.return_value = True
        self.frappe.get_doc.return_value = types.SimpleNamespace(
            enabled=1, user_type="System User", role_profile_name="",
            roles=[types.SimpleNamespace(role="System Manager"), types.SimpleNamespace(role="Store Manager")],
        )
        with patch("builtins.input", return_value="LOCAL-ONLY smarto.local"), self.assertRaises(AccessError):
            self.accounts.provision()
        self.frappe.db.savepoint.assert_not_called()

    def test_failed_user_creation_rolls_back_and_propagates_failure(self):
        self.frappe.get_doc.return_value.insert.side_effect = RuntimeError("Insert failed")
        with patch("builtins.input", return_value="LOCAL-ONLY smarto.local"), patch.object(
            self.accounts.getpass, "getpass", return_value="temporary-test-secret"
        ), self.assertRaisesRegex(RuntimeError, "Insert failed"):
            self.accounts.provision()
        self.frappe.db.rollback.assert_called_once_with(save_point="smarto_development_accounts")

    def test_unconfirmed_public_exposure_is_rejected(self):
        with patch("builtins.input", return_value="no"), self.assertRaises(AccessError):
            self.accounts.provision()
        self.frappe.get_doc.assert_not_called()

    def test_verification_rejects_public_target_before_requesting_credentials(self):
        with patch("builtins.input", side_effect=["LOCAL-ONLY smarto.local", "https://example.com"]), patch.object(
            self.accounts.getpass, "getpass"
        ) as password, self.assertRaises(AccessError):
            self.accounts.verify()
        password.assert_not_called()

    def test_wrong_http_identity_fails_every_account_without_leaking_passwords(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value.status_code = 200
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"message": {"user": "wrong@example.test"}}
        api = types.ModuleType("intelligent_ordering.api")
        api.orders = Mock()
        api.payments = Mock()
        pages = types.ModuleType("intelligent_ordering.utils.staff_pages")
        pages.PAGE_ROLES = {}
        pages.require_staff_page = Mock()
        with patch("builtins.input", side_effect=["LOCAL-ONLY smarto.local", "http://localhost:8000"]), patch.object(
            self.accounts.getpass, "getpass", return_value="test-only-password"
        ), patch("requests.Session", return_value=session), patch.dict(sys.modules, {
            "intelligent_ordering.api": api,
            "intelligent_ordering.utils.staff_pages": pages,
        }):
            result = self.accounts.verify()
        self.assertFalse(result["all_passed"])
        self.assertEqual(len(result["checks"]), 8)
        self.assertTrue(all(row["status"] == "FAIL" for row in result["checks"]))
        self.assertNotIn("test-only-password", repr(result))
        self.assertEqual(self.frappe.session.user, "Administrator")

    def test_verified_support_checks_server_denials_and_restores_admin(self):
        email = "support.test@smarto.local"
        api = types.ModuleType("intelligent_ordering.api")
        api.orders = Mock()
        api.payments = Mock()
        api.orders.update_order_status.side_effect = AccessError("Denied")
        api.payments.reconcile_payment.side_effect = AccessError("Denied")
        pages = types.ModuleType("intelligent_ordering.utils.staff_pages")
        pages.PAGE_ROLES = {"support": {"Customer Support"}, "admin": {"System Manager"}}
        pages.require_staff_page = Mock(side_effect=AccessError("Denied"))
        self.frappe._dict = dict
        self.frappe.has_permission = Mock(side_effect=lambda doctype, permission:
                                         permission == "read" and doctype != "Payment Transaction")
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value.status_code = 200

        def get(url, **kwargs):
            if url.endswith("current_user"):
                return Mock(status_code=200, json=lambda: {"message": {
                    "user": email, "roles": ["Customer Support", "All", "Desk User"],
                }})
            return Mock(status_code=200 if url.endswith(("/support", "orders.list_orders")) else 403)

        session.get.side_effect = get
        with patch("builtins.input", side_effect=["LOCAL-ONLY smarto.local", "http://localhost:8000"]), patch.object(
            self.accounts.getpass, "getpass", return_value="test-only-password"
        ), patch.object(self.accounts, "TEST_ACCOUNTS", [(email, "Support", "Customer Support")]), patch(
            "requests.Session", return_value=session
        ), patch.dict(sys.modules, {
            "intelligent_ordering.api": api,
            "intelligent_ordering.utils.staff_pages": pages,
        }):
            result = self.accounts.verify()
        self.assertTrue(result["all_passed"])
        api.orders.update_order_status.assert_called_once()
        api.payments.reconcile_payment.assert_called_once()
        self.assertEqual(self.frappe.session.user, "Administrator")
