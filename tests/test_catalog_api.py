import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class CatalogError(Exception):
    pass


def load_catalog():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.ValidationError = CatalogError
    frappe.DoesNotExistError = CatalogError
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(CatalogError(message)))
    frappe.db = Mock()
    frappe.get_all = Mock(return_value=[])
    path = Path(__file__).parents[1] / "intelligent_ordering/api/catalog.py"
    spec = importlib.util.spec_from_file_location("catalog_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe}):
        spec.loader.exec_module(module)
    return module, frappe


class TestCatalogApi(unittest.TestCase):
    def setUp(self):
        self.catalog, self.frappe = load_catalog()

    def test_sort_is_validated_and_applied_before_pagination(self):
        self.frappe.db.sql.side_effect = [[(2,)], [{"name": "A"}, {"name": "B"}]]
        result = self.catalog.get_catalog(page_size=1, sort="price_desc")
        query, values = self.frappe.db.sql.call_args.args
        self.assertIn("ORDER BY p.price DESC, p.name ASC", query)
        self.assertEqual(values, [2, 0])
        self.assertEqual(result["products"], [{"name": "A"}])
        self.assertTrue(result["has_more"])

    def test_rejects_untrusted_sort_before_sql(self):
        for value in ("p.price DESC; DROP TABLE `tabProduct`", ["name_asc"]):
            with self.subTest(value=value), self.assertRaises(CatalogError):
                self.catalog.get_catalog(sort=value)
        self.frappe.db.sql.assert_not_called()

    def test_search_and_category_filters_are_parameterized(self):
        self.frappe.db.exists.return_value = True
        self.frappe.db.sql.side_effect = [[(0,)], []]
        result = self.catalog.get_catalog(search="50%_off!", category="Drinks", page=2, page_size=5)
        query, values = self.frappe.db.sql.call_args.args
        self.assertIn("p.category = %s", query)
        self.assertIn("LIKE %s ESCAPE '!'", query)
        self.assertEqual(values, [
            "Drinks", "%50!%!_off!!%", "%50!%!_off!!%", "%50!%!_off!!%", 6, 5,
        ])
        self.assertEqual(result["products"], [])
        self.assertFalse(result["has_more"])

    def test_disabled_category_is_not_available_as_a_filter(self):
        self.frappe.db.exists.return_value = False
        with self.assertRaisesRegex(CatalogError, "category is unavailable"):
            self.catalog.get_catalog(category="disabled")
        self.frappe.db.sql.assert_not_called()

    def test_detail_is_parameterized_and_only_returns_public_products(self):
        self.frappe.db.sql.return_value = [{"name": "SKU'1"}]
        result = self.catalog.get_product(" SKU'1 ")
        query, values = self.frappe.db.sql.call_args.args
        self.assertEqual(result["name"], "SKU'1")
        self.assertIn("p.enabled = 1", query)
        self.assertIn("c.name IS NOT NULL", query)
        self.assertIn("p.name = %s", query)
        self.assertEqual(values, ["SKU'1"])
        self.assertNotIn("SKU'1", query)

    def test_detail_rejects_invalid_and_unavailable_products(self):
        for value in ("", " " * 2, "x" * 141, None):
            with self.subTest(value=value), self.assertRaises(CatalogError):
                self.catalog.get_product(value)
        self.frappe.db.sql.return_value = []
        with self.assertRaisesRegex(CatalogError, "unavailable"):
            self.catalog.get_product("missing")


if __name__ == "__main__":
    unittest.main()
