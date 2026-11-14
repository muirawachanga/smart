import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.cart import (
    add_item,
    clear_cart,
    get_cart,
    merge_guest_cart,
    remove_item,
    update_item,
)
from intelligent_ordering.api.inventory import adjust_stock


class TestShoppingCart(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        suffix = frappe.generate_hash(length=8)
        self.customer = self._create_customer(f"cart-{suffix}@example.com")
        self.other_customer = self._create_customer(f"other-{suffix}@example.com")
        self.product = frappe.get_doc(
            {
                "doctype": "Product",
                "sku": f"CART-{suffix}",
                "product_name": f"Cart Product {suffix}",
                "price": 125,
                "currency": "KES",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.warehouse = frappe.get_doc(
            {
                "doctype": "Stock Warehouse",
                "warehouse_name": f"Cart Warehouse {suffix}",
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 100)
        frappe.set_user(self.customer.name)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_add_item_and_persist_it_in_database(self):
        result = add_item(
            self.product.name,
            2,
            guest_items='[{"product":"ignored","quantity":50,"price":0}]',
        )

        self.assertEqual(result["item_count"], 2)
        self.assertEqual(result["items"][0]["product"], self.product.name)
        self.assertEqual(result["items"][0]["subtotal"], 250)
        self.assertEqual(get_cart()["total"], 250)

    def test_guest_prices_are_read_from_product_records(self):
        frappe.set_user("Guest")
        result = get_cart(
            f'[{{"product":"{self.product.name}","quantity":2,"price":0}}]'
        )

        self.assertEqual(result["items"][0]["unit_price"], 125)
        self.assertEqual(result["total"], 250)
        frappe.set_user(self.customer.name)

    def test_update_and_remove_items(self):
        add_item(self.product.name, 1)
        updated = update_item(self.product.name, 3)
        self.assertEqual(updated["items"][0]["quantity"], 3)
        self.assertEqual(updated["total"], 375)

        removed = remove_item(self.product.name)
        self.assertEqual(removed["items"], [])
        self.assertEqual(removed["total"], 0)

    def test_guest_and_customer_additions_cannot_exceed_available_stock(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.ValidationError):
            add_item(self.product.name, 101)
        guest_cart = add_item(self.product.name, 1)
        self.assertEqual(guest_cart["item_count"], 1)
        frappe.set_user(self.customer.name)
        add_item(self.product.name, 1)
        with self.assertRaises(frappe.ValidationError):
            add_item(self.product.name, 100)

    def test_empty_and_cleared_cart(self):
        self.assertEqual(get_cart()["items"], [])
        add_item(self.product.name, 1)
        result = clear_cart()
        self.assertEqual(result["items"], [])
        self.assertEqual(get_cart()["item_count"], 0)

    def test_current_database_price_is_used_for_totals(self):
        add_item(self.product.name, 2)
        frappe.set_user("Administrator")
        self.product.price = 199
        self.product.save(ignore_permissions=True)
        frappe.set_user(self.customer.name)

        result = get_cart()

        self.assertEqual(result["items"][0]["unit_price"], 199)
        self.assertEqual(result["total"], 398)
        self.assertEqual(
            frappe.db.get_value("Shopping Cart", self.customer.name, "total"),
            398,
        )

    def test_disabled_or_missing_product_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            add_item("missing-product", 1)
        with self.assertRaises(frappe.ValidationError):
            add_item(self.product.name, 0)

        frappe.set_user("Administrator")
        self.product.enabled = 0
        self.product.save(ignore_permissions=True)
        frappe.set_user(self.customer.name)
        with self.assertRaises(frappe.ValidationError):
            add_item(self.product.name, 1)

    def test_guest_cart_merge_and_duplicate_products(self):
        add_item(self.product.name, 1)
        result = merge_guest_cart(
            f'[{{"product":"{self.product.name}","quantity":2}}]'
        )

        self.assertEqual(result["item_count"], 3)
        self.assertEqual(len(result["items"]), 1)

    def test_customer_cannot_read_another_customers_cart(self):
        add_item(self.product.name, 1)
        cart_name = frappe.db.get_value(
            "Shopping Cart", {"user": self.customer.name}, "name"
        )
        frappe.set_user(self.other_customer.name)

        self.assertEqual(get_cart()["items"], [])
        self.assertEqual(frappe.get_list("Shopping Cart"), [])
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Shopping Cart", cart_name).check_permission("read")

    def _create_customer(self, email):
        return frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": email.split("@")[0],
                "enabled": 1,
                "user_type": "Website User",
                "send_welcome_email": 0,
                "roles": [{"role": "Customer"}],
            }
        ).insert(ignore_permissions=True)
