import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from intelligent_ordering.utils.delivery import distance_km, nearest_delivery_route, validate_coordinates
from test_delivery_workflow import DeliveryError, load_services


class Row(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def delivery(name, latitude, longitude, **values):
    return Row({
        "name": name, "order": f"SO-{name}", "latitude": latitude, "longitude": longitude,
        "delivery_address": "Test address", "delivery_area": "Central",
        "status": "Awaiting Assignment", "assigned_delivery_person": None, "location_set": 1,
        **values,
    })


class TestDistance(unittest.TestCase):
    def test_distance_and_route_use_real_coordinates(self):
        self.assertAlmostEqual(distance_km((0, 0), (0, 1)), 111.195, places=2)
        route = nearest_delivery_route((0, 0), [
            delivery("D2", 0, 0.02), delivery("D1", 0, 0.01), delivery("D3", 0, 0.03),
        ])
        self.assertEqual([row["name"] for row in route], ["D1", "D2", "D3"])
        self.assertAlmostEqual(route[0]["distance_km"], 1.11, places=2)

    def test_invalid_and_nonfinite_coordinates_are_rejected(self):
        self.assertEqual(validate_coordinates("0", "-180"), (0.0, -180.0))
        for value in ((91, 0), (0, -181), ("nan", 0), (0, "inf"), (True, 0), ("", 1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_coordinates(*value)


class TestOptimizationWorkflows(unittest.TestCase):
    def setUp(self):
        self.service, _, _, self.frappe = load_services()
        self.seed = delivery("D1", 0, 0)
        self.frappe.get_doc.return_value = self.seed

    def test_suggests_nearest_idle_rider_and_nearby_same_area_stops(self):
        riders = [
            Row(name="far", full_name="Far", latitude=0, longitude=0.1,
                accuracy_meters=10, location_updated_at=datetime(2026, 1, 10, 11, 55)),
            Row(name="near", full_name="Near", latitude=0, longitude=0.001,
                accuracy_meters=5, location_updated_at=datetime(2026, 1, 10, 11, 59)),
        ]
        candidates = [self.seed, delivery("D2", 0, 0.01), delivery("D3", 0, 0.08)]
        self.frappe.db.sql.side_effect = [riders, candidates]
        plan = self.service.suggest_delivery_group("D1", radius_km="2", max_stops="5")
        self.assertEqual(plan["rider"], "near")
        self.assertEqual([row["name"] for row in plan["route"]], ["D1", "D2"])
        sql = self.frappe.db.sql.call_args_list
        self.assertIn("NOT EXISTS", sql[0].args[0])
        self.assertEqual(sql[0].args[1][0], datetime(2026, 1, 10, 11, 30))
        self.assertEqual(sql[1].args[1], "Central")

    def test_invalid_plan_inputs_and_unavailable_riders_are_rejected(self):
        for radius, count in (("nan", "2"), ("51", "2"), ("1", "0"), ("1", "1.5")):
            with self.subTest(radius=radius, count=count), self.assertRaises(DeliveryError):
                self.service.suggest_delivery_group("D1", radius, count)
        self.frappe.db.sql.return_value = []
        with self.assertRaisesRegex(DeliveryError, "No idle riders"):
            self.service.suggest_delivery_group("D1")
        self.seed.location_set = 0
        with self.assertRaisesRegex(DeliveryError, "coordinates"):
            self.service.suggest_delivery_group("D1")
        self.frappe.session.user = "rider@example.test"
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        with self.assertRaises(DeliveryError):
            self.service.suggest_delivery_group("D1")

    def test_rider_can_only_share_and_clear_their_own_current_location(self):
        self.frappe.session.user = "rider@example.test"
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        self.frappe.db.get_value.return_value = 1
        self.frappe.db.exists.return_value = False
        location = Mock()
        self.frappe.get_doc.return_value = location
        self.service.share_rider_location("-1.28", "36.82", "12")
        self.assertEqual(self.frappe.get_doc.call_args.args[0]["rider"], "rider@example.test")
        self.assertEqual((location.latitude, location.longitude, location.accuracy_meters), (-1.28, 36.82, 12))
        self.assertFalse(self.frappe.flags.sharing_delivery_location)
        self.frappe.db.exists.return_value = True
        self.service.clear_rider_location()
        self.assertEqual((location.location_set, location.latitude, location.longitude), (0, 0, 0))
        self.assertIsNone(location.location_updated_at)
        with self.assertRaises(DeliveryError):
            self.service.share_rider_location(0, 0, "nan")
        self.frappe.get_roles.return_value = ["Customer"]
        with self.assertRaises(DeliveryError):
            self.service.share_rider_location(0, 0, 5)

    def test_location_freshness_uses_server_timestamp(self):
        now = datetime(2026, 1, 10, 12, 0)
        location = Row(location_set=1, location_updated_at=now - timedelta(minutes=30))
        self.frappe.db.get_value.return_value = location
        self.assertIs(self.service._rider_location("rider"), location)
        location.location_updated_at = now - timedelta(minutes=30, seconds=1)
        self.assertIsNone(self.service._rider_location("rider"))
        location.location_updated_at = now + timedelta(seconds=1)
        self.assertIsNone(self.service._rider_location("rider"))
        location.location_set = 0
        self.assertIsNone(self.service._rider_location("rider"))

    def test_coordinate_updates_are_manager_only_and_preserve_workflow(self):
        order = Row(status="Ready for Delivery")
        with patch.object(self.service, "_delivery_locked", return_value=(self.seed, order)), \
                patch.object(self.service, "_save") as save, \
                patch.object(self.service, "_serialize", return_value={}):
            self.service.set_delivery_coordinates("D1", "-1.2", "36.8")
            self.assertEqual((self.seed.latitude, self.seed.longitude, self.seed.location_set), (-1.2, 36.8, 1))
            save.assert_called_once()
            self.service.clear_delivery_coordinates("D1")
            self.assertEqual((self.seed.latitude, self.seed.longitude, self.seed.location_set), (0, 0, 0))
            self.seed.status = "Delivered"
            with self.assertRaises(DeliveryError):
                self.service.set_delivery_coordinates("D1", 0, 0)
            self.frappe.session.user = "rider@example.test"
            self.frappe.get_roles.return_value = ["Delivery Staff"]
            with self.assertRaises(DeliveryError):
                self.service.set_delivery_coordinates("D1", 0, 0)

    def test_group_assignment_rechecks_all_deliveries_before_existing_assignment_workflow(self):
        rows = {"D1": self.seed, "D2": delivery("D2", 0, 0.01)}
        order = Row(status="Ready for Delivery")
        location = Row(location_set=1, latitude=0, longitude=0, location_updated_at=datetime(2026, 1, 10, 12))
        token = self.service._plan_signature("rider", location, list(rows.values()))
        self.frappe.db.sql.return_value = []
        with patch.object(self.service, "_validate_person"), \
                patch.object(self.service, "_rider_location", return_value=location), \
                patch.object(self.service, "_delivery_locked", side_effect=lambda name: (rows[name], order)) as lock, \
                patch.object(self.service, "assign_delivery") as assign:
            result = self.service.assign_delivery_group("rider", '["D2","D1"]', "2026-01-11", token)
            self.assertEqual(result["deliveries"], ["D2", "D1"])
            self.assertEqual([call.args[0] for call in lock.call_args_list], ["D1", "D2"])
            self.assertEqual([call.args[0] for call in assign.call_args_list], ["D2", "D1"])
            assign.reset_mock()
            rows["D2"].assigned_delivery_person = "other"
            with self.assertRaisesRegex(DeliveryError, "no longer ready"):
                self.service.assign_delivery_group("rider", '["D1","D2"]', "2026-01-11", token)
            assign.assert_not_called()
            rows["D2"].assigned_delivery_person = None
            rows["D2"].longitude = 0.5
            with self.assertRaisesRegex(DeliveryError, "coordinates changed"):
                self.service.assign_delivery_group("rider", '["D1","D2"]', "2026-01-11", token)
            assign.assert_not_called()
            with self.assertRaises(DeliveryError):
                self.service.assign_delivery_group("rider", '["D1","D1"]', "2026-01-11", token)

    def test_group_assignment_rejects_busy_or_stale_rider(self):
        with patch.object(self.service, "_validate_person"), \
                patch.object(self.service, "_rider_location", return_value=None):
            with self.assertRaisesRegex(DeliveryError, "recent location"):
                self.service.assign_delivery_group("rider", '["D1"]', "2026-01-11", "a" * 64)
        self.frappe.db.sql.side_effect = [[], [("another delivery",)]]
        with patch.object(self.service, "_validate_person"), \
                patch.object(self.service, "_rider_location", return_value=Row(location_set=1)):
            with self.assertRaisesRegex(DeliveryError, "no longer idle"):
                self.service.assign_delivery_group("rider", '["D1"]', "2026-01-11", "a" * 64)

    def test_rider_route_is_scoped_and_excludes_unlocated_stops(self):
        self.frappe.session.user = "rider@example.test"
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        self.frappe.db.get_value.return_value = 1
        self.frappe.get_all.return_value = [self.seed, delivery("D2", 0, 0, location_set=0)]
        location = Row(latitude=0, longitude=0, location_updated_at=datetime(2026, 1, 10, 12))
        with patch.object(self.service, "_rider_location", return_value=location):
            result = self.service.my_delivery_route()
        self.assertEqual([row["name"] for row in result["route"]], ["D1"])
        self.assertEqual(result["missing_coordinates"], 1)
        self.assertEqual(self.frappe.get_all.call_args.kwargs["filters"]["assigned_delivery_person"], "rider@example.test")


if __name__ == "__main__":
    unittest.main()
