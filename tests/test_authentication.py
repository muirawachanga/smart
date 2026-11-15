import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "intelligent_ordering"


class Denied(Exception):
    pass


class Redirect(Exception):
    pass


def load(path, modules):
    spec = importlib.util.spec_from_file_location(path.stem + "_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class TestAuthentication(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.session = types.SimpleNamespace(user="customer@example.test")
        self.frappe.get_roles = Mock(return_value=["Customer"])
        self.frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(Denied(message)))
        self.frappe.PermissionError = self.frappe.ValidationError = self.frappe.AuthenticationError = Denied
        self.frappe.DoesNotExistError = Denied
        self.frappe.Redirect = Redirect
        self.frappe.request = types.SimpleNamespace(path="/account")
        self.frappe.local = types.SimpleNamespace(
            flags=types.SimpleNamespace(), response={}, login_manager=Mock(),
        )
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.clear_messages = Mock()
        self.modules = {"frappe": self.frappe}
        staff = load(ROOT / "utils/staff_pages.py", self.modules)
        self.modules["intelligent_ordering.utils.staff_pages"] = staff
        self.auth = load(ROOT / "utils/authentication.py", self.modules)
        strength = types.ModuleType("frappe.utils.password_strength")
        strength.test_password_strength = Mock(return_value={"score": 4})
        self.modules["frappe.utils.password_strength"] = strength

    def test_server_selects_each_role_workspace_and_rejects_guest(self):
        for role, destination in (
            ("System Manager", "/dashboard/admin"), ("Business Admin", "/dashboard/admin"),
            ("Store Manager", "/dashboard/owner"), ("Finance Manager", "/dashboard/sales"),
            ("Order Manager", "/dashboard/orders"), ("Inventory Manager", "/dashboard/inventory"),
            ("Delivery Manager", "/dashboard/delivery"), ("Delivery Staff", "/dashboard/delivery"),
            ("Customer Support", "/dashboard/support"), ("Customer", "/account"),
        ):
            self.frappe.get_roles.return_value = [role]
            self.assertEqual(self.auth.login_destination(), destination)
        self.frappe.session.user = "Administrator"
        self.assertEqual(self.auth.login_destination(), "/dashboard/admin")
        self.frappe.session.user = "Guest"
        with self.assertRaises(Denied):
            self.auth.login_destination()

    def test_customer_return_paths_never_redirect_to_external_or_staff_destinations(self):
        for requested in (
            "https://evil.test", "//evil.test", "/%2f%2fevil.test", "/\\evil.test",
            "/dashboard/admin", "/app", "/login", "/%0aevil",
        ):
            self.assertEqual(self.auth.login_destination(requested), "/account")
        self.assertEqual(self.auth.login_destination("/checkout"), "/checkout")
        self.assertEqual(self.auth.login_destination("/payment?order=SO-1"), "/payment?order=SO-1")
        self.frappe.get_roles.return_value = ["Inventory Manager"]
        self.assertEqual(self.auth.login_destination("/dashboard/orders"), "/dashboard/inventory")
        self.assertEqual(self.auth.login_destination("/dashboard/inventory"), "/dashboard/inventory")

    def test_password_confirmation_length_and_strength_are_enforced(self):
        with patch.dict(sys.modules, self.modules):
            for password, confirmation in (("short", "short"), ("a" * 129, "a" * 129), ("a" * 12, "different")):
                with self.assertRaises(Denied):
                    self.auth.validate_new_password(password, confirmation)
            checker = self.modules["frappe.utils.password_strength"].test_password_strength
            checker.return_value = {"score": 1}
            with self.assertRaises(Denied):
                self.auth.validate_new_password("weakpassword123", "weakpassword123")

    def test_page_guards_redirect_guests_and_unauthorized_users_before_rendering(self):
        sessions = types.ModuleType("frappe.sessions")
        sessions.get_csrf_token = Mock(return_value="csrf")
        self.modules["frappe.sessions"] = sessions
        pages = load(ROOT / "utils/auth_pages.py", self.modules)
        render = Mock()
        guarded = pages.guard_website(render)
        self.frappe.session.user = "Guest"
        with self.assertRaises(Redirect):
            guarded(types.SimpleNamespace())
        self.assertEqual(self.frappe.local.flags.redirect_location, "/login?redirect-to=%2Faccount")
        render.assert_not_called()
        self.frappe.session.user = "customer@example.test"
        render.side_effect = Denied("Unauthorized")
        with self.assertRaises(Redirect):
            guarded(types.SimpleNamespace())
        self.assertEqual(self.frappe.local.flags.redirect_location, "/access-denied")

    def recovery_api(self):
        self.modules["intelligent_ordering.utils.authentication"] = self.auth
        limiter = types.ModuleType("frappe.rate_limiter")
        limiter.rate_limit = lambda **kwargs: lambda fn: fn
        utils = types.ModuleType("frappe.utils")
        utils.validate_email_address = lambda email, throw: email
        user = types.ModuleType("frappe.core.doctype.user.user")
        user.reset_password = Mock()
        user.update_password = Mock()
        self.modules.update({
            "frappe.rate_limiter": limiter, "frappe.utils": utils,
            "frappe.core.doctype.user.user": user,
        })
        return load(ROOT / "api/authentication.py", self.modules), user

    def test_recovery_does_not_expose_account_existence(self):
        api, user = self.recovery_api()
        with patch.dict(sys.modules, self.modules):
            known = api.forgot_password("customer@example.test")
            user.reset_password.side_effect = Denied("Does not exist")
            unknown = api.forgot_password("unknown@example.test")
        self.assertEqual(known, unknown)

    def test_invalid_reset_cannot_claim_success_for_an_existing_logged_in_session(self):
        api, user = self.recovery_api()
        self.frappe.local.response["http_status_code"] = 410
        with patch.dict(sys.modules, self.modules), self.assertRaises(Denied):
            api.reset_password("invalid", "unique passphrase for testing", "unique passphrase for testing")
        self.frappe.local.login_manager.logout.assert_not_called()
        user.update_password.assert_called_once()
