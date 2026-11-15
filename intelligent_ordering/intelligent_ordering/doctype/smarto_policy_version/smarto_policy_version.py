import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SmartOPolicyVersion(Document):
    def validate(self):
        previous = self.get_doc_before_save()
        if previous and previous.status == "Published":
            frappe.throw("Published policies are immutable. Create a new draft version.", frappe.ValidationError)
        if not self.version or not self.version.strip():
            frappe.throw("A policy version is required.", frappe.ValidationError)
        self.version = self.version.strip()
        if not self.content or not self.content.strip():
            frappe.throw("Policy content is required.", frappe.ValidationError)
        if frappe.db.exists("SmartO Policy Version", {
            "policy_type": self.policy_type, "version": self.version,
            "name": ["!=", self.name or ""],
        }):
            frappe.throw("This policy version already exists.", frappe.ValidationError)
        if self.status == "Published":
            if self.version == "review-draft":
                frappe.throw("Replace the review draft with approved content and a new version before publishing.",
                             frappe.ValidationError)
            self.published_at = now_datetime()
        else:
            self.published_at = None

    def on_trash(self):
        if self.status == "Published":
            frappe.throw("Published policies must be retained for acceptance audits.", frappe.ValidationError)
