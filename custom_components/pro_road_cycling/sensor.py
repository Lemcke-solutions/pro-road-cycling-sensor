from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import DOMAIN

RACES_FILE = Path(__file__).parent / "cycling_races.json"

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _load_races(path: Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("races", [])
    except FileNotFoundError:
        _LOGGER.warning("Races file not found: %s", path)
        return []
    except (json.JSONDecodeError, OSError) as err:
        _LOGGER.error("Failed to load races file %s: %s", path, err)
        return []


def _category_slug(category: str) -> str:
    return category.lower().replace(".", "").replace(" ", "_")


def _resolve_name(name: str | dict, lang: str) -> str:
    if isinstance(name, str):
        return name
    return name.get(lang) or name.get("en") or next(iter(name.values()), "Unknown")


def _race_dates(race: dict) -> tuple[date, date]:
    return date.fromisoformat(race["start_date"]), date.fromisoformat(race["end_date"])


def _compute_slots(races: list[dict]) -> int:
    if not races:
        return 1

    all_starts = [date.fromisoformat(r["start_date"]) for r in races]
    all_ends = [date.fromisoformat(r["end_date"]) for r in races]

    max_concurrent = 0
    day = min(all_starts)
    last = max(all_ends)
    while day <= last:
        n = sum(
            1 for r in races
            if date.fromisoformat(r["start_date"]) <= day <= date.fromisoformat(r["end_date"])
        )
        max_concurrent = max(max_concurrent, n)
        day += timedelta(days=1)

    max_same_start = max(Counter(r["start_date"] for r in races).values(), default=1)

    return max(max_concurrent, max_same_start, 1)


def _current_slots(races: list[dict], today: date, n: int) -> list[dict | None]:
    current = [
        r for r in races
        if date.fromisoformat(r["start_date"]) <= today <= date.fromisoformat(r["end_date"])
    ]
    current.sort(key=lambda r: date.fromisoformat(r["end_date"]))
    return current[:n] + [None] * (n - len(current))


def _next_slots(races: list[dict], today: date, n: int) -> list[dict | None]:
    upcoming = [r for r in races if date.fromisoformat(r["start_date"]) > today]
    upcoming.sort(key=lambda r: date.fromisoformat(r["start_date"]))
    return upcoming[:n] + [None] * (n - len(upcoming))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    races = await hass.async_add_executor_job(_load_races, RACES_FILE)
    if not races:
        _LOGGER.warning(
            "No races loaded from %s — place cycling_races.json in the integration "
            "directory and reload the integration",
            RACES_FILE,
        )

    # Collect all unique (category, gender) combinations from the race data
    all_groups: dict[tuple[str, str], str] = {}  # (cat_slug, gender) -> display label
    for race in races:
        cat = race.get("category", "other")
        gender = race.get("gender", "men")
        cat_slug = _category_slug(cat)
        gender_label = "Men" if gender == "men" else "Women"
        all_groups[(cat_slug, gender)] = f"{cat} {gender_label}"

    device_info_by_cat: dict[tuple[str, str], DeviceInfo] = {
        (cat_slug, gender): DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{cat_slug}_{gender}")},
            name=f"Pro Road Cycling — {label}",
            manufacturer="Lemcke Solutions",
            model="Race Calendar",
        )
        for (cat_slug, gender), label in all_groups.items()
    }

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for race in races:
        type_slug = "stage" if race.get("type") == "stage_race" else "oneday"
        cat_slug = _category_slug(race.get("category", "other"))
        gender = race.get("gender", "men")
        groups.setdefault((type_slug, cat_slug, gender), []).append(race)

    sensors: list[RaceSlotSensor] = []
    for (type_slug, cat_slug, gender), group_races in groups.items():
        n_slots = _compute_slots(group_races)
        _LOGGER.debug(
            "Group %s/%s/%s: %d race(s), %d slot(s)",
            type_slug, cat_slug, gender, len(group_races), n_slots,
        )
        for status in ("current", "next"):
            for slot in range(1, n_slots + 1):
                sensors.append(
                    RaceSlotSensor(
                        hass=hass,
                        entry=entry,
                        device_info=device_info_by_cat[(cat_slug, gender)],
                        status=status,
                        type_slug=type_slug,
                        cat_slug=cat_slug,
                        gender=gender,
                        slot=slot,
                        races=group_races,
                        n_slots=n_slots,
                    )
                )

    async_add_entities(sensors)

    async def _midnight_update(_now) -> None:
        for sensor in sensors:
            sensor.async_write_ha_state()

    entry.async_on_unload(
        async_track_time_change(hass, _midnight_update, hour=0, minute=0, second=0)
    )


class RaceSlotSensor(SensorEntity):
    _attr_should_poll = False
    _attr_icon = "mdi:bicycle-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        status: str,
        type_slug: str,
        cat_slug: str,
        gender: str,
        slot: int,
        races: list[dict],
        n_slots: int,
    ) -> None:
        self._hass = hass
        self._status = status
        self._type_slug = type_slug
        self._cat_slug = cat_slug
        self._gender = gender
        self._slot = slot
        self._races = races
        self._n_slots = n_slots

        base = f"{status}_road_{type_slug}_{cat_slug}_{gender}_{slot}"
        self.entity_id = f"sensor.{base}"
        self._attr_unique_id = f"{entry.entry_id}_{base}"
        self._attr_device_info = device_info

    def _assigned_race(self) -> dict | None:
        today = dt_util.now().date()
        if self._status == "current":
            slots = _current_slots(self._races, today, self._n_slots)
        else:
            slots = _next_slots(self._races, today, self._n_slots)
        return slots[self._slot - 1]

    @property
    def name(self) -> str:
        race = self._assigned_race()
        if race is None:
            return f"{self._status.title()} {self._type_slug} {self._cat_slug} {self._gender} {self._slot}"
        return _resolve_name(race["name"], self._hass.config.language)

    @property
    def native_value(self) -> int | None:
        race = self._assigned_race()
        if race is None:
            return None
        today = dt_util.now().date()
        start, end = _race_dates(race)
        if self._status == "current":
            return (end - today).days
        return (start - today).days

    @property
    def extra_state_attributes(self) -> dict:
        race = self._assigned_race()
        if race is None:
            return {}
        today = dt_util.now().date()
        start, end = _race_dates(race)
        lang = self._hass.config.language
        attrs: dict = {
            "race_name": _resolve_name(race["name"], lang),
            "category": race.get("category"),
            "gender": race.get("gender"),
            "race_type": race.get("type"),
            "start_date": race["start_date"],
            "end_date": race["end_date"],
        }
        if self._status == "current" and start < end:
            attrs["days_remaining"] = (end - today).days
        return attrs
