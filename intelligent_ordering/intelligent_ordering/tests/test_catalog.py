import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.catalog import get_catalog


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
