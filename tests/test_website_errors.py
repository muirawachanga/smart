import unittest
from types import SimpleNamespace

from intelligent_ordering.utils.website_errors import customer_error_response


class Response:
    def __init__(self, status, mimetype="text/html"):
        self.status_code = status
        self.mimetype = mimetype
        self.headers = {}
        self.body = "private traceback"

    def set_data(self, data):
        self.body = data


class TestWebsiteErrors(unittest.TestCase):
    def test_customer_html_errors_keep_status_and_hide_details(self):
        for status in (403, 404, 500, 503):
            with self.subTest(status=status):
                response = Response(status)
                customer_error_response(SimpleNamespace(method="GET", path="/checkout"), response)
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private traceback", response.body)
                self.assertNotIn(str(status), response.body)
                self.assertIn('href="/"', response.body)
                self.assertIn('href="/contact"', response.body)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_staff_api_and_mutations_are_unchanged(self):
        for path, method, mimetype in (
            ("/dashboard/orders", "GET", "text/html"),
            ("/api/method/test", "GET", "application/json"),
            ("/checkout", "POST", "text/html"),
            ("/checkout", "GET", "application/json"),
        ):
            with self.subTest(path=path, method=method, mimetype=mimetype):
                response = Response(500, mimetype)
                customer_error_response(SimpleNamespace(method=method, path=path), response)
                self.assertEqual(response.body, "private traceback")


if __name__ == "__main__":
    unittest.main()
