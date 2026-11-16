from datetime import date, timedelta


ORDER_STATUSES = {
    "Pending", "Confirmed", "Processing", "Ready for Delivery", "Completed", "Cancelled",
}
PAYMENT_STATUSES = {
    "Initiated", "Pending", "Successful", "Failed", "Cancelled", "Reversed",
}
PERIOD_FORMATS = {
    "daily": "%Y-%m-%d",
    "weekly": "%x-W%v",
    "monthly": "%Y-%m",
    "yearly": "%Y",
}
REPORTS = {"sales", "orders", "customers", "payments", "inventory", "deliveries"}


def parse_report_filters(
    start_date="", end_date="", product="", category="",
    order_status="", payment_status="",
):
    start = parse_date(start_date, "Start date") if start_date else None
    end = parse_date(end_date, "End date") if end_date else None
    if start and end and start > end:
        raise ValueError("Start date must not be after end date.")
    if not isinstance(product, str) or len(product) > 140:
        raise ValueError("Product filter is invalid.")
    if not isinstance(category, str) or len(category) > 140:
        raise ValueError("Category filter is invalid.")
    if not isinstance(order_status, str) or (
        order_status and order_status not in ORDER_STATUSES
    ):
        raise ValueError("Select a valid order status.")
    if not isinstance(payment_status, str) or (
        payment_status and payment_status not in PAYMENT_STATUSES
    ):
        raise ValueError("Select a valid payment status.")
    return {
        "start_date": start.isoformat() if start else "",
        "end_date": end.isoformat() if end else "",
        "product": product.strip(),
        "category": category.strip(),
        "order_status": order_status,
        "payment_status": payment_status,
    }


def parse_date(value, label="Date"):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{label} must use YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must use YYYY-MM-DD format.") from None


def report_filename(report, file_format, start_date="", end_date=""):
    if not isinstance(report, str) or report not in REPORTS:
        raise ValueError("Select a supported report.")
    if not isinstance(file_format, str) or file_format not in {"csv", "xlsx"}:
        raise ValueError("Select CSV or Excel format.")
    suffix = f"-{start_date}-to-{end_date}" if start_date or end_date else ""
    return f"{report}-report{suffix}.{file_format}"


def spreadsheet_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        import json

        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def forecast_daily(observations, first_day, last_day, horizon=7):
    """Fit a weekday-seasonal linear trend to complete daily observations."""
    first_day = max(first_day, last_day - timedelta(days=55))
    days = (last_day - first_day).days + 1
    values = [float(observations.get(first_day + timedelta(days=index), 0)) for index in range(max(days, 0))]
    active_days = sum(value > 0 for value in values)
    if days < 28 or active_days < 5:
        return {"available": False, "history_days": max(days, 0), "active_days": active_days, "forecast": []}
    center = (days - 1) / 2
    mean = sum(values) / days
    denominator = sum((index - center) ** 2 for index in range(days))
    slope = sum((index - center) * (value - mean) for index, value in enumerate(values)) / denominator
    seasonal = {day: [] for day in range(7)}
    for index, value in enumerate(values):
        weekday = (first_day + timedelta(days=index)).weekday()
        seasonal[weekday].append(value - slope * (index - center))
    forecast = []
    for offset in range(1, horizon + 1):
        target = last_day + timedelta(days=offset)
        baseline = sum(seasonal[target.weekday()]) / len(seasonal[target.weekday()])
        estimate = max(0, baseline + slope * (days - 1 + offset - center))
        forecast.append({"date": target.isoformat(), "estimate": round(estimate, 2)})
    return {"available": True, "history_days": days, "active_days": active_days, "forecast": forecast}


def build_order_filter_sql(filters, order_alias="o", item_alias="oi"):
    clauses = []
    values = []
    if filters["start_date"]:
        clauses.append(f"DATE({order_alias}.order_datetime) >= %s")
        values.append(filters["start_date"])
    if filters["end_date"]:
        clauses.append(f"DATE({order_alias}.order_datetime) <= %s")
        values.append(filters["end_date"])
    if filters["order_status"]:
        clauses.append(f"{order_alias}.status = %s")
        values.append(filters["order_status"])
    if filters["product"]:
        clauses.append(
            f"EXISTS (SELECT 1 FROM `tabSales Order Item` {item_alias} "
            f"WHERE {item_alias}.parent = {order_alias}.name "
            f"AND {item_alias}.product = %s)"
        )
        values.append(filters["product"])
    if filters["category"]:
        clauses.append(
            f"EXISTS (SELECT 1 FROM `tabSales Order Item` {item_alias} "
            f"WHERE {item_alias}.parent = {order_alias}.name "
            f"AND {item_alias}.product_category_snapshot = %s)"
        )
        values.append(filters["category"])
    if filters["payment_status"]:
        clauses.append(
            f"EXISTS (SELECT 1 FROM `tabPayment Transaction` filter_payment "
            f"WHERE filter_payment.`order` = {order_alias}.name "
            "AND filter_payment.status = %s)"
        )
        values.append(filters["payment_status"])
    return (" AND ".join(clauses) if clauses else "1=1", values)


def build_payment_filter_sql(filters, payment_alias="t", order_alias="o"):
    clauses = [f"{payment_alias}.status = 'Successful'"]
    values = []
    if filters["start_date"]:
        clauses.append(f"DATE({payment_alias}.transaction_date) >= %s")
        values.append(filters["start_date"])
    if filters["end_date"]:
        clauses.append(f"DATE({payment_alias}.transaction_date) <= %s")
        values.append(filters["end_date"])
    if filters["order_status"]:
        clauses.append(f"{order_alias}.status = %s")
        values.append(filters["order_status"])
    if filters["payment_status"]:
        clauses.append(f"{payment_alias}.status = %s")
        values.append(filters["payment_status"])
    if filters["product"]:
        clauses.append(
            f"EXISTS (SELECT 1 FROM `tabSales Order Item` filter_item "
            f"WHERE filter_item.parent = {order_alias}.name "
            "AND filter_item.product = %s)"
        )
        values.append(filters["product"])
    if filters["category"]:
        clauses.append(
            f"EXISTS (SELECT 1 FROM `tabSales Order Item` filter_item "
            f"WHERE filter_item.parent = {order_alias}.name "
            "AND filter_item.product_category_snapshot = %s)"
        )
        values.append(filters["category"])
    return " AND ".join(clauses), values
