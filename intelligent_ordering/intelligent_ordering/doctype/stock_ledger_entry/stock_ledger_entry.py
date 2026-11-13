import frappe
from frappe.model.document import Document
from frappe.utils import flt


class StockLedgerEntry(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("Stock ledger entries are immutable.", frappe.PermissionError)
        if not getattr(frappe.flags, "creating_stock_ledger_entry", False):
            frappe.throw(
                "Stock movements must be recorded through inventory operations.",
                frappe.PermissionError,
            )
        if flt(self.quantity_change) == 0 and flt(self.reserved_change) == 0:
            frappe.throw("A stock movement must change a quantity.", frappe.ValidationError)

    def on_trash(self):
        frappe.throw("Stock ledger entries cannot be deleted.", frappe.PermissionError)
