"""Pure empirical calibration for the Challenge 4 Container 1 sensor.

The three anchors were measured from the actual hackathon container and
Keyestudio water-level sensor on ESP32 GPIO33. Container volume is visibly
non-linear with raw ADC, so the conversion deliberately uses two linear
segments instead of a single ``raw / full_scale`` formula.

This module performs no hardware I/O and has no production integration.
"""

from __future__ import annotations

import math
from numbers import Real


EMPTY_ADC = 0.0
QUARTER_FULL_ADC = 1700.0
FULL_ADC = 2000.0

EMPTY_PERCENT = 0.0
QUARTER_FULL_PERCENT = 25.0
FULL_PERCENT = 100.0


def calibrate_c1_water_percent(raw_adc: float) -> float:
    """Convert one raw C1 ADC value to calibrated water percentage.

    Finite values outside the measured ADC interval are clamped. Booleans and
    non-numeric inputs raise :class:`TypeError`; NaN and infinity raise
    :class:`ValueError` so invalid sensor data cannot silently become a level.
    """

    if isinstance(raw_adc, bool) or not isinstance(raw_adc, Real):
        raise TypeError("raw_adc must be a finite real number, not bool")

    raw = float(raw_adc)
    if not math.isfinite(raw):
        raise ValueError("raw_adc must be finite")

    if raw <= EMPTY_ADC:
        return EMPTY_PERCENT
    if raw <= QUARTER_FULL_ADC:
        return _interpolate(
            raw,
            EMPTY_ADC,
            QUARTER_FULL_ADC,
            EMPTY_PERCENT,
            QUARTER_FULL_PERCENT,
        )
    if raw < FULL_ADC:
        return _interpolate(
            raw,
            QUARTER_FULL_ADC,
            FULL_ADC,
            QUARTER_FULL_PERCENT,
            FULL_PERCENT,
        )
    return FULL_PERCENT


def _interpolate(
    value: float,
    input_low: float,
    input_high: float,
    output_low: float,
    output_high: float,
) -> float:
    fraction = (value - input_low) / (input_high - input_low)
    return output_low + fraction * (output_high - output_low)


__all__ = ["calibrate_c1_water_percent"]
