import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.products import create_category, list_products, save_product
from intelligent_ordering.api.inventory import adjust_stock
from intelligent_ordering.api.catalog import get_product


class TestWebsiteProductManagement(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.suffix = frappe.generate_hash(length=8)
        self.category = create_category(f"Website Products {self.suffix}")["name"]
        self.values = {
            "sku": f"WEB-{self.suffix}", "product_name": "Website product",
            "category": self.category, "price": "120", "currency": "KES",
        }

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def user(self, role):
        frappe.set_user("Administrator")
        user = frappe.get_doc({
            "doctype": "User", "email": f"products-{frappe.generate_hash(length=10)}@example.test",
            "first_name": "Products", "enabled": 1, "send_welcome_email": 0,
            "user_type": "Website User" if role == "Customer" else "System User",
            "roles": [{"role": role}],
        }).insert(ignore_permissions=True)
        frappe.set_user(user.name)

    def test_inventory_manager_creates_product_and_receives_stock_using_existing_ledger(self):
        warehouse = frappe.get_doc({
            "doctype": "Stock Warehouse", "warehouse_name": f"Website WH {self.suffix}", "status": "Active",
        }).insert()
        self.user("Inventory Manager")
        product = save_product(**self.values)["product"]
        self.assertFalse(frappe.db.exists("Stock Ledger Entry", {"product": product["name"]}))
        adjust_stock(product["name"], warehouse.name, "Opening", 5, remarks="Website opening stock")
        self.assertTrue(frappe.db.exists("Stock Ledger Entry", {"product": product["name"], "quantity_change": 5}))
        self.assertEqual(get_product(product["name"])["available_quantity"], 5)
        self.assertTrue(frappe.db.exists("Admin Audit Log", {
            "event_type": "Product created", "reference_name": product["name"],
        }))

    def test_store_manager_can_create_and_edit_but_not_receive_stock(self):
        self.user("Store Manager")
        category = create_category(f"Store Category {self.suffix}")
        self.assertTrue(category["name"])
        product = save_product(**self.values)["product"]
        updated = save_product(
            **{**self.values, "price": "130"}, product=product["name"], modified=str(product["modified"]),
        )["product"]
        self.assertEqual(float(updated["price"]), 130)
        with self.assertRaises(frappe.PermissionError):
            adjust_stock(product["name"], "not-a-warehouse", "Receipt", 1)

    def test_category_create_and_product_creation_do_not_expand_role_permissions(self):
        self.user("Order Manager")
        self.assertFalse(list_products()["can_create_category"])
        with self.assertRaises(frappe.PermissionError):
            create_category(f"Denied Category {self.suffix}")
        for role in ("Customer", "Finance Manager", "Customer Support", "Delivery Staff"):
            self.user(role)
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                save_product(**self.values)
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                list_products()
