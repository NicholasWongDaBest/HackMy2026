"""Pure, hardware-independent water-allocation policy for Challenge 4.

The actual hackathon topology is fixed:

    Container 1 -> Pump 1 -> Zone 1
    Container 3 -> Pump 2 -> Zone 2

Container 1 has a calibrated water-level measurement. Container 3 has no
water-level sensor and is represented only by an operator/configured boolean.
Scarcity is therefore derived solely from Container 1. Crop priority is
configured explicitly; soil moisture is not an allocation input or tie-break.

``allowed_pumps`` lists source/pump paths permitted by allocation policy.
``requested_pumps`` always remains empty because this module has no irrigation
demand signal and never operates hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from numbers import Real
from typing import Optional, Tuple


class AllocationMode(str, Enum):
    """High-level operating mode returned with every plan."""

    NORMAL = "normal"
    SCARCITY = "scarcity"
    SAFETY_REFUSAL = "safety_refusal"


@dataclass(frozen=True)
class AllocationInput:
    """One immutable allocation snapshot.

    ``container_1_water_percent`` is a calibrated percentage supplied by a
    later integration layer. Raw ADC conversion does not belong here.
    ``container_3_available`` is a configured/operator state, not a measured
    percentage. Higher priority integers mean more important crops.
    """

    container_1_water_percent: Optional[float]
    container_1_valid: bool = True
    container_1_fresh: bool = True
    container_3_available: bool = True
    zone_1_priority: int = 1
    zone_2_priority: int = 1
    pump_1_available: bool = True
    pump_2_available: bool = True
    scarcity_threshold_percent: float = 25.0


@dataclass(frozen=True)
class AllocationPlan:
    """Deterministic, explainable result of :func:`plan_allocation`.

    A restricted zone cannot safely use its own path. A deferred zone has a
    working path but is intentionally postponed to conserve scarce Container 1
    water. Pumps are permanently bound to their corresponding zones.
    """

    scarcity_detected: bool
    mode: AllocationMode
    prioritized_zone: Optional[int]
    allowed_pumps: Tuple[int, ...]
    requested_pumps: Tuple[int, ...]
    deferred_zones: Tuple[int, ...]
    restricted_zones: Tuple[int, ...]
    explanation: str
    refusal_reason: Optional[str] = None


def plan_allocation(snapshot: object) -> AllocationPlan:
    """Return a pure allocation plan without requesting actuator operation."""

    if not isinstance(snapshot, AllocationInput):
        return _safety_refusal(
            "allocation input must be an AllocationInput instance"
        )

    errors = _validation_errors(snapshot)
    if errors:
        return _safety_refusal("; ".join(errors))

    water_1 = float(snapshot.container_1_water_percent)
    threshold = float(snapshot.scarcity_threshold_percent)
    scarcity = water_1 <= threshold

    if scarcity:
        return _scarcity_plan(snapshot, water_1, threshold)
    return _normal_plan(snapshot, water_1, threshold)


def _safety_refusal(reason: str) -> AllocationPlan:
    return AllocationPlan(
        scarcity_detected=False,
        mode=AllocationMode.SAFETY_REFUSAL,
        prioritized_zone=None,
        allowed_pumps=(),
        requested_pumps=(),
        deferred_zones=(),
        restricted_zones=(1, 2),
        explanation=f"Automatic allocation refused for safety: {reason}.",
        refusal_reason=reason,
    )


def _normal_plan(
    snapshot: AllocationInput,
    water_1: float,
    threshold: float,
) -> AllocationPlan:
    blocks = _path_block_reasons(snapshot, water_1)
    restricted = tuple(zone for zone in (1, 2) if blocks[zone] is not None)
    allowed = tuple(zone for zone in (1, 2) if blocks[zone] is None)

    messages = [
        f"Container 1 is at {_percent(water_1)}, above the "
        f"{_percent(threshold)} scarcity threshold."
    ]
    if blocks[1] is None:
        messages.append(
            "Pump 1 is permitted only for Zone 1 from Container 1."
        )
    else:
        messages.append(f"Zone 1 is restricted because {blocks[1]}.")

    if blocks[2] is None:
        messages.append(
            "Container 3 is configured available, so Pump 2 is permitted only "
            "for Zone 2; no Container 3 water percentage is measured or used."
        )
    else:
        messages.append(f"Zone 2 is restricted because {blocks[2]}.")

    messages.append(
        "No pump run is requested until the later demand layer determines "
        "irrigation is needed."
    )
    refusal = _refusal_reason(blocks, restricted) if not allowed else None

    return AllocationPlan(
        scarcity_detected=False,
        mode=AllocationMode.NORMAL,
        prioritized_zone=None,
        allowed_pumps=allowed,
        requested_pumps=(),
        deferred_zones=(),
        restricted_zones=restricted,
        explanation=" ".join(messages),
        refusal_reason=refusal,
    )


def _scarcity_plan(
    snapshot: AllocationInput,
    water_1: float,
    threshold: float,
) -> AllocationPlan:
    preferred, preference_reason = _preferred_zone(snapshot)
    blocks = _path_block_reasons(snapshot, water_1)
    restricted = tuple(zone for zone in (1, 2) if blocks[zone] is not None)

    # Only Zone 1 has a measured scarce source. It is deferred when its path is
    # healthy but Zone 2 has the higher configured crop priority.
    deferred = (
        (1,)
        if preferred == 2 and blocks[1] is None
        else ()
    )
    allowed = tuple(
        zone
        for zone in (1, 2)
        if blocks[zone] is None and zone not in deferred
    )

    messages = [
        f"Water scarcity detected because Container 1 is at "
        f"{_percent(water_1)}, at or below the {_percent(threshold)} threshold.",
        preference_reason,
    ]

    if blocks[1] is not None:
        messages.append(f"Zone 1 is restricted because {blocks[1]}.")
    elif 1 in deferred:
        messages.append(
            "Zone 1 routine irrigation is deferred to conserve Container 1 "
            "because Zone 2 currently has higher configured crop priority."
        )
    else:
        messages.append(
            "Pump 1 remains permitted for critical Zone 1 irrigation from "
            "Container 1."
        )

    if blocks[2] is not None:
        messages.append(f"Zone 2 is restricted because {blocks[2]}.")
    else:
        messages.append(
            "Container 3 is configured available, so Pump 2 remains "
            "independently permitted only for Zone 2; no Container 3 water "
            "percentage is measured or used."
        )

    messages.extend(
        (
            "No pump or water source substitutes for the other zone.",
            "No pump run is requested until the later demand layer determines "
            "irrigation is needed.",
        )
    )

    refusal = None
    if not allowed:
        reasons = [blocks[zone] for zone in restricted]
        if 1 in deferred:
            reasons.append("Zone 1 is deferred to conserve Container 1")
        refusal = "; ".join(reason for reason in reasons if reason)

    return AllocationPlan(
        scarcity_detected=True,
        mode=AllocationMode.SCARCITY,
        prioritized_zone=preferred,
        allowed_pumps=allowed,
        requested_pumps=(),
        deferred_zones=deferred,
        restricted_zones=restricted,
        explanation=" ".join(messages),
        refusal_reason=refusal,
    )


def _preferred_zone(snapshot: AllocationInput) -> tuple[int, str]:
    priority_1 = snapshot.zone_1_priority
    priority_2 = snapshot.zone_2_priority

    if priority_1 > priority_2:
        return 1, (
            f"Zone 1 is prioritised because its configured crop priority "
            f"({priority_1}) is higher than Zone 2 ({priority_2})."
        )
    if priority_2 > priority_1:
        return 2, (
            f"Zone 2 is prioritised because its configured crop priority "
            f"({priority_2}) is higher than Zone 1 ({priority_1})."
        )
    return 1, (
        f"Configured crop priorities are equal ({priority_1}); deterministic "
        "tie-break selects Zone 1. Soil moisture is not used."
    )


def _path_block_reasons(
    snapshot: AllocationInput,
    water_1: float,
) -> dict[int, Optional[str]]:
    zone_1_reasons = []
    if water_1 == 0.0:
        zone_1_reasons.append("Container 1 is empty (0%); Pump 1 is prohibited")
    if not snapshot.pump_1_available:
        zone_1_reasons.append("Pump 1 is unavailable")

    zone_2_reasons = []
    if not snapshot.container_3_available:
        zone_2_reasons.append("Container 3 is configured unavailable")
    if not snapshot.pump_2_available:
        zone_2_reasons.append("Pump 2 is unavailable")

    return {
        1: "; ".join(zone_1_reasons) or None,
        2: "; ".join(zone_2_reasons) or None,
    }


def _refusal_reason(
    blocks: dict[int, Optional[str]],
    restricted: Tuple[int, ...],
) -> Optional[str]:
    reasons = [blocks[zone] for zone in restricted]
    joined = "; ".join(reason for reason in reasons if reason)
    return joined or None


def _validation_errors(snapshot: AllocationInput) -> list[str]:
    errors = []

    water_error = _percentage_error(
        "Container 1 water percentage",
        snapshot.container_1_water_percent,
    )
    if water_error:
        errors.append(water_error)

    for label, value, false_message in (
        (
            "Container 1 validity flag",
            snapshot.container_1_valid,
            "Container 1 water measurement is marked invalid",
        ),
        (
            "Container 1 freshness flag",
            snapshot.container_1_fresh,
            "Container 1 water measurement is stale",
        ),
    ):
        if type(value) is not bool:
            errors.append(f"{label} must be a boolean")
        elif not value:
            errors.append(false_message)

    if type(snapshot.container_3_available) is not bool:
        errors.append("Container 3 availability must be a boolean")

    for zone, priority in (
        (1, snapshot.zone_1_priority),
        (2, snapshot.zone_2_priority),
    ):
        if type(priority) is not int or priority < 1:
            errors.append(f"Zone {zone} priority must be a positive integer")

    for pump, available in (
        (1, snapshot.pump_1_available),
        (2, snapshot.pump_2_available),
    ):
        if type(available) is not bool:
            errors.append(f"Pump {pump} availability must be a boolean")

    threshold_error = _percentage_error(
        "Scarcity threshold",
        snapshot.scarcity_threshold_percent,
    )
    if threshold_error:
        errors.append(threshold_error)

    return errors


def _percentage_error(label: str, value: object) -> Optional[str]:
    if value is None:
        return f"{label} is missing"
    if isinstance(value, bool) or not isinstance(value, Real):
        return f"{label} must be a finite number from 0 to 100"

    numeric = float(value)
    if not math.isfinite(numeric):
        return f"{label} must be finite"
    if not 0.0 <= numeric <= 100.0:
        return f"{label} {numeric:g}% is outside 0 to 100%"
    return None


def _percent(value: float) -> str:
    return f"{value:g}%"


__all__ = [
    "AllocationInput",
    "AllocationMode",
    "AllocationPlan",
    "plan_allocation",
]
