import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.cart import add_item, get_cart, merge_guest_cart, update_item
from intelligent_ordering.api.catalog import get_catalog, get_product
from intelligent_ordering.api.checkout import create_order, get_checkout, get_checkout_attempt
from intelligent_ordering.api.orders import (
    get_my_orders,
    get_my_order,
    get_order,
    list_orders,
    update_order_status,
)
from intelligent_ordering.api.inventory import adjust_stock
from intelligent_ordering.utils.staff_pages import require_staff_page


class TestCheckout(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        suffix = frappe.generate_hash(length=8)
        self.customer = self._make_user(f"customer-{suffix}@example.test", "Customer")
        self.profile = frappe.get_doc(
            {
                "doctype": "Customer Profile",
                "user": self.customer.name,
                "full_name": "Test Customer",
                "phone": "+254700000000",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.delivery_area = frappe.get_doc({
            "doctype": "Delivery Area",
            "area_name": f"Checkout Area {suffix}",
            "currency": "KES",
            "delivery_fee": 0,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        self.product = frappe.get_doc(
            {
                "doctype": "Product",
                "sku": f"CHECKOUT-{suffix}",
                "product_name": "Checkout Test Product",
                "price": 125,
                "currency": "KES",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.warehouse = frappe.get_doc(
            {
                "doctype": "Stock Warehouse",
                "warehouse_name": f"Checkout Warehouse {suffix}",
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 20)
        frappe.set_user(self.customer.name)
        add_item(self.product.name, 2)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_checkout_creates_pending_order_from_server_prices_and_clears_cart(self):
        result = self._submit_order()

        self.assertFalse(result["duplicate"])
        order = result["order"]
        self.assertEqual(order["status"], "Pending")
        self.assertEqual(order["subtotal"], 250)
        self.assertEqual(order["total"], 250)
        self.assertEqual(order["customer_name"], "Test Customer")
        self.assertTrue(order["order_datetime"])
        self.assertEqual(len(order["items"]), 1)
        self.assertEqual(order["items"][0]["unit_price"], 125)
        self.assertEqual(order["items"][0]["line_total"], 250)
        self.assertEqual(result["cart"]["items"], [])

    def test_invalid_customer_information_does_not_clear_cart(self):
        checkout = get_checkout()
        with self.assertRaises(frappe.ValidationError):
            create_order(
                customer_name="",
                phone="not a phone",
                address_line_1="1 Main Road",
                city="Nairobi",
                request_token=str(uuid.uuid4()),
                cart_revision=checkout["cart_revision"],
            )
        self.assertEqual(len(get_cart()["items"]), 1)

    def test_empty_cart_cannot_be_submitted(self):
        cart_doc = frappe.get_doc(
            "Shopping Cart",
            frappe.db.get_value("Shopping Cart", {"user": self.customer.name}),
        )
        cart_doc.set("items", [])
        cart_doc.save()
        checkout = get_checkout()

        with self.assertRaises(frappe.ValidationError):
            create_order(
                customer_name="Test Customer",
                phone="+254700000000",
                address_line_1="1 Main Road",
                city="Nairobi",
                request_token=str(uuid.uuid4()),
                cart_revision=checkout["cart_revision"],
            )
        self.assertEqual(get_cart()["items"], [])

    def test_changed_product_price_invalidates_reviewed_checkout(self):
        checkout = get_checkout()
        frappe.set_user("Administrator")
        self.product.price = 150
        self.product.save(ignore_permissions=True)
        frappe.set_user(self.customer.name)

        with self.assertRaises(frappe.ValidationError):
            create_order(
                customer_name="Test Customer",
                phone="+254700000000",
                address_line_1="1 Main Road",
                city="Nairobi",
                request_token=str(uuid.uuid4()),
                cart_revision=checkout["cart_revision"],
            )
        self.assertEqual(len(get_cart()["items"]), 1)

    def test_duplicate_submission_returns_the_existing_order(self):
        token = str(uuid.uuid4())
        first = self._submit_order(token=token)
        duplicate = self._submit_order(token=token)

        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["order"]["name"], first["order"]["name"])

    def test_customer_cannot_read_another_customers_order(self):
        result = self._submit_order()
        other_customer = self._make_user(
            f"other-{frappe.generate_hash(length=8)}@example.test", "Customer"
        )

        frappe.set_user(other_customer.name)
        with self.assertRaises(frappe.PermissionError):
            get_order(result["order"]["name"])
        with self.assertRaises(frappe.PermissionError):
            get_my_order(result["order"]["name"])

    def test_confirmation_remains_owner_scoped_for_customer_with_staff_role(self):
        order = self._submit_order()["order"]
        self.assertEqual(get_my_order(order["name"])["name"], order["name"])
        other = self._make_user(
            f"staff-customer-{frappe.generate_hash(length=8)}@example.test", "Customer"
        )
        frappe.set_user("Administrator")
        other.add_roles("Order Manager")
        frappe.set_user(other.name)
        with self.assertRaises(frappe.PermissionError):
            get_my_order(order["name"])

    def test_checkout_attempt_recovers_only_the_owners_order(self):
        token = str(uuid.uuid4())
        self.assertIsNone(get_checkout_attempt(token)["order_name"])
        order = self._submit_order(token=token)["order"]
        self.assertEqual(get_checkout_attempt(token)["order_name"], order["name"])
        other = self._make_user(
            f"recovery-{frappe.generate_hash(length=8)}@example.test", "Customer"
        )
        frappe.set_user(other.name)
        with self.assertRaises(frappe.PermissionError):
            get_checkout_attempt(token)

    def test_customer_journey_from_catalog_through_order_recovery(self):
        frappe.set_user("Administrator")
        category = frappe.get_doc({
            "doctype": "Product Category",
            "category_name": f"Journey {frappe.generate_hash(length=8)}",
            "enabled": 1,
        }).insert(ignore_permissions=True)
        self.product.category = category.name
        self.product.save(ignore_permissions=True)
        self.delivery_area.delivery_fee = 30
        self.delivery_area.save(ignore_permissions=True)

        frappe.set_user("Guest")
        listing = get_catalog(search=self.product.sku, category=category.name, sort="price_asc")
        self.assertEqual(listing["products"][0]["name"], self.product.name)
        self.assertEqual(get_product(self.product.name)["available_quantity"], 20)
        guest_cart = add_item(self.product.name, 1)

        frappe.set_user(self.customer.name)
        merged = merge_guest_cart(json.dumps(guest_cart["items"]))
        self.assertEqual(merged["items"][0]["quantity"], 3)
        updated = update_item(self.product.name, 4)
        self.assertEqual(updated["total"], 500)
        quote = get_checkout(delivery_area=self.delivery_area.name)
        self.assertEqual(quote["delivery_fee"], 30)
        self.assertEqual(quote["total"], 530)
        token = str(uuid.uuid4())
        result = create_order(
            customer_name="Test Customer",
            phone="+254700000000",
            address_line_1="1 Main Road",
            city="Nairobi",
            request_token=token,
            cart_revision=quote["cart_revision"],
            delivery_area=self.delivery_area.name,
            delivery_quote=quote["delivery_quote"],
        )
        order = result["order"]
        self.assertEqual(order["status"], "Pending")
        self.assertEqual(order["payment_status"], "Unpaid")
        self.assertEqual(order["total"], 530)
        self.assertEqual(order["items"][0]["quantity"], 4)
        self.assertEqual(order["items"][0]["unit_price"], 125)
        self.assertEqual(result["cart"]["items"], [])
        self.assertEqual(get_checkout_attempt(token)["order_name"], order["name"])
        self.assertEqual(get_my_order(order["name"])["total"], 530)

    def test_checkout_rejects_stock_reduced_after_review(self):
        quote = get_checkout(delivery_area=self.delivery_area.name)
        frappe.set_user("Administrator")
        adjust_stock(self.product.name, self.warehouse.name, "Adjustment", -19)
        frappe.set_user(self.customer.name)
        with self.assertRaises(frappe.ValidationError):
            create_order(
                customer_name="Test Customer", phone="+254700000000",
                address_line_1="1 Main Road", city="Nairobi",
                request_token=str(uuid.uuid4()), cart_revision=quote["cart_revision"],
                delivery_area=self.delivery_area.name, delivery_quote=quote["delivery_quote"],
            )
        self.assertEqual(get_cart()["items"][0]["quantity"], 2)

    def test_changed_delivery_fee_rejects_old_quote(self):
        quote = get_checkout(delivery_area=self.delivery_area.name)
        frappe.set_user("Administrator")
        self.delivery_area.delivery_fee = 50
        self.delivery_area.save(ignore_permissions=True)
        frappe.set_user(self.customer.name)
        with self.assertRaises(frappe.ValidationError):
            create_order(
                customer_name="Test Customer", phone="+254700000000",
                address_line_1="1 Main Road", city="Nairobi",
                request_token=str(uuid.uuid4()), cart_revision=quote["cart_revision"],
                delivery_area=self.delivery_area.name, delivery_quote=quote["delivery_quote"],
            )
        self.assertEqual(get_cart()["items"][0]["quantity"], 2)

    def test_customer_history_and_staff_order_management(self):
        result = self._submit_order()
        history = get_my_orders()
        self.assertEqual(
            [row.name for row in history["orders"]], [result["order"]["name"]]
        )

        with self.assertRaises(frappe.PermissionError):
            list_orders(status="Pending")

        staff = self._make_user(
            f"manager-{frappe.generate_hash(length=8)}@example.test",
            "Order Manager",
        )
        frappe.set_user(staff.name)
        listing = list_orders(search=result["order"]["name"])
        self.assertEqual(
            [row.name for row in listing["orders"]], [result["order"]["name"]]
        )
        updated = update_order_status(result["order"]["name"], "Confirmed")
        self.assertEqual(updated["status"], "Confirmed")

        with self.assertRaises(frappe.ValidationError):
            update_order_status(result["order"]["name"], "Completed")

        order_doc = frappe.get_doc("Sales Order", result["order"]["name"])
        order_doc.total = 1
        with self.assertRaises(frappe.ValidationError):
            order_doc.save()

    def test_staff_workspace_requires_the_corresponding_role(self):
        context = frappe._dict()
        with self.assertRaises(frappe.PermissionError):
            require_staff_page(context, "orders")
        staff = self._make_user(
            f"workspace-{frappe.generate_hash(length=8)}@example.test", "Order Manager"
        )
        frappe.set_user(staff.name)
        require_staff_page(context, "orders")
        self.assertFalse(context.can_manage_users)
        with self.assertRaises(frappe.PermissionError):
            require_staff_page(context, "admin")

    def _submit_order(self, token=None):
        checkout = get_checkout(delivery_area=self.delivery_area.name)
        return create_order(
            customer_name="Test Customer",
            phone="+254700000000",
            address_line_1="1 Main Road",
            city="Nairobi",
            request_token=token or str(uuid.uuid4()),
            cart_revision=checkout["cart_revision"],
            delivery_area=self.delivery_area.name,
            delivery_quote=checkout["delivery_quote"],
        )

    def _make_user(self, email, role):
        previous_user = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@", 1)[0],
                    "user_type": "Website User",
                    "enabled": 1,
                }
            ).insert(ignore_permissions=True)
            user.add_roles(role)
            return user
        finally:
            frappe.set_user(previous_user)
