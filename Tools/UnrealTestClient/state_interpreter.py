"""Rule-based helpers for interpreting Unreal test events."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

Event = Mapping[str, Any]
Predicate = Callable[[Event], bool]


def _get_type(event: Event) -> str:
    value = event.get("type", "")
    return str(value) if value is not None else ""


def _get_payload(event: Event) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _match_optional_field(container: Mapping[str, Any], field_name: str, expected: Any) -> bool:
    if expected is None:
        return True
    value = container.get(field_name)
    return value == expected


def event_type_is(event: Event, expected_type: str) -> bool:
    """Return True when the event type matches the expected value."""

    return _get_type(event) == expected_type


def has_damage_applied(
    event: Event,
    *,
    amount: Optional[float] = None,
    source_actor_id: Optional[str] = None,
    target_actor_id: Optional[str] = None,
    damage_type: Optional[str] = None,
) -> bool:
    """Match damage_applied events with optional field filters."""

    if not event_type_is(event, "damage_applied"):
        return False

    payload = _get_payload(event)
    return all(
        [
            _match_optional_field(payload, "amount", amount),
            _match_optional_field(payload, "source_actor_id", source_actor_id),
            _match_optional_field(payload, "target_actor_id", target_actor_id),
            _match_optional_field(payload, "damage_type", damage_type),
        ]
    )


def has_actor_died(
    event: Event,
    *,
    actor_id: Optional[str] = None,
    target_actor_id: Optional[str] = None,
) -> bool:
    """Match actor_died events with optional field filters."""

    if not event_type_is(event, "actor_died"):
        return False

    payload = _get_payload(event)
    return all(
        [
            _match_optional_field(payload, "actor_id", actor_id),
            _match_optional_field(payload, "target_actor_id", target_actor_id),
        ]
    )


def has_command_step_succeeded(
    event: Event,
    *,
    command_name: Optional[str] = None,
    step_index: Optional[int] = None,
) -> bool:
    """Match command_step_succeeded events."""

    if not event_type_is(event, "command_step_succeeded"):
        return False

    payload = _get_payload(event)
    return all(
        [
            _match_optional_field(payload, "command_name", command_name),
            _match_optional_field(payload, "step_index", step_index),
        ]
    )


def has_command_step_failed(
    event: Event,
    *,
    command_name: Optional[str] = None,
    step_index: Optional[int] = None,
    error_code: Optional[str] = None,
) -> bool:
    """Match command_step_failed events."""

    if not event_type_is(event, "command_step_failed"):
        return False

    payload = _get_payload(event)
    return all(
        [
            _match_optional_field(payload, "command_name", command_name),
            _match_optional_field(payload, "step_index", step_index),
            _match_optional_field(payload, "error_code", error_code),
        ]
    )


def first_match(events: Iterable[Event], predicate: Predicate) -> Optional[Event]:
    """Return the first event that matches the predicate."""

    for event in events:
        if predicate(event):
            return event
    return None
