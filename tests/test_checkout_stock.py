import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class StockError(Exception):
    pass


def load_inventory():
    frappe = types.ModuleType("frappe")
    frappe.ValidationError = StockError
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(StockError(message)))
    utils = types.ModuleType("frappe.utils")
    utils.flt = float
    utils.now_datetime = Mock()
    spec = importlib.util.spec_from_file_location(
        "checkout_inventory_under_test",
        Path(__file__).parents[1] / "intelligent_ordering/utils/inventory.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
        spec.loader.exec_module(module)
    return module


class TestCheckoutStock(unittest.TestCase):
    def test_stock_is_checked_under_inventory_locks(self):
        inventory = load_inventory()
        items = [{"product": "B", "quantity": 2}, {"product": "A", "quantity": 3}]
        with patch.object(inventory, "_lock_products") as locks, patch.object(
            inventory, "_get_product_balances",
            side_effect=[
                [types.SimpleNamespace(available_quantity=3)],
                [types.SimpleNamespace(available_quantity=1), types.SimpleNamespace(available_quantity=1)],
            ],
        ) as balances:
            inventory.validate_checkout_stock(items)
        locks.assert_called_once_with(["A", "B"])
        self.assertEqual(balances.call_args_list[0].kwargs, {"lock": True})
        self.assertEqual(balances.call_args_list[1].kwargs, {"lock": True})

    def test_insufficient_stock_is_rejected(self):
        inventory = load_inventory()
        with patch.object(inventory, "_lock_products"), patch.object(
            inventory, "_get_product_balances", return_value=[
                types.SimpleNamespace(available_quantity=1)
            ],
        ), self.assertRaisesRegex(StockError, "Insufficient"):
            inventory.validate_checkout_stock([{"product": "A", "quantity": 2}])


if __name__ == "__main__":
    unittest.main()
