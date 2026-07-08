# Pro Road Cycling Sensor

A Home Assistant custom integration that creates sensors for professional road cycling races. All sensors are grouped under a single device and automatically reflect which races are happening today and which are coming up.

## How it works

The integration reads `cycling_races.json` (bundled in the integration directory) and creates two sensor groups per race type / category / gender combination:

- **`current_road_*`** — races happening **today**; state = days remaining (0 on the last day)
- **`next_road_*`** — upcoming races sorted by start date; state = days until start

The number of slots per group is calculated automatically from the calendar data. Race names are displayed in the language configured in your Home Assistant instance. Sensors are grouped into devices per category and gender (e.g. **Pro Road Cycling — WT Men**, **Pro Road Cycling — WT Women**, **Pro Road Cycling — 1.Pro Men**, …), all listed under the Lemcke Solutions manufacturer.

### Sensor naming

```
sensor.{status}_road_{type}_{category}_{gender}_{slot}
```

| Part | Values |
|---|---|
| `status` | `current` or `next` |
| `type` | `oneday` or `stage` |
| `category` | `wt`, `1pro`, `2pro`, … |
| `gender` | `men` or `women` |
| `slot` | `1`, `2`, … |

**Examples:**

| Sensor | Meaning |
|---|---|
| `sensor.current_road_oneday_wt_men_1` | WorldTour men's one-day classic happening today |
| `sensor.current_road_stage_wt_men_1` | WorldTour men's stage race currently in progress |
| `sensor.next_road_oneday_wt_women_1` | Next upcoming WorldTour women's one-day race |
| `sensor.next_road_stage_1pro_men_2` | Second upcoming 1.Pro men's stage race |

A slot with no race assigned has state `unknown`.

### Sensor attributes

| Attribute | Description |
|---|---|
| `race_name` | Race name in your HA language |
| `category` | UCI category (`WT`, `1.Pro`, `2.Pro`, …) |
| `gender` | `men` or `women` |
| `race_type` | `one_day` or `stage_race` |
| `start_date` | ISO date (YYYY-MM-DD) |
| `end_date` | ISO date (YYYY-MM-DD) |
| `days_remaining` | Days left in a stage race (only on `current_road_stage_*`) |

---

## Installation

### Manual

Copy the `custom_components/pro_road_cycling` directory to your HA `config/custom_components/` folder and restart.

### HACS

Add this repository as a custom repository in HACS, install **Pro Road Cycling Sensor**, restart Home Assistant, then go to **Settings → Integrations → Add Integration** and search for *Pro Road Cycling Sensor*.

---

## Configuration

The setup screen has no required fields. Click **Submit** to activate the integration.

---

## Automation examples

### Example 1 — Daily briefing: today's races and what's coming up

Announces all races happening today, followed by the three most imminent upcoming races.

```yaml
alias: Cycling daily briefing
trigger:
  - platform: time
    at: "07:00:00"
action:
  - action: notify.mobile_app_my_phone
    data:
      title: "🚴 Cycling update"
      message: >
        {%- set current = states.sensor
            | selectattr('entity_id', 'match', '^sensor\\.current_road_')
            | rejectattr('state', 'in', ['unknown', 'unavailable'])
            | list -%}
        {%- set next_races = states.sensor
            | selectattr('entity_id', 'match', '^sensor\\.next_road_')
            | rejectattr('state', 'in', ['unknown', 'unavailable'])
            | sort(attribute='state') | list -%}

        {%- if current %}
        Vandaag op de fiets:
        {%- for s in current %}
        • {{ state_attr(s.entity_id, 'race_name') }}
          {%- if s.state | int > 0 %} (nog {{ s.state }} dag{{ 'en' if s.state | int != 1 else '' }}){% endif %}
        {%- endfor %}
        {%- else %}
        Vandaag geen wedstrijden.
        {%- endif %}

        {%- set shown = namespace(names=[]) %}
        {%- set upcoming_text = namespace(lines=[]) %}
        {%- for s in next_races %}
          {%- set name = state_attr(s.entity_id, 'race_name') %}
          {%- if name not in shown.names and upcoming_text.lines | length < 3 %}
            {%- set shown.names = shown.names + [name] %}
            {%- set days = s.state | int %}
            {%- set line = '• ' ~ name ~ ' over ' ~ days ~ ' dag' ~ ('en' if days != 1 else '') %}
            {%- set upcoming_text.lines = upcoming_text.lines + [line] %}
          {%- endif %}
        {%- endfor %}
        {%- if upcoming_text.lines %}

        Aankomend:
        {{ upcoming_text.lines | join('\n') }}
        {%- endif %}
```

---

### Example 2 — Today's races, or next upcoming if nothing today

```yaml
alias: Cycling status
trigger:
  - platform: time
    at: "08:00:00"
action:
  - action: notify.mobile_app_my_phone
    data:
      message: >
        {%- set current = states.sensor
            | selectattr('entity_id', 'match', '^sensor\\.current_road_')
            | rejectattr('state', 'in', ['unknown', 'unavailable'])
            | list -%}
        {%- if current %}
          {%- if current | length == 1 %}
        Vandaag is er {{ state_attr(current[0].entity_id, 'race_name') }}.
          {%- else %}
        Vandaag zijn er {{ current | length }} wedstrijden:
            {%- for s in current %}
        • {{ state_attr(s.entity_id, 'race_name') }}
            {%- endfor %}
          {%- endif %}
        {%- else %}
          {%- set next_s = states.sensor
              | selectattr('entity_id', 'match', '^sensor\\.next_road_')
              | rejectattr('state', 'in', ['unknown', 'unavailable'])
              | sort(attribute='state')
              | first | default(none) %}
          {%- if next_s %}
            {%- set days = next_s.state | int %}
        Vandaag geen wedstrijd.
        Volgende: {{ state_attr(next_s.entity_id, 'race_name') }} over {{ days }} dag{{ 'en' if days != 1 else '' }}.
          {%- else %}
        Geen wielerwedstrijden gepland.
          {%- endif %}
        {%- endif %}
```

---

### Example 3 — WorldTour men: today's race or next upcoming

Reports today's WT men's race(s), including days remaining for stage races. Falls back to the next upcoming race if nothing is on today.

```yaml
alias: WT men cycling update
trigger:
  - platform: time
    at: "07:00:00"
action:
  - action: notify.mobile_app_my_phone
    data:
      message: >
        {%- set current = states.sensor
            | selectattr('entity_id', 'match', '^sensor\\.current_road_.*_wt_men_')
            | rejectattr('state', 'in', ['unknown', 'unavailable'])
            | list -%}
        {%- if current | length == 1 %}
          {%- set s = current[0] %}
          {%- set days = s.state | int %}
        Today the {{ state_attr(s.entity_id, 'race_name') }} is on
          {%- if state_attr(s.entity_id, 'race_type') == 'stage_race' %}, {{ days }} day{{ 's' if days != 1 else '' }} remaining{% endif %}.
        {%- elif current | length > 1 %}
        Today there are {{ current | length }} WT men's races:
          {%- for s in current %}
            {%- set days = s.state | int %}
        • {{ state_attr(s.entity_id, 'race_name') }}
            {%- if state_attr(s.entity_id, 'race_type') == 'stage_race' %} ({{ days }} day{{ 's' if days != 1 else '' }} remaining){% endif %}
          {%- endfor %}
        {%- else %}
          {%- set upcoming = states.sensor
              | selectattr('entity_id', 'match', '^sensor\\.next_road_.*_wt_men_')
              | rejectattr('state', 'in', ['unknown', 'unavailable'])
              | list %}
          {%- set ns = namespace(best=none, best_days=9999) %}
          {%- for s in upcoming %}
            {%- set d = s.state | int %}
            {%- if d < ns.best_days %}
              {%- set ns.best = s %}
              {%- set ns.best_days = d %}
            {%- endif %}
          {%- endfor %}
          {%- if ns.best %}
            {%- set days = ns.best_days %}
        The next WT men's race is {{ state_attr(ns.best.entity_id, 'race_name') }} in {{ days }} day{{ 's' if days != 1 else '' }}.
          {%- else %}
        No upcoming WT men's races scheduled.
          {%- endif %}
        {%- endif %}
```

---

## Race calendar

The integration ships with a bundled `cycling_races.json` that contains the race calendar for the current season. This file is maintained in the repository and covers UCI WorldTour, UCI Women's WorldTour, UCI ProSeries and UCI Women's ProSeries races.

### Something missing or incorrect?

If a race is missing, has wrong dates, or is categorised incorrectly, feel free to open a pull request to fix it. The file lives at `custom_components/pro_road_cycling/cycling_races.json` in this repository. Each entry follows this structure:

```json
{
  "name": {
    "en": "Tour de France",
    "nl": "Ronde van Frankrijk",
    "fr": "Tour de France"
  },
  "category": "WT",
  "gender": "men",
  "type": "stage_race",
  "start_date": "2026-07-04",
  "end_date": "2026-07-26"
}
```

Race names can include translations for any of the supported languages: `en`, `nl`, `fr`, `de`, `it`, `es`, `da`, `nb`, `pt`. Missing translations fall back to `en`.

### Updating for a new season

The calendar will be updated in this repository at the start of each new season. After pulling the latest version, reload the integration via **Settings → Integrations → Pro Road Cycling Sensor → Reload**.

---

## Supported languages

Race names are available in: **English**, **Dutch**, **French**, **German**, **Italian**, **Spanish**, **Danish**, **Norwegian** and **Portuguese**. The integration uses whichever language is set in your Home Assistant configuration.

---

## License

MIT
