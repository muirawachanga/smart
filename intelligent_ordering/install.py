import frappe


APP_ROLES = {
    "Customer": False,
    "Business Admin": True,
    "Store Manager": False,
    "Finance Manager": True,
    "Delivery Manager": False,
    "Order Manager": False,
    "Inventory Manager": False,
    "Customer Support": False,
    "Delivery Staff": False,
}


def after_install():
    ensure_roles()
    ensure_business_fields()
    ensure_policy_indexes()
    ensure_policy_drafts()


def after_migrate():
    ensure_roles()
    ensure_business_fields()
    ensure_inventory_indexes()
    ensure_policy_indexes()
    ensure_policy_drafts()


def ensure_business_fields():
    from intelligent_ordering.utils.business import ensure_business_fields as create_fields

    create_fields()


def ensure_policy_drafts():
    from intelligent_ordering.api.policies import ensure_policy_drafts as create_drafts

    create_drafts()


def ensure_policy_indexes():
    if not frappe.db.table_exists("SmartO Policy Version"):
        return
    index_name = "uniq_smarto_policy_kind_version"
    if not frappe.db.sql("SHOW INDEX FROM `tabSmartO Policy Version` WHERE Key_name = %s", index_name):
        frappe.db.add_unique("SmartO Policy Version", ["policy_type", "version"], index_name)


def ensure_roles():
    for role_name, desk_access in APP_ROLES.items():
        if frappe.db.exists("Role", role_name):
            role = frappe.get_doc("Role", role_name)
            if bool(role.desk_access) != desk_access:
                role.desk_access = desk_access
                # Frappe recalculates user types and revokes sessions on type changes.
                role.save(ignore_permissions=True)
            continue

        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": desk_access,
            }
        ).insert(ignore_permissions=True)


def ensure_inventory_indexes():
    if not frappe.db.table_exists("Stock Balance"):
        return
    index_name = "uniq_stock_balance_product_warehouse"
    if frappe.db.sql(
        "SHOW INDEX FROM `tabStock Balance` WHERE Key_name = %s",
        index_name,
    ):
        return
    frappe.db.add_unique(
        "Stock Balance",
        ["product", "warehouse"],
        index_name,
    )
