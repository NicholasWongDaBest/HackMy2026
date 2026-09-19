"""Hardware-free tests for empirical Container 1 ADC calibration."""

import math
import unittest

from farm.task4_calibration import calibrate_c1_water_percent


class Container1CalibrationTests(unittest.TestCase):
    def test_empty_anchor(self):
        self.assertEqual(calibrate_c1_water_percent(0), 0.0)

    def test_physical_quarter_full_anchor(self):
        self.assertEqual(calibrate_c1_water_percent(1700), 25.0)

    def test_full_anchor(self):
        self.assertEqual(calibrate_c1_water_percent(2000), 100.0)

    def test_midpoint_below_1700(self):
        self.assertEqual(calibrate_c1_water_percent(850), 12.5)

    def test_midpoint_between_1700_and_2000(self):
        self.assertEqual(calibrate_c1_water_percent(1850), 62.5)

    def test_measured_example_1500(self):
        self.assertAlmostEqual(
            calibrate_c1_water_percent(1500),
            22.058823529411764,
        )

    def test_below_zero_clamps_to_empty(self):
        self.assertEqual(calibrate_c1_water_percent(-500), 0.0)

    def test_above_2000_clamps_to_full(self):
        self.assertEqual(calibrate_c1_water_percent(4095), 100.0)

    def test_nan_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            calibrate_c1_water_percent(math.nan)

    def test_infinities_are_rejected(self):
        for value in (math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite"):
                    calibrate_c1_water_percent(value)

    def test_bool_is_rejected(self):
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    calibrate_c1_water_percent(value)

    def test_non_numeric_input_is_rejected(self):
        for value in ("1700", None, object()):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    calibrate_c1_water_percent(value)  # type: ignore[arg-type]

    def test_deterministic_repeated_calls(self):
        expected = calibrate_c1_water_percent(1500.25)
        for _ in range(100):
            self.assertEqual(calibrate_c1_water_percent(1500.25), expected)


if __name__ == "__main__":
    unittest.main()
