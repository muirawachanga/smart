import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.cart import add_item
from intelligent_ordering.api.checkout import create_order, get_checkout
from intelligent_ordering.api.inventory import (
    adjust_stock,
    get_dashboard,
    get_product_availability,
    list_movements,
    list_stock,
    record_order_return,
)
from intelligent_ordering.api.orders import update_order_status


class TestInventory(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        suffix = frappe.generate_hash(length=8)
        self.warehouse = frappe.get_doc(
            {
                "doctype": "Stock Warehouse",
                "warehouse_name": f"Test Warehouse {suffix}",
                "location": "Nairobi",
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        self.product = frappe.get_doc(
            {
                "doctype": "Product",
                "sku": f"STOCK-{suffix}",
                "product_name": f"Inventory Product {suffix}",
                "price": 25,
                "currency": "KES",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.delivery_area = frappe.get_doc({
            "doctype": "Delivery Area",
            "area_name": f"Inventory Area {suffix}",
            "currency": "KES",
            "delivery_fee": 0,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        self.inventory_user = self._make_user(
            f"inventory-{suffix}@example.test",
            ["Inventory Manager", "Order Manager"],
        )

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_initial_receipt_adjustment_and_negative_stock_protection(self):
        frappe.set_user(self.inventory_user.name)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 10)
        adjust_stock(self.product.name, self.warehouse.name, "Receipt", 5)
        adjust_stock(
            self.product.name, self.warehouse.name, "Adjustment", -3, "Damaged units"
        )

        balance = frappe.db.get_value(
            "Stock Balance",
            {"product": self.product.name, "warehouse": self.warehouse.name},
            ["quantity_on_hand", "reserved_quantity", "available_quantity"],
            as_dict=True,
        )
        self.assertEqual(balance.quantity_on_hand, 12)
        self.assertEqual(balance.reserved_quantity, 0)
        self.assertEqual(balance.available_quantity, 12)
        with self.assertRaises(frappe.ValidationError):
            adjust_stock(
                self.product.name, self.warehouse.name, "Adjustment", -20
            )
        with self.assertRaises(frappe.ValidationError):
            adjust_stock(self.product.name, self.warehouse.name, "Opening", 1)

        movements = list_movements(product=self.product.name)
        self.assertEqual(len(movements["movements"]), 3)
        self.assertEqual(
            {row.transaction_type for row in movements["movements"]},
            {"Adjustment", "Receipt", "Opening"},
        )

    def test_dashboard_stock_search_and_availability(self):
        frappe.set_user(self.inventory_user.name)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 3)

        availability = get_product_availability(self.product.name)
        self.assertEqual(availability["available_quantity"], 3)
        self.assertEqual(availability["stock_status"], "In Stock")

        stock = list_stock(search=self.product.sku, warehouse=self.warehouse.name)
        self.assertEqual(len(stock["stock"]), 1)
        self.assertEqual(stock["stock"][0].available_quantity, 3)
        dashboard = get_dashboard(low_stock_threshold=5)
        self.assertGreaterEqual(dashboard["summary"]["low_stock_products"], 1)
        self.assertGreaterEqual(dashboard["summary"]["total_stock"], 3)

    def test_out_of_stock_product_cannot_be_added_to_customer_cart(self):
        frappe.set_user(self.inventory_user.name)
        self.assertEqual(
            get_product_availability(self.product.name)["stock_status"],
            "Out of Stock",
        )
        customer = self._make_customer(f"customer-{frappe.generate_hash(8)}@example.test")
        frappe.set_user(customer.name)
        with self.assertRaises(frappe.ValidationError):
            add_item(self.product.name, 1)

        frappe.set_user(self.inventory_user.name)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 1)
        frappe.set_user(customer.name)
        result = add_item(self.product.name, 1)
        self.assertEqual(result["items"][0]["available_quantity"], 1)
        with self.assertRaises(frappe.ValidationError):
            add_item(self.product.name, 1)

    def test_customer_cannot_modify_stock(self):
        customer = self._make_customer(f"customer-{frappe.generate_hash(8)}@example.test")
        frappe.set_user(customer.name)
        with self.assertRaises(frappe.PermissionError):
            adjust_stock(self.product.name, self.warehouse.name, "Receipt", 1)
        frappe.set_user(self.inventory_user.name)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 4)
        ledger_name = frappe.db.get_value(
            "Stock Ledger Entry",
            {"product": self.product.name, "warehouse": self.warehouse.name},
            "name",
        )
        frappe.set_user(customer.name)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Stock Ledger Entry", ledger_name).save()

    def test_confirmation_reserves_and_dispatch_reduces_on_hand_once(self):
        order = self._create_order(5)
        frappe.set_user(self.inventory_user.name)
        pending_balance = self._balance()
        self.assertEqual(pending_balance.available_quantity, 10)

        update_order_status(order.name, "Confirmed")
        reserved_balance = self._balance()
        self.assertEqual(reserved_balance.quantity_on_hand, 10)
        self.assertEqual(reserved_balance.reserved_quantity, 5)
        self.assertEqual(reserved_balance.available_quantity, 5)

        update_order_status(order.name, "Confirmed")
        reservations = frappe.db.count(
            "Stock Ledger Entry",
            {
                "reference_order": order.name,
                "transaction_type": "Reservation",
            },
        )
        self.assertEqual(reservations, 1)

        update_order_status(order.name, "Processing")
        update_order_status(order.name, "Ready for Delivery")
        dispatched_balance = self._balance()
        self.assertEqual(dispatched_balance.quantity_on_hand, 5)
        self.assertEqual(dispatched_balance.reserved_quantity, 0)
        self.assertEqual(dispatched_balance.available_quantity, 5)

    def test_competing_orders_cannot_reserve_stock_twice(self):
        first = self._create_order(8)
        second = self._create_order(3)
        frappe.set_user(self.inventory_user.name)
        update_order_status(first.name, "Confirmed")

        self._assert_update_fails(second.name, "Confirmed")
        self.assertEqual(self._balance().available_quantity, 2)

    def test_order_reservations_allocate_across_multiple_warehouses(self):
        second_warehouse = frappe.get_doc(
            {
                "doctype": "Stock Warehouse",
                "warehouse_name": f"Secondary Warehouse {frappe.generate_hash(8)}",
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        frappe.set_user(self.inventory_user.name)
        adjust_stock(self.product.name, second_warehouse.name, "Opening", 5)
        order = self._create_order(12)
        update_order_status(order.name, "Confirmed")

        balances = frappe.get_all(
            "Stock Balance",
            filters={"product": self.product.name},
            fields=["quantity_on_hand", "reserved_quantity", "available_quantity"],
        )
        self.assertEqual(sum(row.reserved_quantity for row in balances), 12)
        self.assertEqual(sum(row.available_quantity for row in balances), 3)

        update_order_status(order.name, "Processing")
        update_order_status(order.name, "Ready for Delivery")
        balances = frappe.get_all(
            "Stock Balance",
            filters={"product": self.product.name},
            fields=["quantity_on_hand", "reserved_quantity"],
        )
        self.assertEqual(sum(row.quantity_on_hand for row in balances), 3)
        self.assertEqual(sum(row.reserved_quantity for row in balances), 0)

    def test_cancellation_releases_stock_and_dispatched_returns_are_required(self):
        order = self._create_order(4)
        frappe.set_user(self.inventory_user.name)
        update_order_status(order.name, "Confirmed")
        update_order_status(order.name, "Cancelled")
        released = self._balance()
        self.assertEqual(released.reserved_quantity, 0)
        self.assertEqual(released.available_quantity, 10)

        dispatched_order = self._create_order(3)
        update_order_status(dispatched_order.name, "Confirmed")
        update_order_status(dispatched_order.name, "Processing")
        update_order_status(dispatched_order.name, "Ready for Delivery")
        self._assert_update_fails(dispatched_order.name, "Cancelled")

        record_order_return(
            dispatched_order.name,
            self.product.name,
            self.warehouse.name,
            3,
            "Returned to warehouse",
        )
        update_order_status(dispatched_order.name, "Cancelled")
        self.assertEqual(self._balance().quantity_on_hand, 10)

    def test_order_confirmation_fails_when_stock_is_insufficient(self):
        order = self._create_order(8)
        frappe.set_user(self.inventory_user.name)
        adjust_stock(
            self.product.name, self.warehouse.name, "Adjustment", -5
        )
        self._assert_update_fails(order.name, "Confirmed")
        self.assertEqual(self._balance().available_quantity, 5)

    def _create_order(self, quantity):
        frappe.set_user(self.inventory_user.name)
        if not self._balance_exists():
            adjust_stock(self.product.name, self.warehouse.name, "Opening", 10)
        customer = self._make_customer(
            f"buyer-{frappe.generate_hash(8)}@example.test"
        )
        frappe.set_user(customer.name)
        add_item(self.product.name, quantity)
        checkout = get_checkout(delivery_area=self.delivery_area.name)
        result = create_order(
            customer_name="Inventory Buyer",
            phone="+254712345678",
            address_line_1="1 Main Road",
            city="Nairobi",
            request_token=str(uuid.uuid4()),
            cart_revision=checkout["cart_revision"],
            delivery_area=self.delivery_area.name,
            delivery_quote=checkout["delivery_quote"],
        )
        return frappe.get_doc("Sales Order", result["order"]["name"])

    def _assert_update_fails(self, order_name, status):
        savepoint = f"inventory_test_{frappe.generate_hash(6)}"
        frappe.db.savepoint(savepoint)
        try:
            with self.assertRaises(frappe.ValidationError):
                update_order_status(order_name, status)
        finally:
            frappe.db.rollback(save_point=savepoint)

    def _balance_exists(self):
        return frappe.db.exists(
            "Stock Balance",
            {"product": self.product.name, "warehouse": self.warehouse.name},
        )

    def _balance(self):
        return frappe.db.get_value(
            "Stock Balance",
            {"product": self.product.name, "warehouse": self.warehouse.name},
            ["quantity_on_hand", "reserved_quantity", "available_quantity"],
            as_dict=True,
        )

    def _make_customer(self, email):
        user = self._make_user(email, ["Customer"])
        frappe.set_user("Administrator")
        frappe.get_doc(
            {
                "doctype": "Customer Profile",
                "user": user.name,
                "full_name": "Inventory Buyer",
                "phone": "+254712345678",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        return user

    def _make_user(self, email, roles):
        previous_user = frappe.session.user
        frappe.set_user("Administrator")
        try:
            return frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@", 1)[0],
                    "user_type": "System User",
                    "enabled": 1,
                    "roles": [{"role": role} for role in roles],
                }
            ).insert(ignore_permissions=True)
        finally:
            frappe.set_user(previous_user)
