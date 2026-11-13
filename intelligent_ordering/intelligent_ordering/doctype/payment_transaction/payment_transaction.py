import frappe
from frappe.model.document import Document


class PaymentTransaction(Document):
    def validate(self):
        if not getattr(frappe.flags, "processing_mpesa", False):
            frappe.throw(
                "Payments can only be updated by verified payment workflows.",
                frappe.PermissionError,
            )

    def on_trash(self):
        frappe.throw("Payment history cannot be deleted.", frappe.PermissionError)

    def before_rename(self, *args):
        frappe.throw("Payment history cannot be renamed.", frappe.PermissionError)
