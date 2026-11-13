import frappe
from frappe.model.document import Document


class FulfillmentNotification(Document):
    def validate(self):
        if not getattr(frappe.flags, "preparing_fulfillment_notification", False):
            frappe.throw("Notification events are managed by fulfillment workflows.", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Notification history cannot be deleted.", frappe.PermissionError)

    def before_rename(self, *args):
        frappe.throw("Notification history cannot be renamed.", frappe.PermissionError)
