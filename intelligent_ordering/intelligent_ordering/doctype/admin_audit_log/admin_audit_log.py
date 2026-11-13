import frappe
from frappe.model.document import Document


class AdminAuditLog(Document):
    def validate(self):
        if not getattr(frappe.flags, "creating_admin_audit_log", False):
            frappe.throw("Audit records are written only by application workflows.", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Audit records cannot be deleted.", frappe.PermissionError)

    def before_rename(self, *args):
        frappe.throw("Audit records cannot be renamed.", frappe.PermissionError)
