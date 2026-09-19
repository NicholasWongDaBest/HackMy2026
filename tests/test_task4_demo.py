"""Hardware-free tests for the updated Challenge 4 terminal demo."""

from contextlib import redirect_stdout
from io import StringIO
import unittest

from farm.allocation import AllocationMode
from tools.task4_demo import PRESET_SCENARIOS, display_plan, evaluate_scenario


class Task4DemoTests(unittest.TestCase):
    def test_all_presets_are_non_actuating(self):
        for scenario in PRESET_SCENARIOS:
            with self.subTest(scenario=scenario.name):
                _, _, plan = evaluate_scenario(scenario)
                self.assertEqual(plan.requested_pumps, ())

    def test_normal_preset(self):
        calibrated, allocation_input, plan = evaluate_scenario(PRESET_SCENARIOS[0])
        self.assertEqual(calibrated, 100.0)
        self.assertTrue(allocation_input.container_3_available)
        self.assertEqual(plan.mode, AllocationMode.NORMAL)
        self.assertEqual(plan.allowed_pumps, (1, 2))

    def test_zone_1_priority_scarcity_preset(self):
        calibrated, _, plan = evaluate_scenario(PRESET_SCENARIOS[1])
        self.assertEqual(calibrated, 25.0)
        self.assertEqual(plan.mode, AllocationMode.SCARCITY)
        self.assertEqual(plan.prioritized_zone, 1)
        self.assertEqual(plan.allowed_pumps, (1, 2))

    def test_zone_2_priority_scarcity_preset(self):
        calibrated, _, plan = evaluate_scenario(PRESET_SCENARIOS[2])
        self.assertLess(calibrated, 25.0)
        self.assertEqual(plan.prioritized_zone, 2)
        self.assertEqual(plan.allowed_pumps, (2,))
        self.assertEqual(plan.deferred_zones, (1,))

    def test_c3_unavailable_and_c1_empty_presets(self):
        _, c3_input, c3_plan = evaluate_scenario(PRESET_SCENARIOS[3])
        self.assertFalse(c3_input.container_3_available)
        self.assertEqual(c3_plan.restricted_zones, (2,))

        calibrated, _, empty_plan = evaluate_scenario(PRESET_SCENARIOS[4])
        self.assertEqual(calibrated, 0.0)
        self.assertEqual(empty_plan.restricted_zones, (1,))

    def test_display_includes_raw_and_calibrated_values(self):
        scenario = PRESET_SCENARIOS[1]
        calibrated, allocation_input, plan = evaluate_scenario(scenario)
        output = StringIO()
        with redirect_stdout(output):
            display_plan(
                scenario.raw_c1_adc,
                calibrated,
                allocation_input,
                plan,
                scenario_title=scenario.name,
            )
        text = output.getvalue()
        self.assertIn("Container 1 raw ADC: 1700", text)
        self.assertIn("Calibrated C1 water: 25%", text)
        self.assertIn("Requested pumps:\nNone", text)


if __name__ == "__main__":
    unittest.main()
