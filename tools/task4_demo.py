#!/usr/bin/env python3
"""Standalone terminal demo for Challenge 4 calibration and allocation.

Run from the repository root:

    python tools/task4_demo.py

The demo performs no hardware I/O. It calibrates a supplied Container 1 ADC
value, constructs the current pure ``AllocationInput``, calls
``plan_allocation()``, and displays the returned plan.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Sequence


# Running ``python tools/task4_demo.py`` puts tools/ at sys.path[0]. Add the
# repository root so the canonical farm package can be imported reliably.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from farm.allocation import (  # noqa: E402
    AllocationInput,
    AllocationMode,
    AllocationPlan,
    plan_allocation,
)
from farm.task4_calibration import calibrate_c1_water_percent  # noqa: E402


LINE = "=" * 60
SUBLINE = "-" * 60


@dataclass(frozen=True)
class PresetScenario:
    """Display metadata plus raw/calibrated allocation inputs."""

    number: int
    name: str
    raw_c1_adc: float
    container_3_available: bool = True
    zone_1_priority: int = 1
    zone_2_priority: int = 1
    pump_1_available: bool = True
    pump_2_available: bool = True
    container_1_valid: bool = True
    container_1_fresh: bool = True
    scarcity_threshold_percent: float = 25.0


PRESET_SCENARIOS: tuple[PresetScenario, ...] = (
    PresetScenario(
        1,
        "Normal - C1 full and C3 available",
        raw_c1_adc=2000,
    ),
    PresetScenario(
        2,
        "Scarcity threshold - Zone 1 higher priority",
        raw_c1_adc=1700,
        zone_1_priority=3,
        zone_2_priority=1,
    ),
    PresetScenario(
        3,
        "Scarcity - Zone 2 higher priority",
        raw_c1_adc=1500,
        zone_1_priority=1,
        zone_2_priority=3,
    ),
    PresetScenario(
        4,
        "C3 configured unavailable",
        raw_c1_adc=2000,
        container_3_available=False,
    ),
    PresetScenario(
        5,
        "C1 empty",
        raw_c1_adc=0,
        zone_1_priority=3,
        zone_2_priority=1,
    ),
)


class InputCancelled(Exception):
    """The operator ended terminal input with Ctrl+C or end-of-file."""


def _read_line(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise InputCancelled from exc


def _format_number(value: float) -> str:
    return f"{float(value):g}"


def _format_percent(value: float) -> str:
    return f"{_format_number(value)}%"


def _format_yes_no(value: bool) -> str:
    return "YES" if value else "NO"


def _format_pumps(pumps: Sequence[int]) -> str:
    return ", ".join(f"Pump {pump}" for pump in pumps) or "None"


def _format_zones(zones: Sequence[int]) -> str:
    return ", ".join(f"Zone {zone}" for zone in zones) or "None"


def _format_mode(mode: AllocationMode) -> str:
    return mode.value.replace("_", " ").upper()


def build_allocation_input(
    *,
    raw_c1_adc: float,
    container_1_valid: bool = True,
    container_1_fresh: bool = True,
    container_3_available: bool = True,
    zone_1_priority: int = 1,
    zone_2_priority: int = 1,
    pump_1_available: bool = True,
    pump_2_available: bool = True,
    scarcity_threshold_percent: float = 25.0,
) -> tuple[float, AllocationInput]:
    """Calibrate raw C1 ADC and construct the current allocation contract."""

    calibrated = calibrate_c1_water_percent(raw_c1_adc)
    allocation_input = AllocationInput(
        container_1_water_percent=calibrated,
        container_1_valid=container_1_valid,
        container_1_fresh=container_1_fresh,
        container_3_available=container_3_available,
        zone_1_priority=zone_1_priority,
        zone_2_priority=zone_2_priority,
        pump_1_available=pump_1_available,
        pump_2_available=pump_2_available,
        scarcity_threshold_percent=scarcity_threshold_percent,
    )
    return calibrated, allocation_input


def evaluate_scenario(
    scenario: PresetScenario,
) -> tuple[float, AllocationInput, AllocationPlan]:
    calibrated, allocation_input = build_allocation_input(
        raw_c1_adc=scenario.raw_c1_adc,
        container_1_valid=scenario.container_1_valid,
        container_1_fresh=scenario.container_1_fresh,
        container_3_available=scenario.container_3_available,
        zone_1_priority=scenario.zone_1_priority,
        zone_2_priority=scenario.zone_2_priority,
        pump_1_available=scenario.pump_1_available,
        pump_2_available=scenario.pump_2_available,
        scarcity_threshold_percent=scenario.scarcity_threshold_percent,
    )
    return calibrated, allocation_input, plan_allocation(allocation_input)


def display_plan(
    raw_c1_adc: float,
    calibrated_c1_percent: float,
    allocation_input: AllocationInput,
    plan: AllocationPlan,
    *,
    scenario_title: str | None = None,
) -> None:
    """Display calibrated inputs and the exact returned allocation plan."""

    print()
    print(LINE)
    print("CHALLENGE 4 WATER ALLOCATION")
    if scenario_title:
        print(scenario_title)
    print(LINE)
    print()
    print("INPUTS")
    print()
    print(f"Container 1 raw ADC: {_format_number(raw_c1_adc)}")
    print(f"Calibrated C1 water: {_format_percent(calibrated_c1_percent)}")
    print(
        "Container 1 reading valid: "
        f"{_format_yes_no(allocation_input.container_1_valid)}"
    )
    print(
        "Container 1 reading fresh: "
        f"{_format_yes_no(allocation_input.container_1_fresh)}"
    )
    print(
        "Container 3 configured available: "
        f"{_format_yes_no(allocation_input.container_3_available)}"
    )
    print(f"Scarcity threshold: {_format_percent(allocation_input.scarcity_threshold_percent)}")
    print()
    print(f"Zone 1 crop priority: {allocation_input.zone_1_priority}")
    print(f"Zone 2 crop priority: {allocation_input.zone_2_priority}")
    print()
    print(f"Pump 1 available: {_format_yes_no(allocation_input.pump_1_available)}")
    print(f"Pump 2 available: {_format_yes_no(allocation_input.pump_2_available)}")
    print()
    print(SUBLINE)
    print()
    print("DECISION")
    print()
    print(f"System mode: {_format_mode(plan.mode)}")
    print(f"Scarcity detected: {_format_yes_no(plan.scarcity_detected)}")
    print()
    print("Prioritised zone:")
    print(f"Zone {plan.prioritized_zone}" if plan.prioritized_zone else "None")
    print()
    print("Allowed pumps:")
    print(_format_pumps(plan.allowed_pumps))
    print()
    print("Deferred zones:")
    print(_format_zones(plan.deferred_zones))
    print()
    print("Restricted zones:")
    print(_format_zones(plan.restricted_zones))
    print()
    print("Requested pumps:")
    print(_format_pumps(plan.requested_pumps))
    print()
    print("Note:")
    print(
        "No real pump run is requested because controller/hardware demand "
        "integration has not been added yet."
    )
    if plan.refusal_reason:
        print()
        print("Safety/refusal reason:")
        print(plan.refusal_reason)
    print()
    print(SUBLINE)
    print()
    print("DECISION EXPLANATION")
    print()
    print(plan.explanation)
    print()
    print(LINE)


def run_scenario(scenario: PresetScenario) -> None:
    calibrated, allocation_input, plan = evaluate_scenario(scenario)
    display_plan(
        scenario.raw_c1_adc,
        calibrated,
        allocation_input,
        plan,
        scenario_title=f"SCENARIO {scenario.number} - {scenario.name}",
    )


def run_all_presets() -> None:
    for scenario in PRESET_SCENARIOS:
        run_scenario(scenario)


def choose_preset() -> None:
    print()
    print("Preset scenarios")
    print()
    for scenario in PRESET_SCENARIOS:
        print(f"{scenario.number}. {scenario.name}")
    print("0. Back")

    while True:
        choice = _read_line("\nChoose a scenario: ").strip()
        if choice == "0":
            return
        try:
            number = int(choice)
        except ValueError:
            print("Please enter a scenario number from 1 to 5, or 0 to go back.")
            continue

        for scenario in PRESET_SCENARIOS:
            if scenario.number == number:
                run_scenario(scenario)
                return
        print("Please enter a scenario number from 1 to 5, or 0 to go back.")


def _prompt_finite_number(label: str) -> float:
    while True:
        raw = _read_line(f"{label}: ").strip()
        if not raw:
            print("A numeric value is required.")
            continue
        try:
            value = float(raw)
        except ValueError:
            print(f"'{raw}' is not a number. Please try again.")
            continue
        if not math.isfinite(value):
            print("The value must be finite; NaN and infinity are not accepted.")
            continue
        return value


def _prompt_percentage(label: str) -> float:
    while True:
        value = _prompt_finite_number(f"{label} (0-100)")
        if 0 <= value <= 100:
            return value
        print("The value must be between 0 and 100 inclusive.")


def _prompt_priority(label: str) -> int:
    while True:
        raw = _read_line(f"{label} (positive whole number): ").strip()
        try:
            value = int(raw)
        except ValueError:
            print("Priority must be a positive whole number, for example 1 or 3.")
            continue
        if value < 1:
            print("Priority must be at least 1; higher numbers mean higher priority.")
            continue
        return value


def _prompt_yes_no(label: str) -> bool:
    while True:
        raw = _read_line(f"{label} (yes/no): ").strip().lower()
        if raw in {"yes", "y"}:
            return True
        if raw in {"no", "n"}:
            return False
        print("Please enter yes or no.")


def run_interactive() -> None:
    print()
    print("Interactive custom scenario")
    print("Raw ADC values below 0 clamp to 0%; values above 2000 clamp to 100%.")
    print()

    raw_c1_adc = _prompt_finite_number("Container 1 raw ADC")
    calibrated, allocation_input = build_allocation_input(
        raw_c1_adc=raw_c1_adc,
        container_1_valid=_prompt_yes_no("Container 1 measurement valid"),
        container_1_fresh=_prompt_yes_no("Container 1 measurement fresh"),
        container_3_available=_prompt_yes_no("Container 3 configured available"),
        zone_1_priority=_prompt_priority("Zone 1 crop priority"),
        zone_2_priority=_prompt_priority("Zone 2 crop priority"),
        pump_1_available=_prompt_yes_no("Pump 1 available"),
        pump_2_available=_prompt_yes_no("Pump 2 available"),
        scarcity_threshold_percent=_prompt_percentage("Scarcity threshold"),
    )
    plan = plan_allocation(allocation_input)
    display_plan(
        raw_c1_adc,
        calibrated,
        allocation_input,
        plan,
        scenario_title="INTERACTIVE CUSTOM SCENARIO",
    )


def show_menu() -> None:
    print()
    print("Challenge 4 Demo")
    print()
    print("Empirical C1 calibration: ADC 0 -> 0%, 1700 -> 25%, 2000 -> 100%")
    print("Fixed topology:")
    print("  Container 1 -> Pump 1 -> Zone 1 / Container 2")
    print("  Container 3 -> Pump 2 -> Zone 2 / Container 4")
    print("  Container 3 is availability-only; no C3 percentage is invented")
    print("  No cross-zone substitution")
    print()
    print("1. Run a preset scenario")
    print("2. Run all preset scenarios")
    print("3. Interactive custom scenario")
    print("4. Exit")


def main() -> int:
    while True:
        show_menu()
        try:
            choice = _read_line("\nChoose an option: ").strip()
            if choice == "1":
                choose_preset()
            elif choice == "2":
                run_all_presets()
            elif choice == "3":
                run_interactive()
            elif choice == "4":
                print("Challenge 4 demo finished.")
                return 0
            else:
                print("Please enter 1, 2, 3, or 4.")
        except InputCancelled:
            print("\nInput cancelled. Challenge 4 demo finished.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
