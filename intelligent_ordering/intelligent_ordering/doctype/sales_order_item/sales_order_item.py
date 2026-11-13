import frappe
from frappe.model.document import Document
from frappe.utils import flt


class SalesOrderItem(Document):
    def validate(self):
        quantity = flt(self.quantity)
        if quantity <= 0 or not quantity.is_integer():
            frappe.throw(
                "Quantity must be a positive whole number.",
                frappe.ValidationError,
            )
        if flt(self.unit_price) < 0:
            frappe.throw("Unit price cannot be negative.", frappe.ValidationError)
        if flt(self.line_total) < 0:
            frappe.throw("Line total cannot be negative.", frappe.ValidationError)
