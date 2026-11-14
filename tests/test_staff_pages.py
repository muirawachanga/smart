import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class PermissionDenied(Exception):
    pass


def load_staff_pages():
    frappe = types.ModuleType("frappe")
    frappe.session = types.SimpleNamespace(user="test@example.test")
    frappe.PermissionError = PermissionDenied
    frappe.get_roles = Mock(return_value=[])
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(PermissionDenied(message)))
    path = Path(__file__).parents[1] / "intelligent_ordering/utils/staff_pages.py"
    spec = importlib.util.spec_from_file_location("staff_pages_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe}):
        spec.loader.exec_module(module)
    return module, frappe


class TestStaffPages(unittest.TestCase):
    def setUp(self):
        self.pages, self.frappe = load_staff_pages()

    def test_customer_and_guest_cannot_access_order_workspace(self):
        self.frappe.get_roles.return_value = ["Customer"]
        with self.assertRaises(PermissionDenied):
            self.pages.require_staff_page(types.SimpleNamespace(), "orders")
        self.frappe.session.user = "Guest"
        self.frappe.get_roles.return_value = ["Order Manager"]
        with self.assertRaises(PermissionDenied):
            self.pages.require_staff_page(types.SimpleNamespace(), "orders")

    def test_role_boundaries_prevent_cross_department_access(self):
        self.frappe.get_roles.return_value = ["Inventory Manager"]
        self.pages.require_staff_page(types.SimpleNamespace(), "inventory")
        with self.assertRaises(PermissionDenied):
            self.pages.require_staff_page(types.SimpleNamespace(), "orders")
        with self.assertRaises(PermissionDenied):
            self.pages.require_staff_page(types.SimpleNamespace(), "admin")

    def test_only_system_manager_sees_user_management_link(self):
        self.frappe.get_roles.return_value = ["Business Admin"]
        context = types.SimpleNamespace()
        self.pages.require_staff_page(context, "admin")
        self.assertFalse(context.can_manage_users)
        self.assertEqual(context.no_cache, 1)
        self.frappe.get_roles.return_value = ["System Manager"]
        self.pages.require_staff_page(context, "admin")
        self.assertTrue(context.can_manage_users)

    def test_delivery_staff_cannot_access_inventory(self):
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        self.pages.require_staff_page(types.SimpleNamespace(), "delivery")
        with self.assertRaises(PermissionDenied):
            self.pages.require_staff_page(types.SimpleNamespace(), "inventory")

    def test_support_can_only_open_its_read_only_workspace(self):
        self.frappe.get_roles.return_value = ["Customer Support"]
        self.pages.require_staff_page(types.SimpleNamespace(), "support")
        for page in ("orders", "admin", "inventory", "sales", "delivery"):
            with self.subTest(page=page), self.assertRaises(PermissionDenied):
                self.pages.require_staff_page(types.SimpleNamespace(), page)

    def test_support_read_hooks_do_not_bypass_customer_cart_ownership(self):
        path = Path(__file__).parents[1] / "intelligent_ordering/permissions.py"
        spec = importlib.util.spec_from_file_location("permissions_under_test", path)
        permissions = importlib.util.module_from_spec(spec)
        self.frappe.get_roles.return_value = ["Customer Support"]
        with patch.dict(sys.modules, {"frappe": self.frappe}):
            spec.loader.exec_module(permissions)
        user = self.frappe.session.user
        self.assertEqual(permissions.customer_profile_query(user), "")
        self.assertEqual(permissions.sales_order_query(user), "")
        self.assertEqual(permissions.shopping_cart_query(user), "1 = 0")
        self.assertIsNone(permissions.customer_profile_has_permission(None, "read", user))
        self.assertIsNone(permissions.sales_order_has_permission(None, "read", user))
        self.assertFalse(permissions.shopping_cart_has_permission(None, "read", user))


if __name__ == "__main__":
    unittest.main()
