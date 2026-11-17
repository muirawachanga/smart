import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class TestRoleDeskAccess(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.db = Mock()
        self.frappe.get_doc = Mock()
        spec = importlib.util.spec_from_file_location(
            "install_under_test", Path(__file__).parents[1] / "intelligent_ordering/install.py",
        )
        self.install = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": self.frappe}):
            spec.loader.exec_module(self.install)

    def test_existing_operational_roles_are_downgraded_through_native_lifecycle(self):
        documents = {}
        for role, expected in self.install.APP_ROLES.items():
            documents[role] = Mock(desk_access=1 if role != "Customer" else 0)
        self.frappe.db.exists.return_value = True
        self.frappe.get_doc.side_effect = lambda doctype, role: documents[role]
        self.install.ensure_roles()
        for role in ("Store Manager", "Order Manager", "Inventory Manager", "Delivery Manager",
                     "Customer Support", "Delivery Staff"):
            self.assertFalse(documents[role].desk_access)
            documents[role].save.assert_called_once_with(ignore_permissions=True)
        for role in ("Customer", "Business Admin", "Finance Manager"):
            documents[role].save.assert_not_called()
        self.assertNotIn("System Manager", documents)
        self.install.ensure_roles()
        for role in ("Store Manager", "Order Manager", "Inventory Manager", "Delivery Manager",
                     "Customer Support", "Delivery Staff"):
            self.assertEqual(documents[role].save.call_count, 1)

    def test_new_roles_use_website_or_desk_defaults_without_changing_permissions(self):
        self.frappe.db.exists.return_value = False
        self.install.ensure_roles()
        values = [call.args[0] for call in self.frappe.get_doc.call_args_list]
        self.assertEqual({value["role_name"] for value in values}, set(self.install.APP_ROLES))
        for value in values:
            self.assertEqual(value["desk_access"], value["role_name"] in {"Business Admin", "Finance Manager"})
        self.frappe.get_doc.return_value.insert.assert_called_with(ignore_permissions=True)

    def test_role_save_failure_is_not_suppressed(self):
        self.frappe.db.exists.return_value = True
        self.frappe.get_doc.return_value.desk_access = 1
        self.frappe.get_doc.return_value.save.side_effect = RuntimeError("Save failed")
        with self.assertRaisesRegex(RuntimeError, "Save failed"):
            self.install.ensure_roles()
