import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.catalog import get_catalog, get_product


class TestCatalog(FrappeTestCase):
    def setUp(self):
        suffix = frappe.generate_hash(length=8)
        self.category = frappe.get_doc(
            {
                "doctype": "Product Category",
                "category_name": f"Test Category {suffix}",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.product = frappe.get_doc(
            {
                "doctype": "Product",
                "sku": f"TEST-{suffix}",
                "product_name": f"Catalog Test Product {suffix}",
                "category": self.category.name,
                "description": "Catalog integration test",
                "price": 125,
                "currency": "KES",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)

    def test_search_returns_matching_enabled_product_and_category(self):
        result = get_catalog(search=self.product.sku, page=1, page_size=20)

        self.assertEqual(len(result["products"]), 1)
        self.assertEqual(result["products"][0]["sku"], self.product.sku)
        self.assertEqual(
            result["products"][0]["category"], self.category.category_name
        )
        self.assertEqual(result["total"], 1)

    def test_disabled_category_hides_its_products(self):
        self.category.enabled = 0
        self.category.save(ignore_permissions=True)

        result = get_catalog(search=self.product.sku, page=1, page_size=20)

        self.assertEqual(result["products"], [])
        self.assertEqual(result["total"], 0)

    def test_invalid_page_size_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            get_catalog(page=1, page_size=101)

    def test_product_detail_uses_public_visibility_rules(self):
        self.assertEqual(get_product(self.product.name)["sku"], self.product.sku)
        self.category.enabled = 0
        self.category.save(ignore_permissions=True)
        with self.assertRaises(frappe.DoesNotExistError):
            get_product(self.product.name)
        self.category.enabled = 1
        self.category.save(ignore_permissions=True)
        self.product.enabled = 0
        self.product.save(ignore_permissions=True)
        with self.assertRaises(frappe.DoesNotExistError):
            get_product(self.product.name)

    def test_sorting_is_applied_before_pagination(self):
        other = frappe.get_doc(
            {
                "doctype": "Product",
                "sku": f"{self.product.sku}-B",
                "product_name": f"{self.product.product_name} B",
                "category": self.category.name,
                "price": 25,
                "currency": "KES",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        first = get_catalog(category=self.category.name, page_size=1, sort="price_asc")
        second = get_catalog(category=self.category.name, page=2, page_size=1, sort="price_asc")
        self.assertEqual(first["products"][0]["name"], other.name)
        self.assertTrue(first["has_more"])
        self.assertEqual(second["products"][0]["name"], self.product.name)
        self.assertFalse(second["has_more"])

    def test_invalid_sort_and_product_reference_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            get_catalog(sort="p.price DESC; DROP TABLE `tabProduct`")
        with self.assertRaises(frappe.ValidationError):
            get_product(" " * 2)
