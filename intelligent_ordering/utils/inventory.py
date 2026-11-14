import hashlib
import re

import frappe
from frappe.utils import flt, now_datetime


INVENTORY_ROLES = {"System Manager", "Business Admin", "Inventory Manager"}
MAX_STOCK_QUANTITY = 2_147_483_647


def require_inventory_access():
    if (
        frappe.session.user != "Administrator"
        and not INVENTORY_ROLES.intersection(frappe.get_roles(frappe.session.user))
    ):
        frappe.throw("Inventory management access is required.", frappe.PermissionError)


def validate_quantity(value, allow_negative=False):
    if isinstance(value, bool):
        frappe.throw("Quantity must be a non-zero whole number.", frappe.ValidationError)
    if isinstance(value, int):
        quantity = value
    elif isinstance(value, float) and value.is_integer():
        quantity = int(value)
    elif isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value.strip()):
        quantity = int(value.strip())
    else:
        frappe.throw("Quantity must be a non-zero whole number.", frappe.ValidationError)
    if quantity == 0 or (quantity < 0 and not allow_negative):
        frappe.throw("Quantity must be a non-zero whole number.", frappe.ValidationError)
    if abs(quantity) > MAX_STOCK_QUANTITY:
        frappe.throw(
            f"Quantity must not exceed {MAX_STOCK_QUANTITY}.",
            frappe.ValidationError,
        )
    return quantity


def available_stock(product):
    row = frappe.db.sql(
        """
        SELECT COALESCE(SUM(balance.available_quantity), 0) AS available_quantity
        FROM `tabStock Balance` AS balance
        INNER JOIN `tabStock Warehouse` AS warehouse
            ON warehouse.name = balance.warehouse AND warehouse.status = 'Active'
        WHERE balance.product = %s
        """,
        product,
        as_dict=True,
    )
    return int(flt(row[0].available_quantity)) if row else 0


def validate_checkout_stock(items):
    """Check current stock under the same product and balance locks as inventory changes."""
    _lock_products(sorted({item["product"] for item in items}))
    for item in sorted(items, key=lambda row: row["product"]):
        balances = _get_product_balances(item["product"], lock=True)
        available = sum(int(flt(balance.available_quantity)) for balance in balances)
        if item["quantity"] > available:
            frappe.throw(
                f"Insufficient available stock for {item['product']}.",
                frappe.ValidationError,
            )


def handle_order_status_change(doc, method=None):
    original = doc.get_doc_before_save()
    if not original or original.status == doc.status:
        return

    if doc.status == "Confirmed":
        reserve_order_stock(doc)
    elif doc.status == "Ready for Delivery":
        dispatch_order_stock(doc)
    elif doc.status == "Cancelled":
        cancel_order_stock(doc)


def reserve_order_stock(order):
    products = sorted({item.product for item in order.items})
    _lock_products(products)

    for item in sorted(order.items, key=lambda row: row.product):
        existing = frappe.db.get_value(
            "Stock Ledger Entry",
            {
                "reference_order": order.name,
                "product": item.product,
                "transaction_type": "Reservation",
            },
            "name",
        )
        if existing:
            continue

        quantity = validate_quantity(item.quantity)
        balances = _get_product_balances(item.product, lock=True)
        remaining = quantity
        for balance in balances:
            if not balance.available_quantity:
                continue
            allocated = min(remaining, int(balance.available_quantity))
            _update_balance(
                balance,
                balance.quantity_on_hand,
                balance.reserved_quantity + allocated,
            )
            _record_ledger(
                product=item.product,
                warehouse=balance.warehouse,
                transaction_type="Reservation",
                quantity=allocated,
                quantity_change=0,
                reserved_change=allocated,
                reference_order=order.name,
                reference_document=order.name,
                idempotency_key=_movement_key(
                    order.name, "reserve", item.product, balance.warehouse
                ),
                remarks=f"Reserved for order {order.name}",
            )
            remaining -= allocated
            if not remaining:
                break

        if remaining:
            frappe.throw(
                f"Insufficient available stock for {item.product}.",
                frappe.ValidationError,
            )


def dispatch_order_stock(order):
    products = sorted({item.product for item in order.items})
    _lock_products(products)

    for item in sorted(order.items, key=lambda row: row.product):
        existing_dispatch = frappe.db.get_value(
            "Stock Ledger Entry",
            {
                "reference_order": order.name,
                "product": item.product,
                "transaction_type": "Dispatch",
            },
            "name",
        )
        if existing_dispatch:
            continue

        reservations = frappe.db.sql(
            """
            SELECT warehouse,
                SUM(reserved_change) AS reserved
            FROM `tabStock Ledger Entry`
            WHERE reference_order = %s AND product = %s AND warehouse IS NOT NULL
            GROUP BY warehouse
            HAVING SUM(reserved_change) > 0
            ORDER BY warehouse
            """,
            (order.name, item.product),
            as_dict=True,
        )
        to_dispatch = validate_quantity(item.quantity)
        for reservation in reservations:
            balance = _get_balance_locked(item.product, reservation.warehouse)
            quantity = min(to_dispatch, int(flt(reservation.reserved)))
            if not quantity:
                continue
            if quantity > balance.reserved_quantity or quantity > balance.quantity_on_hand:
                frappe.throw(
                    "Reserved stock no longer matches the order.",
                    frappe.ValidationError,
                )
            _update_balance(
                balance,
                balance.quantity_on_hand - quantity,
                balance.reserved_quantity - quantity,
            )
            _record_ledger(
                product=item.product,
                warehouse=reservation.warehouse,
                transaction_type="Dispatch",
                quantity=quantity,
                quantity_change=-quantity,
                reserved_change=-quantity,
                reference_order=order.name,
                reference_document=order.name,
                idempotency_key=_movement_key(
                    order.name, "dispatch", item.product, reservation.warehouse
                ),
                remarks=f"Dispatched for order {order.name}",
            )
            to_dispatch -= quantity
            if not to_dispatch:
                break
        if to_dispatch:
            frappe.throw(
                f"Order {order.name} has no complete stock reservation for {item.product}.",
                frappe.ValidationError,
            )


def cancel_order_stock(order):
    products = sorted({item.product for item in order.items})
    _lock_products(products)
    dispatched = _order_movement_quantities(order.name, "Dispatch")
    returned = _order_movement_quantities(order.name, "Return")

    for item in sorted(order.items, key=lambda row: row.product):
        for warehouse, quantity in _remaining_reservations(order.name, item.product).items():
            balance = _get_balance_locked(item.product, warehouse)
            if quantity > balance.reserved_quantity:
                frappe.throw("Reserved stock is inconsistent.", frappe.ValidationError)
            _update_balance(
                balance,
                balance.quantity_on_hand,
                balance.reserved_quantity - quantity,
            )
            _record_ledger(
                product=item.product,
                warehouse=warehouse,
                transaction_type="Release",
                quantity=quantity,
                quantity_change=0,
                reserved_change=-quantity,
                reference_order=order.name,
                reference_document=order.name,
                idempotency_key=_movement_key(
                    order.name, "release", item.product, warehouse
                ),
                remarks=f"Released reservation for cancelled order {order.name}",
            )
        if dispatched.get(item.product, 0) > returned.get(item.product, 0):
            frappe.throw(
                "Dispatched items must be returned through inventory before cancelling this order.",
                frappe.ValidationError,
            )


def return_order_stock(order_name, product, warehouse, quantity, remarks=""):
    require_inventory_access()
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (order_name, product, warehouse)
    ):
        frappe.throw("Select a valid order, product, and warehouse.", frappe.ValidationError)
    quantity = validate_quantity(quantity)
    if not isinstance(remarks, str) or len(remarks.strip()) > 500:
        frappe.throw("Remarks must be text no longer than 500 characters.", frappe.ValidationError)
    frappe.db.sql(
        "SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE",
        order_name,
    )
    order = frappe.get_doc("Sales Order", order_name)
    order.check_permission("read")
    if order.status not in {"Ready for Delivery", "Completed"}:
        frappe.throw(
            "Stock can only be returned for a dispatched order.",
            frappe.ValidationError,
        )
    if product not in {item.product for item in order.items}:
        frappe.throw("The product is not part of this order.", frappe.ValidationError)

    _lock_products([product])
    _require_active_warehouse(warehouse)
    balance = _get_balance_locked(product, warehouse)
    dispatched = _ledger_quantity(order_name, product, warehouse, "Dispatch")
    already_returned = _ledger_quantity(order_name, product, warehouse, "Return")
    if quantity > dispatched - already_returned:
        frappe.throw(
            "Return quantity exceeds the dispatched quantity not yet returned.",
            frappe.ValidationError,
        )

    _update_balance(
        balance,
        balance.quantity_on_hand + quantity,
        balance.reserved_quantity,
    )
    return _record_ledger(
        product=product,
        warehouse=warehouse,
        transaction_type="Return",
        quantity=quantity,
        quantity_change=quantity,
        reserved_change=0,
        reference_order=order.name,
        reference_document=order.name,
        idempotency_key=None,
        remarks=remarks.strip() or f"Return for order {order.name}",
    )


def record_stock(product, warehouse, transaction_type, quantity, remarks=""):
    require_inventory_access()
    if not isinstance(transaction_type, str) or transaction_type not in {
        "Opening", "Receipt", "Adjustment"
    }:
        frappe.throw("Select Opening, Receipt, or Adjustment.", frappe.ValidationError)
    if not isinstance(product, str) or not product.strip():
        frappe.throw("Select a valid product.", frappe.ValidationError)
    if not isinstance(warehouse, str) or not warehouse.strip():
        frappe.throw("Select an active stock warehouse.", frappe.ValidationError)
    quantity = validate_quantity(quantity, allow_negative=transaction_type == "Adjustment")
    if not isinstance(remarks, str) or len(remarks.strip()) > 500:
        frappe.throw("Remarks must be text no longer than 500 characters.", frappe.ValidationError)
    _lock_products([product])
    _require_active_warehouse(warehouse)
    balance = _get_balance_locked(product, warehouse)

    if transaction_type == "Opening":
        if balance.quantity_on_hand or frappe.db.exists(
            "Stock Ledger Entry", {"product": product, "warehouse": warehouse}
        ):
            frappe.throw(
                "Opening stock can only be recorded once for an empty warehouse balance.",
                frappe.ValidationError,
            )
        on_hand_change = quantity
    else:
        on_hand_change = quantity

    new_on_hand = balance.quantity_on_hand + on_hand_change
    if new_on_hand < balance.reserved_quantity:
        frappe.throw(
            "Stock adjustment cannot reduce stock below the reserved quantity.",
            frappe.ValidationError,
        )
    _update_balance(balance, new_on_hand, balance.reserved_quantity)
    return _record_ledger(
        product=product,
        warehouse=warehouse,
        transaction_type=transaction_type,
        quantity=abs(quantity),
        quantity_change=on_hand_change,
        reserved_change=0,
        reference_order=None,
        reference_document=None,
        idempotency_key=None,
        remarks=remarks.strip(),
    )


def _lock_products(products):
    for product in products:
        row = frappe.db.sql(
            "SELECT name FROM `tabProduct` WHERE name = %s FOR UPDATE",
            product,
        )
        if not row:
            frappe.throw("Select a valid product.", frappe.ValidationError)


def _require_active_warehouse(warehouse):
    rows = frappe.db.sql(
        "SELECT status FROM `tabStock Warehouse` WHERE name = %s FOR UPDATE",
        warehouse,
    )
    if not rows or rows[0][0] != "Active":
        frappe.throw("Select an active stock warehouse.", frappe.ValidationError)


def _get_product_balances(product, lock=False):
    rows = frappe.db.sql(
        """
        SELECT balance.name, balance.product, balance.warehouse,
            balance.quantity_on_hand, balance.reserved_quantity,
            balance.available_quantity
        FROM `tabStock Balance` AS balance
        INNER JOIN `tabStock Warehouse` AS warehouse
            ON warehouse.name = balance.warehouse AND warehouse.status = 'Active'
        WHERE balance.product = %s
        ORDER BY balance.warehouse
        """ + (" FOR UPDATE" if lock else ""),
        product,
        as_dict=True,
    )
    return rows


def _get_balance_locked(product, warehouse):
    _require_active_warehouse(warehouse)
    rows = frappe.db.sql(
        """
        SELECT name, product, warehouse, quantity_on_hand,
            reserved_quantity, available_quantity
        FROM `tabStock Balance`
        WHERE product = %s AND warehouse = %s
        FOR UPDATE
        """,
        (product, warehouse),
        as_dict=True,
    )
    if rows:
        return rows[0]

    was_updating = getattr(frappe.flags, "updating_stock_balance", False)
    frappe.flags.updating_stock_balance = True
    try:
        balance = frappe.get_doc(
            {
                "doctype": "Stock Balance",
                "product": product,
                "warehouse": warehouse,
                "quantity_on_hand": 0,
                "reserved_quantity": 0,
                "available_quantity": 0,
            }
        ).insert(ignore_permissions=True)
    finally:
        frappe.flags.updating_stock_balance = was_updating
    return frappe._dict(
        {
            "name": balance.name,
            "product": product,
            "warehouse": warehouse,
            "quantity_on_hand": 0,
            "reserved_quantity": 0,
            "available_quantity": 0,
        }
    )


def _update_balance(balance, quantity_on_hand, reserved_quantity):
    if quantity_on_hand < 0 or reserved_quantity < 0:
        frappe.throw("Stock quantities cannot be negative.", frappe.ValidationError)
    if quantity_on_hand > MAX_STOCK_QUANTITY or reserved_quantity > MAX_STOCK_QUANTITY:
        frappe.throw(
            f"Stock quantities must not exceed {MAX_STOCK_QUANTITY}.",
            frappe.ValidationError,
        )
    if reserved_quantity > quantity_on_hand:
        frappe.throw(
            "Reserved stock cannot exceed quantity on hand.",
            frappe.ValidationError,
        )
    frappe.db.sql(
        """
        UPDATE `tabStock Balance`
        SET quantity_on_hand = %s, reserved_quantity = %s,
            available_quantity = %s, modified = %s, modified_by = %s
        WHERE name = %s
        """,
        (
            quantity_on_hand,
            reserved_quantity,
            quantity_on_hand - reserved_quantity,
            now_datetime(),
            frappe.session.user,
            balance.name,
        ),
    )
    balance.quantity_on_hand = quantity_on_hand
    balance.reserved_quantity = reserved_quantity
    balance.available_quantity = quantity_on_hand - reserved_quantity


def _record_ledger(
    product,
    warehouse,
    transaction_type,
    quantity,
    quantity_change,
    reserved_change,
    reference_order,
    reference_document,
    idempotency_key,
    remarks,
):
    existing = (
        frappe.db.get_value(
            "Stock Ledger Entry", {"idempotency_key": idempotency_key}, "name"
        )
        if idempotency_key
        else None
    )
    if existing:
        return frappe.get_doc("Stock Ledger Entry", existing)
    was_creating = getattr(frappe.flags, "creating_stock_ledger_entry", False)
    frappe.flags.creating_stock_ledger_entry = True
    try:
        return frappe.get_doc(
            {
                "doctype": "Stock Ledger Entry",
                "product": product,
                "warehouse": warehouse,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "quantity_change": quantity_change,
                "reserved_change": reserved_change,
                "reference_order": reference_order,
                "reference_document": reference_document,
                "transaction_date": now_datetime(),
                "user_responsible": frappe.session.user,
                "remarks": remarks,
                "idempotency_key": idempotency_key,
            }
        ).insert(ignore_permissions=True)
    finally:
        frappe.flags.creating_stock_ledger_entry = was_creating


def _remaining_reservations(order_name, product):
    rows = frappe.db.sql(
        """
        SELECT warehouse, SUM(reserved_change) AS quantity
        FROM `tabStock Ledger Entry`
        WHERE reference_order = %s AND product = %s AND warehouse IS NOT NULL
        GROUP BY warehouse
        HAVING SUM(reserved_change) > 0
        """,
        (order_name, product),
        as_dict=True,
    )
    return {row.warehouse: int(flt(row.quantity)) for row in rows}


def _order_movement_quantities(order_name, transaction_type):
    rows = frappe.db.sql(
        """
        SELECT product, SUM(quantity) AS quantity
        FROM `tabStock Ledger Entry`
        WHERE reference_order = %s AND transaction_type = %s
        GROUP BY product
        """,
        (order_name, transaction_type),
        as_dict=True,
    )
    return {row.product: int(flt(row.quantity)) for row in rows}


def _ledger_quantity(order_name, product, warehouse, transaction_type):
    row = frappe.db.sql(
        """
        SELECT COALESCE(SUM(quantity), 0) AS quantity
        FROM `tabStock Ledger Entry`
        WHERE reference_order = %s AND product = %s
            AND warehouse = %s AND transaction_type = %s
        """,
        (order_name, product, warehouse, transaction_type),
        as_dict=True,
    )
    return int(flt(row[0].quantity)) if row else 0


def _movement_key(order_name, action, product, warehouse):
    source = "\0".join((order_name, action, product, warehouse))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()

