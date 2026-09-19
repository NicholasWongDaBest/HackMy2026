"""Hardware-free tests for the pure Challenge 4 allocation policy."""

from dataclasses import FrozenInstanceError, fields
import math
import unittest

from farm.allocation import (
    AllocationInput,
    AllocationMode,
    plan_allocation,
)


def snapshot(**overrides) -> AllocationInput:
    values = {
        "container_1_water_percent": 80.0,
        "container_1_valid": True,
        "container_1_fresh": True,
        "container_3_available": True,
        "zone_1_priority": 1,
        "zone_2_priority": 1,
        "pump_1_available": True,
        "pump_2_available": True,
        "scarcity_threshold_percent": 25.0,
    }
    values.update(overrides)
    return AllocationInput(**values)


class InputContractTests(unittest.TestCase):
    def test_allocation_input_has_exact_hardware_truth_fields(self):
        self.assertEqual(
            tuple(field.name for field in fields(AllocationInput)),
            (
                "container_1_water_percent",
                "container_1_valid",
                "container_1_fresh",
                "container_3_available",
                "zone_1_priority",
                "zone_2_priority",
                "pump_1_available",
                "pump_2_available",
                "scarcity_threshold_percent",
            ),
        )

    def test_old_container_3_percentage_is_not_accepted(self):
        with self.assertRaises(TypeError):
            AllocationInput(  # type: ignore[call-arg]
                container_1_water_percent=80,
                container_3_water_percent=80,
            )

    def test_soil_moisture_fields_are_not_accepted(self):
        with self.assertRaises(TypeError):
            AllocationInput(  # type: ignore[call-arg]
                container_1_water_percent=80,
                zone_1_moisture_percent=20,
            )

    def test_input_and_plan_are_immutable(self):
        data = snapshot()
        plan = plan_allocation(data)
        with self.assertRaises(FrozenInstanceError):
            data.zone_1_priority = 9  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            plan.allowed_pumps = ()  # type: ignore[misc]


class NormalAllocationTests(unittest.TestCase):
    def test_c1_above_threshold_and_c3_available_is_normal(self):
        plan = plan_allocation(snapshot())

        self.assertEqual(plan.mode, AllocationMode.NORMAL)
        self.assertFalse(plan.scarcity_detected)
        self.assertIsNone(plan.prioritized_zone)
        self.assertEqual(plan.allowed_pumps, (1, 2))
        self.assertEqual(plan.requested_pumps, ())
        self.assertEqual(plan.deferred_zones, ())
        self.assertEqual(plan.restricted_zones, ())
        self.assertIn("Pump 1 is permitted only for Zone 1", plan.explanation)
        self.assertIn("Pump 2 is permitted only for Zone 2", plan.explanation)
        self.assertIn("no Container 3 water percentage", plan.explanation)

    def test_value_just_above_threshold_is_normal(self):
        plan = plan_allocation(snapshot(container_1_water_percent=25.01))
        self.assertEqual(plan.mode, AllocationMode.NORMAL)

    def test_c3_unavailable_does_not_create_scarcity(self):
        plan = plan_allocation(snapshot(container_3_available=False))

        self.assertEqual(plan.mode, AllocationMode.NORMAL)
        self.assertFalse(plan.scarcity_detected)
        self.assertEqual(plan.allowed_pumps, (1,))
        self.assertEqual(plan.restricted_zones, (2,))
        self.assertIn("Container 3 is configured unavailable", plan.explanation)

    def test_normal_mode_pump_1_unavailable(self):
        plan = plan_allocation(snapshot(pump_1_available=False))
        self.assertEqual(plan.allowed_pumps, (2,))
        self.assertEqual(plan.restricted_zones, (1,))
        self.assertIn("Pump 1 is unavailable", plan.explanation)

    def test_normal_mode_pump_2_unavailable(self):
        plan = plan_allocation(snapshot(pump_2_available=False))
        self.assertEqual(plan.allowed_pumps, (1,))
        self.assertEqual(plan.restricted_zones, (2,))
        self.assertIn("Pump 2 is unavailable", plan.explanation)

    def test_normal_mode_with_both_paths_unavailable(self):
        plan = plan_allocation(
            snapshot(pump_1_available=False, container_3_available=False)
        )
        self.assertEqual(plan.mode, AllocationMode.NORMAL)
        self.assertEqual(plan.allowed_pumps, ())
        self.assertEqual(plan.restricted_zones, (1, 2))
        self.assertIsNotNone(plan.refusal_reason)


class ScarcityPriorityTests(unittest.TestCase):
    def test_c1_exactly_at_threshold_enters_scarcity(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=25,
                zone_1_priority=3,
                zone_2_priority=1,
            )
        )
        self.assertEqual(plan.mode, AllocationMode.SCARCITY)
        self.assertTrue(plan.scarcity_detected)
        self.assertEqual(plan.prioritized_zone, 1)
        self.assertEqual(plan.allowed_pumps, (1, 2))
        self.assertIn("Container 1 is at 25%", plan.explanation)

    def test_c1_below_threshold_enters_scarcity(self):
        plan = plan_allocation(snapshot(container_1_water_percent=24.99))
        self.assertEqual(plan.mode, AllocationMode.SCARCITY)
        self.assertTrue(plan.scarcity_detected)

    def test_zone_2_higher_priority_defers_healthy_zone_1(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                zone_1_priority=1,
                zone_2_priority=3,
            )
        )
        self.assertEqual(plan.prioritized_zone, 2)
        self.assertEqual(plan.allowed_pumps, (2,))
        self.assertEqual(plan.deferred_zones, (1,))
        self.assertEqual(plan.restricted_zones, ())
        self.assertIn("deferred to conserve Container 1", plan.explanation)

    def test_zone_1_higher_priority_keeps_both_healthy_paths_allowed(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                zone_1_priority=4,
                zone_2_priority=2,
            )
        )
        self.assertEqual(plan.prioritized_zone, 1)
        self.assertEqual(plan.allowed_pumps, (1, 2))
        self.assertEqual(plan.deferred_zones, ())
        self.assertIn(
            "Pump 1 remains permitted for critical Zone 1", plan.explanation
        )
        self.assertIn("Pump 2 remains independently permitted", plan.explanation)

    def test_equal_priorities_use_deterministic_zone_1_tie_break(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                zone_1_priority=7,
                zone_2_priority=7,
            )
        )
        self.assertEqual(plan.prioritized_zone, 1)
        self.assertEqual(plan.allowed_pumps, (1, 2))
        self.assertIn("deterministic tie-break selects Zone 1", plan.explanation)
        self.assertIn("Soil moisture is not used", plan.explanation)

    def test_c1_empty_restricts_zone_1_not_defers_it(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=0,
                zone_1_priority=1,
                zone_2_priority=3,
            )
        )
        self.assertEqual(plan.allowed_pumps, (2,))
        self.assertEqual(plan.deferred_zones, ())
        self.assertEqual(plan.restricted_zones, (1,))
        self.assertIn("Container 1 is empty", plan.explanation)

    def test_c3_unavailable_restricts_zone_2_only(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                container_3_available=False,
                zone_1_priority=3,
                zone_2_priority=1,
            )
        )
        self.assertEqual(plan.allowed_pumps, (1,))
        self.assertEqual(plan.restricted_zones, (2,))
        self.assertIn("Container 3 is configured unavailable", plan.explanation)

    def test_pump_1_unavailable_restricts_zone_1_only(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                zone_1_priority=4,
                zone_2_priority=1,
                pump_1_available=False,
            )
        )
        self.assertEqual(plan.allowed_pumps, (2,))
        self.assertEqual(plan.restricted_zones, (1,))
        self.assertEqual(plan.deferred_zones, ())
        self.assertIn("Pump 1 is unavailable", plan.explanation)

    def test_pump_2_unavailable_restricts_zone_2_only(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                zone_1_priority=4,
                zone_2_priority=1,
                pump_2_available=False,
            )
        )
        self.assertEqual(plan.allowed_pumps, (1,))
        self.assertEqual(plan.restricted_zones, (2,))
        self.assertIn("Pump 2 is unavailable", plan.explanation)

    def test_restricted_zone_2_does_not_receive_zone_1_water(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=20,
                container_3_available=False,
                zone_1_priority=1,
                zone_2_priority=5,
            )
        )
        self.assertEqual(plan.prioritized_zone, 2)
        self.assertEqual(plan.allowed_pumps, ())
        self.assertEqual(plan.deferred_zones, (1,))
        self.assertEqual(plan.restricted_zones, (2,))
        self.assertIn("No pump or water source substitutes", plan.explanation)

    def test_both_paths_restricted_returns_no_allocation(self):
        plan = plan_allocation(
            snapshot(
                container_1_water_percent=0,
                container_3_available=False,
            )
        )
        self.assertEqual(plan.allowed_pumps, ())
        self.assertEqual(plan.deferred_zones, ())
        self.assertEqual(plan.restricted_zones, (1, 2))
        self.assertIn("Container 1 is empty", plan.refusal_reason)
        self.assertIn("Container 3 is configured unavailable", plan.refusal_reason)

    def test_no_cross_zone_substitution_or_fake_c3_level(self):
        plans = (
            plan_allocation(
                snapshot(
                    container_1_water_percent=20,
                    zone_1_priority=1,
                    zone_2_priority=3,
                )
            ),
            plan_allocation(
                snapshot(
                    container_1_water_percent=20,
                    container_3_available=False,
                    zone_1_priority=3,
                    zone_2_priority=1,
                )
            ),
        )
        for plan in plans:
            text = plan.explanation.lower()
            self.assertNotIn("pump 2 is permitted for zone 1", text)
            self.assertNotIn("pump 1 is permitted for zone 2", text)
            self.assertNotIn("container 3 is at", text)
            self.assertNotIn("alternative", text)
            self.assertNotIn("replacement", text)




class SafetyValidationTests(unittest.TestCase):
    def assertSafetyRefusal(self, data, text=None):
        plan = plan_allocation(data)
        self.assertEqual(plan.mode, AllocationMode.SAFETY_REFUSAL)
        self.assertFalse(plan.scarcity_detected)
        self.assertEqual(plan.allowed_pumps, ())
        self.assertEqual(plan.requested_pumps, ())
        self.assertEqual(plan.deferred_zones, ())
        self.assertEqual(plan.restricted_zones, (1, 2))
        self.assertIsNotNone(plan.refusal_reason)
        if text:
            self.assertIn(text, plan.refusal_reason)

    def test_stale_c1_reading(self):
        self.assertSafetyRefusal(
            snapshot(container_1_fresh=False),
            "Container 1 water measurement is stale",
        )

    def test_invalid_c1_reading(self):
        self.assertSafetyRefusal(
            snapshot(container_1_valid=False),
            "Container 1 water measurement is marked invalid",
        )

    def test_missing_c1_reading(self):
        self.assertSafetyRefusal(
            snapshot(container_1_water_percent=None),
            "Container 1 water percentage is missing",
        )

    def test_c1_percentage_out_of_range(self):
        for invalid in (-0.1, 100.1):
            with self.subTest(value=invalid):
                self.assertSafetyRefusal(
                    snapshot(container_1_water_percent=invalid),
                    "outside 0 to 100%",
                )

    def test_c1_nan_and_infinity(self):
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(value=invalid):
                self.assertSafetyRefusal(
                    snapshot(container_1_water_percent=invalid),
                    "must be finite",
                )

    def test_invalid_priorities(self):
        for zone_field in ("zone_1_priority", "zone_2_priority"):
            for invalid in (0, -1, 1.5, True, None):
                with self.subTest(field=zone_field, value=invalid):
                    self.assertSafetyRefusal(
                        snapshot(**{zone_field: invalid}),
                        "priority must be a positive integer",
                    )

    def test_invalid_boolean_states(self):
        boolean_fields = (
            "container_1_valid",
            "container_1_fresh",
            "container_3_available",
            "pump_1_available",
            "pump_2_available",
        )
        for field_name in boolean_fields:
            for invalid in (None, 0, 1, "yes"):
                with self.subTest(field=field_name, value=invalid):
                    self.assertSafetyRefusal(
                        snapshot(**{field_name: invalid}),
                        "must be a boolean",
                    )

    def test_false_c3_availability_is_valid_operational_state(self):
        plan = plan_allocation(snapshot(container_3_available=False))
        self.assertEqual(plan.mode, AllocationMode.NORMAL)
        self.assertEqual(plan.restricted_zones, (2,))

    def test_invalid_threshold(self):
        for invalid in (-0.1, 100.1, math.nan, math.inf, True, None):
            with self.subTest(value=invalid):
                self.assertSafetyRefusal(
                    snapshot(scarcity_threshold_percent=invalid),
                    "Scarcity threshold",
                )

    def test_malformed_input_object(self):
        self.assertSafetyRefusal(
            {"container_1_water_percent": 25},
            "must be an AllocationInput instance",
        )


class NonActuationAndDeterminismTests(unittest.TestCase):
    def test_requested_pumps_always_empty(self):
        cases = (
            snapshot(),
            snapshot(container_1_water_percent=25),
            snapshot(container_1_water_percent=20, zone_2_priority=3),
            snapshot(container_1_water_percent=0),
            snapshot(container_3_available=False),
            snapshot(pump_1_available=False, pump_2_available=False),
            snapshot(container_1_fresh=False),
        )
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(plan_allocation(data).requested_pumps, ())

    def test_deterministic_repeatability(self):
        data = snapshot(
            container_1_water_percent=20,
            container_3_available=True,
            zone_1_priority=7,
            zone_2_priority=7,
        )
        expected = plan_allocation(data)
        for _ in range(100):
            self.assertEqual(plan_allocation(data), expected)


if __name__ == "__main__":
    unittest.main()
