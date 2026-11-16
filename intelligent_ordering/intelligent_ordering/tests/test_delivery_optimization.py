import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.deliveries import (
    assign_delivery_group,
    create_delivery,
    my_delivery_route,
    set_delivery_coordinates,
    share_rider_location,
    suggest_delivery_group,
)


class TestDeliveryOptimization(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        suffix = frappe.generate_hash(length=8)
        rider = frappe.get_doc({
            "doctype": "User", "email": f"delivery-{suffix}@example.test",
            "first_name": "Test Rider", "send_welcome_email": 0,
            "user_type": "System User", "roles": [{"role": "Delivery Staff"}],
        }).insert(ignore_permissions=True)
        self.rider = rider.name
        customer_user = frappe.get_doc({
            "doctype": "User", "email": f"route-customer-{suffix}@example.test",
            "first_name": "Route Customer", "send_welcome_email": 0,
            "user_type": "Website User", "roles": [{"role": "Customer"}],
        }).insert(ignore_permissions=True)
        customer = frappe.get_doc({
            "doctype": "Customer Profile", "user": customer_user.name, "full_name": "Route Customer",
            "phone": "+254712345678", "enabled": 1,
        }).insert(ignore_permissions=True)
        area = frappe.get_doc({
            "doctype": "Delivery Area", "area_name": f"Route Area {suffix}",
            "currency": "KES", "delivery_fee": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        address = frappe.get_doc({
            "doctype": "Customer Address", "customer": customer.name,
            "address_line_1": "1 Test Road", "city": "Nairobi",
        }).insert(ignore_permissions=True)
        product = frappe.get_doc({
            "doctype": "Product", "sku": f"ROUTE-{suffix}",
            "product_name": "Route Product", "price": 100, "currency": "KES", "enabled": 1,
        }).insert(ignore_permissions=True)
        self.deliveries = []
        for longitude in (36.80, 36.81):
            previous = getattr(frappe.flags, "creating_checkout_order", False)
            frappe.flags.creating_checkout_order = True
            try:
                order = frappe.get_doc({
                    "doctype": "Sales Order", "customer": customer.name,
                    "customer_name_snapshot": "Route Customer", "customer_phone_snapshot": "+254712345678",
                    "delivery_address": address.name, "delivery_address_snapshot": "1 Test Road, Nairobi",
                    "delivery_area": area.name, "items": [{"product": product.name, "quantity": 1}],
                }).insert(ignore_permissions=True)
            finally:
                frappe.flags.creating_checkout_order = previous
            order.db_set("status", "Ready for Delivery")
            delivery = create_delivery(order.name)
            set_delivery_coordinates(delivery["name"], -1.28, longitude)
            self.deliveries.append(delivery["name"])
        frappe.set_user(self.rider)
        share_rider_location(-1.28, 36.80, 10)
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_suggest_assign_and_rider_route_use_existing_deliveries(self):
        from frappe.utils import today

        plan = suggest_delivery_group(self.deliveries[0], radius_km=5, max_stops=5)
        self.assertEqual(plan["rider"], self.rider)
        self.assertEqual({stop["name"] for stop in plan["route"]}, set(self.deliveries))
        assign_delivery_group(self.rider, self.deliveries, today(), plan["plan_token"])
        for name in self.deliveries:
            row = frappe.get_doc("Delivery", name)
            self.assertEqual(row.status, "Assigned")
            self.assertEqual(row.assigned_delivery_person, self.rider)
            self.assertTrue(row.activities)
        frappe.set_user(self.rider)
        route = my_delivery_route()
        self.assertEqual({stop["name"] for stop in route["route"]}, set(self.deliveries))
        self.assertEqual(route["missing_coordinates"], 0)
