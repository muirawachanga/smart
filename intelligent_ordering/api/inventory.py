import frappe

from intelligent_ordering.utils.inventory import (
    available_stock,
    record_stock,
    require_inventory_access,
    return_order_stock,
)
from intelligent_ordering.utils.validation import validate_pagination


@frappe.whitelist()
def get_dashboard(low_stock_threshold=5):
    require_inventory_access()
    threshold = _validate_threshold(low_stock_threshold)
    summary = frappe.db.sql(
        """
        SELECT
            (SELECT COUNT(*) FROM `tabProduct` WHERE enabled = 1) AS total_products,
            COALESCE(SUM(balance.quantity_on_hand), 0) AS total_stock,
            COALESCE(SUM(balance.available_quantity), 0) AS available_stock,
            COALESCE(SUM(balance.reserved_quantity), 0) AS reserved_stock
        FROM `tabStock Balance` AS balance
        INNER JOIN `tabStock Warehouse` AS warehouse
            ON warehouse.name = balance.warehouse AND warehouse.status = 'Active'
        """,
        as_dict=True,
    )[0]
    stock_status = frappe.db.sql(
        """
        SELECT
            SUM(CASE WHEN COALESCE(stock.available_quantity, 0) = 0 THEN 1 ELSE 0 END)
                AS out_of_stock_products,
            SUM(CASE WHEN stock.available_quantity > 0
                    AND stock.available_quantity <= %s THEN 1 ELSE 0 END)
                AS low_stock_products
        FROM `tabProduct` AS product
        LEFT JOIN (
            SELECT balance.product, SUM(balance.available_quantity) AS available_quantity
            FROM `tabStock Balance` AS balance
            INNER JOIN `tabStock Warehouse` AS warehouse
                ON warehouse.name = balance.warehouse AND warehouse.status = 'Active'
            GROUP BY balance.product
        ) AS stock ON stock.product = product.name
        WHERE product.enabled = 1
        """,
        threshold,
        as_dict=True,
    )[0]
    return {
        "summary": {
            "total_products": int(summary.total_products or 0),
            "total_stock": int(summary.total_stock or 0),
            "available_stock": int(summary.available_stock or 0),
            "reserved_stock": int(summary.reserved_stock or 0),
            "low_stock_products": int(stock_status.low_stock_products or 0),
            "out_of_stock_products": int(stock_status.out_of_stock_products or 0),
        },
        "low_stock_threshold": threshold,
        "recent_movements": _movement_rows(page_size=10),
    }


@frappe.whitelist()
def list_stock(search="", warehouse="", availability="all", page=1, page_size=20):
    require_inventory_access()
    if not isinstance(search, str) or len(search.strip()) > 100:
        frappe.throw("Search must be text no longer than 100 characters.", frappe.ValidationError)
    if not isinstance(warehouse, str) or len(warehouse) > 140:
        frappe.throw("Warehouse must be text.", frappe.ValidationError)
    if not isinstance(availability, str) or availability not in {
        "all", "available", "low", "out_of_stock"
    }:
        frappe.throw("Select a valid stock filter.", frappe.ValidationError)
    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    if warehouse and not frappe.db.exists(
        "Stock Warehouse", {"name": warehouse, "status": "Active"}
    ):
        frappe.throw("The selected warehouse is unavailable.", frappe.ValidationError)

    filters = ["product.enabled = 1"]
    values = [warehouse, warehouse]
    if warehouse:
        filters.append("warehouse.name = %s")
        values.append(warehouse)
    if search.strip():
        pattern = f"%{search.strip()}%"
        filters.append("(product.name LIKE %s OR product.sku LIKE %s OR product.product_name LIKE %s)")
        values.extend([pattern] * 3)
    if availability == "available":
        filters.append("COALESCE(balance.available_quantity, 0) > 0")
    elif availability == "low":
        filters.append("COALESCE(balance.available_quantity, 0) BETWEEN 1 AND 5")
    elif availability == "out_of_stock":
        filters.append("COALESCE(balance.available_quantity, 0) = 0")
    where_clause = " AND ".join(filters)
    rows = frappe.db.sql(
        f"""
        SELECT product.name AS product, product.sku, product.product_name,
            warehouse.name AS warehouse, warehouse.warehouse_name,
            COALESCE(balance.quantity_on_hand, 0) AS quantity_on_hand,
            COALESCE(balance.reserved_quantity, 0) AS reserved_quantity,
            COALESCE(balance.available_quantity, 0) AS available_quantity
        FROM `tabProduct` AS product
        CROSS JOIN (
            SELECT name, warehouse_name
            FROM `tabStock Warehouse`
            WHERE status = 'Active' AND (%s = '' OR name = %s)
        ) AS warehouse
        LEFT JOIN `tabStock Balance` AS balance
            ON balance.product = product.name AND balance.warehouse = warehouse.name
        WHERE {where_clause}
        ORDER BY product.product_name, warehouse.warehouse_name
        LIMIT %s OFFSET %s
        """,
        values + [page_size + 1, (page - 1) * page_size],
        as_dict=True,
    )
    has_more = len(rows) > page_size
    active_warehouses = frappe.get_all(
        "Stock Warehouse",
        filters={"status": "Active"},
        fields=["name", "warehouse_name"],
        order_by="warehouse_name asc",
    )
    return {
        "stock": rows[:page_size],
        "warehouses": active_warehouses,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


@frappe.whitelist()
def list_movements(product="", warehouse="", transaction_type="", page=1, page_size=20):
    require_inventory_access()
    for label, value in (("Product", product), ("Warehouse", warehouse)):
        if not isinstance(value, str) or len(value) > 140:
            frappe.throw(f"{label} filter is invalid.", frappe.ValidationError)
    if not isinstance(transaction_type, str) or (
        transaction_type and transaction_type not in {
            "Opening", "Receipt", "Issue", "Adjustment", "Reservation",
            "Release", "Dispatch", "Return",
        }
    ):
        frappe.throw("Select a valid transaction type.", frappe.ValidationError)
    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)

    filters = []
    values = []
    if product:
        filters.append(
            "(entry.product = %s OR product.sku = %s OR product.product_name LIKE %s)"
        )
        values.extend([product, product, f"%{product}%"])
    for field, value in (
        ("entry.warehouse", warehouse),
        ("entry.transaction_type", transaction_type),
    ):
        if value:
            filters.append(f"{field} = %s")
            values.append(value)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = _movement_rows(
        where_clause=where_clause,
        values=values,
        page_size=page_size + 1,
        offset=(page - 1) * page_size,
    )
    has_more = len(rows) > page_size
    return {
        "movements": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


@frappe.whitelist(methods=["POST"])
def adjust_stock(product, warehouse, transaction_type, quantity, remarks=""):
    return record_stock(product, warehouse, transaction_type, quantity, remarks)


@frappe.whitelist(methods=["POST"])
def record_order_return(order_name, product, warehouse, quantity, remarks=""):
    return return_order_stock(order_name, product, warehouse, quantity, remarks)


@frappe.whitelist()
def get_product_availability(product):
    if not isinstance(product, str) or not frappe.db.exists(
        "Product", {"name": product, "enabled": 1}
    ):
        frappe.throw("Select an enabled product.", frappe.ValidationError)
    quantity = available_stock(product)
    return {
        "product": product,
        "available_quantity": quantity,
        "stock_status": "In Stock" if quantity else "Out of Stock",
    }


def _validate_threshold(value):
    if isinstance(value, bool):
        frappe.throw("Low stock threshold must be a non-negative whole number.", frappe.ValidationError)
    try:
        threshold = int(value)
    except (TypeError, ValueError):
        frappe.throw("Low stock threshold must be a non-negative whole number.", frappe.ValidationError)
    if threshold < 0 or str(value).strip() != str(threshold):
        frappe.throw("Low stock threshold must be a non-negative whole number.", frappe.ValidationError)
    return threshold


def _movement_rows(where_clause="", values=None, page_size=10, offset=0):
    where_clause = f" {where_clause}" if where_clause else ""
    return frappe.db.sql(
        f"""
        SELECT entry.name, entry.product, product.sku, product.product_name,
            entry.warehouse, warehouse.warehouse_name, entry.transaction_type,
            entry.quantity, entry.quantity_change, entry.reserved_change,
            entry.reference_document, entry.reference_order,
            entry.transaction_date, entry.user_responsible, entry.remarks
        FROM `tabStock Ledger Entry` AS entry
        LEFT JOIN `tabProduct` AS product ON product.name = entry.product
        LEFT JOIN `tabStock Warehouse` AS warehouse ON warehouse.name = entry.warehouse
        {where_clause}
        ORDER BY entry.transaction_date DESC, entry.creation DESC
        LIMIT %s OFFSET %s
        """,
        (values or []) + [page_size, offset],
        as_dict=True,
    )
