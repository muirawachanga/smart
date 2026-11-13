import frappe
from frappe.model.document import Document
from frappe.utils import flt


class StockBalance(Document):
    def validate(self):
        if not getattr(frappe.flags, "updating_stock_balance", False):
            frappe.throw(
                "Stock balances can only be changed through inventory operations.",
                frappe.PermissionError,
            )
        self.quantity_on_hand = flt(self.quantity_on_hand)
        self.reserved_quantity = flt(self.reserved_quantity)
        if (
            not float(self.quantity_on_hand).is_integer()
            or not float(self.reserved_quantity).is_integer()
        ):
            frappe.throw("Stock quantities must be whole numbers.", frappe.ValidationError)
        if self.quantity_on_hand < 0 or self.reserved_quantity < 0:
            frappe.throw("Stock quantities cannot be negative.", frappe.ValidationError)
        if self.reserved_quantity > self.quantity_on_hand:
            frappe.throw(
                "Reserved stock cannot exceed quantity on hand.",
                frappe.ValidationError,
            )
        self.available_quantity = self.quantity_on_hand - self.reserved_quantity

    def on_trash(self):
        frappe.throw("Stock balances cannot be deleted.", frappe.PermissionError)

