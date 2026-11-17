import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class ProductError(Exception):
    pass


def load_api():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.session = types.SimpleNamespace(user="staff@example.test")
    frappe.PermissionError = frappe.ValidationError = ProductError
    frappe.throw = Mock(side_effect=lambda message, error: (_ for _ in ()).throw(error(message)))
    frappe.get_roles = Mock(return_value=["Store Manager"])
    frappe.get_list = Mock(return_value=[])
    frappe.get_doc = Mock()
    frappe.get_cached_value = Mock(return_value="Website User")
    frappe.has_permission = Mock(return_value=False)
    frappe.db = Mock()
    path = Path(__file__).parents[1] / "intelligent_ordering/api/products.py"
    spec = importlib.util.spec_from_file_location("products_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe}):
        spec.loader.exec_module(module)
    return module, frappe


class TestProductManagement(unittest.TestCase):
    def setUp(self):
        self.api, self.frappe = load_api()
        self.values = {"sku": "MILK", "product_name": "Milk", "category": "Dairy", "price": "120"}

    def test_only_existing_product_roles_can_access(self):
        for role in ("Customer", "Finance Manager", "Delivery Staff", "Delivery Manager", "Customer Support"):
            self.frappe.get_roles.return_value = [role]
            for operation in (self.api.list_products, lambda: self.api.save_product(**self.values),
                              lambda: self.api.create_category("Dairy")):
                with self.subTest(role=role), self.assertRaises(ProductError):
                    operation()
        self.frappe.get_doc.assert_not_called()
        self.frappe.get_list.assert_not_called()
        for role in ("Store Manager", "Order Manager", "Inventory Manager", "Business Admin", "System Manager"):
            self.frappe.get_roles.return_value = [role]
            self.api.list_products()
        self.frappe.session.user = "Guest"
        with self.assertRaises(ProductError):
            self.api.list_products()

    def test_create_preserves_native_permissions_and_never_writes_stock(self):
        doc = self.frappe.get_doc.return_value
        self.api.save_product(**self.values)
        values = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(values["doctype"], "Product")
        self.assertEqual(values["sku"], "MILK")
        self.assertNotIn("quantity", values)
        doc.insert.assert_called_once_with()
        self.frappe.db.sql.assert_not_called()
        doc.insert.side_effect = ProductError("Native create denied")
        with self.assertRaisesRegex(ProductError, "Native create"):
            self.api.save_product(**self.values)

    def test_native_image_upload_choices_follow_user_type(self):
        self.assertNotIn("image/webp", self.api.list_products()["upload_image_types"])
        self.frappe.get_cached_value.return_value = "System User"
        self.assertIn("image/webp", self.api.list_products()["upload_image_types"])

    def test_category_create_respects_document_permissions(self):
        doc = self.frappe.get_doc.return_value
        doc.insert.side_effect = ProductError("Category create denied")
        self.frappe.get_roles.return_value = ["Inventory Manager"]
        with self.assertRaisesRegex(ProductError, "Category create"):
            self.api.create_category("Dairy")
        doc.insert.assert_called_once_with()

    def test_edit_checks_write_permission_sku_and_stale_version(self):
        doc = self.frappe.get_doc.return_value
        doc.sku = "MILK"
        doc.modified = "2026-11-17 10:00:00"
        with self.assertRaisesRegex(ProductError, "changed"):
            self.api.save_product(**self.values, product="MILK", modified="old")
        doc.save.assert_not_called()
        self.api.save_product(**self.values, product="MILK", modified=doc.modified)
        doc.check_permission.assert_called_with("write")
        doc.save.assert_called_once_with()
        with self.assertRaisesRegex(ProductError, "SKU"):
            self.api.save_product(**{**self.values, "sku": "RENAMED"}, product="MILK", modified=doc.modified)

    def test_invalid_prices_currency_and_unattached_images_are_rejected(self):
        for changes in ({"price": "nan"}, {"price": "Infinity"}, {"price": "-1"},
                        {"currency": "K1S"}, {"enabled": "yes"}, {"image": "https://external.test/a.png"},
                        {"product_name": ""}):
            with self.subTest(changes=changes), self.assertRaises(ProductError):
                self.api.save_product(**{**self.values, **changes})
        self.frappe.db.exists.return_value = False
        with self.assertRaises(ProductError):
            self.api.save_product(**self.values, image="/files/not-attached.png", product="MILK")
        self.frappe.get_doc.assert_not_called()

    def test_paginated_search_and_separate_stock_authority(self):
        self.frappe.get_list.side_effect = [[{"name": "MILK"}, {"name": "BREAD"}], []]
        result = self.api.list_products(search="milk", page=2, page_size=1)
        self.assertTrue(result["has_more"])
        self.assertFalse(result["can_receive_stock"])
        call = self.frappe.get_list.call_args_list[0]
        self.assertEqual(call.kwargs["limit_start"], 1)
        self.assertEqual(call.kwargs["or_filters"][0], ["sku", "like", "%milk%"])
        self.frappe.get_list.side_effect = None
        self.frappe.get_list.return_value = []
        self.frappe.get_roles.return_value = ["Inventory Manager"]
        self.assertTrue(self.api.list_products()["can_receive_stock"])


if __name__ == "__main__":
    unittest.main()
