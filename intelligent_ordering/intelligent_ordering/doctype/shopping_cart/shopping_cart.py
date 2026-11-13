from decimal import Decimal

import frappe
from frappe.model.document import Document

from intelligent_ordering.utils.cart import (
    MAX_CART_LINES,
    MAX_CART_QUANTITY,
    round_money,
)


class ShoppingCart(Document):
    def validate(self):
        if not self.user:
            frappe.throw("A cart must belong to a user.", frappe.ValidationError)
        if len(self.items) > MAX_CART_LINES:
            frappe.throw(
                f"A cart cannot contain more than {MAX_CART_LINES} items.",
                frappe.ValidationError,
            )

        if "Customer" in frappe.get_roles(frappe.session.user):
            if self.user != frappe.session.user:
                frappe.throw(
                    "You cannot modify another customer's cart.",
                    frappe.PermissionError,
                )

        products = set()
        currencies = set()
        total = Decimal("0.00")

        for item in self.items:
            if item.product in products:
                frappe.throw(
                    "A product may only appear once in a cart.",
                    frappe.ValidationError,
                )
            products.add(item.product)

            if isinstance(item.quantity, bool):
                frappe.throw("Quantity must be a positive whole number.")
            try:
                quantity = int(item.quantity)
            except (TypeError, ValueError):
                frappe.throw("Quantity must be a positive whole number.")
            if str(item.quantity).strip() != str(quantity) or quantity < 1:
                frappe.throw("Quantity must be a positive whole number.")
            if quantity > MAX_CART_QUANTITY:
                frappe.throw(
                    f"Quantity must not exceed {MAX_CART_QUANTITY}.",
                    frappe.ValidationError,
                )

            product = frappe.db.get_value(
                "Product",
                {"name": item.product, "enabled": 1},
                ["price", "currency", "category"],
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
                    "The cart contains an unavailable product.",
                    frappe.ValidationError,
                )
            previous = self.get_doc_before_save()
            previous_quantity = 0
            if previous:
                previous_quantity = next(
                    (
                        int(row.quantity)
                        for row in previous.items
                        if row.product == item.product
                    ),
                    0,
                )
            from intelligent_ordering.utils.inventory import available_stock

            if (
                quantity > previous_quantity
                and quantity > available_stock(item.product)
            ):
                frappe.throw(
                    "Cart quantity cannot exceed available stock.",
                    frappe.ValidationError,
                )

            currency = (product.currency or "KES").upper()
            currencies.add(currency)
            if len(currencies) > 1:
                frappe.throw(
                    "Products in one cart must use the same currency.",
                    frappe.ValidationError,
                )

            try:
                unit_price = round_money(product.price)
                subtotal = round_money(unit_price * quantity)
            except ValueError as error:
                frappe.throw(str(error), frappe.ValidationError)
            item.quantity = quantity
            item.currency = currency
            item.unit_price = unit_price
            item.subtotal = subtotal
            total += Decimal(str(subtotal))

        self.currency = next(iter(currencies), "KES")
        try:
            self.total = round_money(total)
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)
