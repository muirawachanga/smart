from uuid import uuid4

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from intelligent_ordering.utils.cart import round_money
from intelligent_ordering.utils.checkout import (
    validate_order_status_transition,
    validate_request_token,
)
from intelligent_ordering.utils.delivery_rates import get_area_quote
from intelligent_ordering.utils.order_fulfillment import preparation_minutes


class SalesOrder(Document):
    def validate(self):
        if self.is_new():
            self._validate_new_order()
            return

        original = self.get_doc_before_save()
        if not original:
            frappe.throw("The original order could not be loaded.", frappe.ValidationError)
        cancellation_workflow = getattr(frappe.flags, "processing_customer_cancellation", False)
        cancellation_fields = (
            "cancellation_request_status", "cancellation_reason", "cancellation_requested_at",
            "cancellation_resolved_at", "cancellation_resolved_by", "cancellation_response",
        )
        if any(self.get(field) != original.get(field) for field in cancellation_fields) and not cancellation_workflow:
            frappe.throw("Use the cancellation request workflow.", frappe.PermissionError)
        customer_request = cancellation_workflow and "Customer" in frappe.get_roles(frappe.session.user)
        if customer_request and (
            self.status != original.status or original.get("cancellation_request_status") not in (None, "", "Rejected")
            or self.get("cancellation_request_status") != "Requested"
            or any(self.get(field) for field in (
                "cancellation_resolved_at", "cancellation_resolved_by", "cancellation_response",
            ))
        ):
            frappe.throw("Customers can only request cancellation, not approve it.", frappe.PermissionError)
        checkout_confirmation = (
            getattr(frappe.flags, "confirming_cod_order", None) == self.name
            and original.status == "Pending"
            and self.status == "Confirmed"
            and self.payment_method == "Cash on Delivery"
            and self.payment_status == "Unpaid"
        )
        if (
            "Customer" in frappe.get_roles(frappe.session.user)
            and not getattr(frappe.flags, "processing_delivery", False)
            and not customer_request
            and not checkout_confirmation
        ):
            frappe.throw(
                "Customers cannot modify submitted orders.",
                frappe.PermissionError,
            )
        self._validate_unchanged_order_data(original)
        self._validate_status_transition(original.status)
        if self.status == "Confirmed" and original.status != "Confirmed":
            self.confirmed_at = now_datetime()
            self.preparation_minutes = preparation_minutes()
        elif not getattr(frappe.flags, "processing_order_fulfillment", False) and (
            self.confirmed_at != original.confirmed_at
            or self.preparation_minutes != original.preparation_minutes
        ):
            frappe.throw("Order preparation timing is managed by the fulfillment workflow.",
                         frappe.PermissionError)
        if self.status == "Completed" and self.payment_status != "Paid":
            frappe.throw(
                "Only a verified paid order can be completed.",
                frappe.ValidationError,
            )
        if self.status == "Completed" and original.status != "Completed":
            delivery = frappe.db.get_value(
                "Delivery", {"order": self.name},
                ["status", "customer_receipt_confirmed"], as_dict=True,
            )
            if (
                not getattr(frappe.flags, "processing_delivery", False)
                or not delivery or delivery.status != "Delivered" or not delivery.customer_receipt_confirmed
            ):
                frappe.throw("The customer must confirm receipt before completing this order.",
                             frappe.ValidationError)
        if self.status == "Cancelled" and original.status != "Cancelled":
            if frappe.db.exists("Delivery", {"order": self.name, "status": ["!=", "Cancelled"]}):
                frappe.throw("Cancel the delivery before cancelling its order.", frappe.ValidationError)
        if self.status in {"Completed", "Cancelled"} and self.get("cancellation_request_status") == "Requested":
            self.cancellation_request_status = "Approved" if self.status == "Cancelled" else "Rejected"
            self.cancellation_resolved_at = now_datetime()
            self.cancellation_resolved_by = frappe.session.user
            self.cancellation_response = f"Order {self.status.lower()} through the fulfillment workflow."

    def _validate_new_order(self):
        if not getattr(frappe.flags, "creating_checkout_order", False):
            frappe.throw(
                "Orders must be created through the checkout workflow.",
                frappe.PermissionError,
            )
        if self.status and self.status != "Pending":
            frappe.throw(
                "New orders must start with Pending status.",
                frappe.ValidationError,
            )
        self.status = "Pending"
        self.payment_status = "Unpaid"
        self.payment_method = self.payment_method or "M-Pesa"
        if self.payment_method not in {"M-Pesa", "Cash on Delivery"}:
            frappe.throw("Select a supported payment method.", frappe.ValidationError)
        self.order_datetime = now_datetime()
        self.checkout_token = self.checkout_token or str(uuid4())

        try:
            self.checkout_token = validate_request_token(self.checkout_token)
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)

        customer = frappe.db.get_value(
            "Customer Profile",
            self.customer,
            ["user", "enabled"],
            as_dict=True,
        )
        if not customer or not customer.enabled:
            frappe.throw("The customer profile is unavailable.", frappe.ValidationError)
        if (
            "Customer" in frappe.get_roles(frappe.session.user)
            and customer.user != frappe.session.user
        ):
            frappe.throw(
                "You cannot create an order for another customer.",
                frappe.PermissionError,
            )

        if self.customer and self.delivery_address:
            address_customer = frappe.db.get_value(
                "Customer Address", self.delivery_address, "customer"
            )
            if address_customer != self.customer:
                frappe.throw(
                    "The delivery address must belong to the selected customer.",
                    frappe.ValidationError,
                )

        if not self.customer_name_snapshot or not self.customer_phone_snapshot:
            frappe.throw(
                "Customer name and phone number are required.",
                frappe.ValidationError,
            )
        if not self.delivery_address or not self.delivery_address_snapshot:
            frappe.throw("A delivery address is required.", frappe.ValidationError)
        if not self.items:
            frappe.throw("An order must contain at least one product.", frappe.ValidationError)

        currencies = set()
        subtotal = 0.0
        seen_products = set()
        for item in self.items:
            if item.product in seen_products:
                frappe.throw(
                    "A product may only appear once in an order.",
                    frappe.ValidationError,
                )
            seen_products.add(item.product)

            quantity = flt(item.quantity)
            if quantity <= 0 or not quantity.is_integer():
                frappe.throw(
                    "Order quantities must be positive whole numbers.",
                    frappe.ValidationError,
                )

            product = frappe.db.get_value(
                "Product",
                {"name": item.product, "enabled": 1},
                ["sku", "product_name", "price", "currency", "category"],
                as_dict=True,
            )
            if not product or (
                product.category
                and not frappe.db.exists(
                    "Product Category",
                    {"name": product.category, "enabled": 1},
                )
            ):
                frappe.throw(
                    "The order contains an unavailable product.",
                    frappe.ValidationError,
                )

            currency = (product.currency or "KES").upper()
            currencies.add(currency)
            if len(currencies) > 1:
                frappe.throw(
                    "Products in one order must use the same currency.",
                    frappe.ValidationError,
                )

            try:
                unit_price = round_money(product.price)
                line_total = round_money(unit_price * int(quantity))
            except ValueError as error:
                frappe.throw(str(error), frappe.ValidationError)

            item.quantity = int(quantity)
            item.product_name_snapshot = product.product_name
            item.product_sku_snapshot = product.sku
            item.product_category_snapshot = product.category or ""
            item.currency = currency
            item.unit_price = unit_price
            item.line_total = line_total
            subtotal += line_total

        self.currency = next(iter(currencies), "KES")
        try:
            self.subtotal = round_money(subtotal)
            quote = get_area_quote(self.delivery_area, self.currency, for_update=True)
            self.delivery_fee = quote["delivery_fee"]
            self.total = round_money(self.subtotal + self.delivery_fee)
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)

    def _validate_unchanged_order_data(self, original):
        immutable_fields = (
            "customer",
            "customer_name_snapshot",
            "customer_phone_snapshot",
            "delivery_address",
            "delivery_address_snapshot",
            "delivery_area",
            "delivery_fee",
            "payment_method",
            "order_datetime",
            "checkout_token",
            "payment_status",
            "currency",
            "subtotal",
            "total",
        )
        if any(self.get(field) != original.get(field) for field in immutable_fields):
            frappe.throw(
                "Submitted order details and totals cannot be changed.",
                frappe.ValidationError,
            )

        item_fields = (
            "product",
            "product_name_snapshot",
            "product_sku_snapshot",
            "product_category_snapshot",
            "quantity",
            "currency",
            "unit_price",
            "line_total",
        )
        current_items = tuple(
            tuple(item.get(field) for field in item_fields) for item in self.items
        )
        original_items = tuple(
            tuple(item.get(field) for field in item_fields)
            for item in original.items
        )
        if current_items != original_items:
            frappe.throw(
                "Submitted order products and prices cannot be changed.",
                frappe.ValidationError,
            )

    def _validate_status_transition(self, current_status):
        try:
            self.status = validate_order_status_transition(
                current_status, self.status
            )
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)
