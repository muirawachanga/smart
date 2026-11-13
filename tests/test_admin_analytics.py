import unittest

from intelligent_ordering.utils.admin_analytics import (
    PERIOD_FORMATS,
    build_order_filter_sql,
    build_payment_filter_sql,
    parse_report_filters,
    parse_date,
    report_filename,
    spreadsheet_cell,
)


class TestAdministrationAnalytics(unittest.TestCase):
    def test_date_range_validation_and_normalization(self):
        filters = parse_report_filters(
            start_date="2026-01-02", end_date="2026-02-03",
            product=" SKU-1 ", category=" Grocery ",
            order_status="Completed", payment_status="Successful",
        )
        self.assertEqual(filters, {
            "start_date": "2026-01-02", "end_date": "2026-02-03",
            "product": "SKU-1", "category": "Grocery",
            "order_status": "Completed", "payment_status": "Successful",
        })
        for value in ("2026-02-30", "2026-1-01", "today", []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_date(value)
        with self.assertRaisesRegex(ValueError, "after"):
            parse_report_filters(start_date="2026-02-01", end_date="2026-01-31")

    def test_status_and_identifier_filters_are_validated(self):
        for field, value in (
            ("order_status", "Unknown"),
            ("payment_status", "Paid"),
            ("product", "P" * 141),
            ("category", None),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_report_filters(**{field: value})

    def test_periods_cover_daily_weekly_monthly_and_yearly(self):
        self.assertEqual(set(PERIOD_FORMATS), {"daily", "weekly", "monthly", "yearly"})
        self.assertIn("%v", PERIOD_FORMATS["weekly"])
        self.assertIn("%Y", PERIOD_FORMATS["yearly"])

    def test_filter_sql_uses_bound_values_and_order_time_category_snapshot(self):
        filters = parse_report_filters(
            start_date="2026-01-01", end_date="2026-01-31",
            product="SKU-1", category="Fresh",
            order_status="Completed", payment_status="Successful",
        )
        sql, values = build_order_filter_sql(filters)
        self.assertEqual(values, [
            "2026-01-01", "2026-01-31", "Completed",
            "SKU-1", "Fresh", "Successful",
        ])
        self.assertIn("product_category_snapshot = %s", sql)
        self.assertNotIn("Fresh", sql)
        payment_sql, payment_values = build_payment_filter_sql(filters)
        self.assertIn("status = 'Successful'", payment_sql)
        self.assertEqual(payment_values, [
            "2026-01-01", "2026-01-31", "Completed", "Successful",
            "SKU-1", "Fresh",
        ])
        self.assertNotIn("SKU-1", payment_sql)

    def test_report_formats_and_formula_injection_protection(self):
        self.assertEqual(
            report_filename("sales", "csv", "2026-01-01", "2026-01-31"),
            "sales-report-2026-01-01-to-2026-01-31.csv",
        )
        for report, file_format in (("users", "csv"), ("sales", "ods")):
            with self.subTest(report=report, file_format=file_format), self.assertRaises(ValueError):
                report_filename(report, file_format)
        for dangerous in ("=SUM(A1:A2)", "+cmd", "-2+3", "@command", "\tformula", "\rformula"):
            with self.subTest(value=dangerous):
                self.assertEqual(spreadsheet_cell(dangerous), "'" + dangerous)
        self.assertEqual(spreadsheet_cell(None), "")
        self.assertEqual(spreadsheet_cell(123), 123)


if __name__ == "__main__":
    unittest.main()
