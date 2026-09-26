# Dates and time zones

Read this before writing or reviewing Palmate low-code that reads, stores,
compares, schedules, or prints a date or a time. It condenses the "Dates and
time zones" section of the checkout guide, the `AGENTS.md` (identical to
`CLAUDE.md`) at the root of every checkout, which the CLI package also ships
in its `AGENTS.md` asset, and adds the runtime details the timezone release
settled after that section was written. `builtins.py` in the checkout is the
authority for exact runtime names and signatures; when it and this file
differ, `builtins.py` wins.

- Store and compare instants; turn them into wall clocks only to show them,
  with the zone named. An instant is one point in time
  (`2026-09-22T07:00:00.000Z`); a wall clock (`09:00`, `2026-09-22`, a cron)
  means nothing without a zone.
- Zones: project (`timezone_name`, set in the project's "Region and time"
  settings; the business clock), person (`Account.timezone`, what the
  dashboard shows one viewer; `livechat/body.py` returns instants and the
  dashboard formats them in that zone), platform (`settings.TIME_ZONE`,
  billing and platform jobs), customer (the zone the webchat reported for the
  session, `session.customer_timezone`, or `None`; data, not a setting).
- Never create naive datetimes: `datetime.now()`, `date.today()`,
  `datetime.utcnow()`, `datetime.fromtimestamp(ts)` without `tz=` and
  `strptime` without `%z` give the worker's platform clock or no zone at all.
  `session.now()` is an aware UTC instant; its `.hour` and `.date()` are UTC,
  not the project's.
- Project clock (timezone release): `session.project_timezone` (IANA name),
  `session.project_now()` (aware, its `tzinfo` is the project's `ZoneInfo`),
  `session.local_day_range(day)`, `session.to_project_time(instant)` (aware,
  in the project zone; `zoneinfo` cannot be imported),
  `session.customer_timezone` and `session.to_customer_time(instant)` (aware,
  in the customer's zone, or `None` when no valid zone was reported).
- The six names exist in scripts that run for a conversation (bot flows,
  utilities, `livechat/body.py`), in MCP tool calls, and in statistics
  figures, report generators and livechat assignment modules; the last three
  have no conversation, so `session.customer_timezone` and
  `session.to_customer_time()` are always `None` there. Automations,
  integrations, product data sources, announcement filters and single-run
  background modules do not have them yet.
- In a conversation, a designer variable or database named `project_timezone`
  or `customer_timezone` is still read first. One named `project_now`,
  `local_day_range`, `to_project_time` or `to_customer_time` is hidden behind
  the function of that name: read it with `session.get_variable("<name>")` or
  rename it.
- A local day lasts 23, 24 or 25 hours. `session.local_day_range(day)` takes a
  `date` or `YYYY-MM-DD` (a datetime raises `TypeError`; for the day of an
  instant pass `session.to_project_time(instant).date()`) and returns the
  half-open UTC day: read `.start` and `.end` (or `[0]` and `[1]`), query
  `start <= t < end`, never add 24 hours to a midnight, and count days on the
  calendar (`day - timedelta(days=6)`). Mongo `$dateToString`, `$hour`,
  `$minute` and `$dayOfWeek` cut in UTC unless given
  `"timezone": session.project_timezone`.
- The low-code runtime cannot unpack:
  `start, end = session.local_day_range(day)` and
  `for key, value in d.items():` stop the script. It also ignores f-string
  format specs (`f"{local:%H:%M}"` prints the whole datetime): format with
  `local.strftime("%H:%M")`.
- Parse API and provider dates with a parser (`datetime.fromisoformat`), never
  by slicing, length or digit count; a result without `tzinfo` is a wall clock,
  not an instant. Take an epoch's unit from the provider's documentation,
  never from the size of the number.
- API instants become RFC 3339 UTC with milliseconds
  (`2026-09-22T07:00:00.000Z`) when the wire flag is on and keep legacy offsets
  (`+0300`, `+03:00`) until then; every payload with a wall clock carries a
  `timezone` field. Send aware values: older endpoints read a zone-less value
  in the current zone and newer ones refuse it.
- Values the runtime hands to scripts keep their shape:
  `session.operating_state` `evaluated_at`/`next_open_at` and
  `session.next_open_at` stay project-zone `isoformat()` strings; ticket
  `assigned_time`/`resolved_time` are UTC `...Z` text; dates read back from a
  chatbot database collection are zone-less UTC text (add
  `tzinfo=timezone.utc`); an automation's `event_data["scheduled_at"]` and
  `event_data["executed_at"]` carry their UTC offset.
- Webchat date answers keep `machine_data` as before: the picked day's UTC
  midnight for `format: "date"`, the real instant for `datetime` and `time`
  (its UTC hour is not the time the customer picked). A newer webchat adds
  `date_input` with `kind`, `timezone`, `date` (`YYYY-MM-DD`), `time`
  (`HH:mm`), `instant` (`...Z`), or `from` and `to` for a range, only the keys
  its `kind` uses. Older webchats and other channels send none, so test for
  it first; use `instant` for the moment and `date` and `time` for what the
  customer saw. Teams date answers arrive as `YYYY-MM-DD`.
- `send_time_picker`: give each slot's `startTime` an offset or `Z`, or send
  epoch seconds; zone-less text is read as a wall clock of the project zone
  on every channel. The reservation helpers speak the project's wall clock
  (`DD/MM/YYYY HH:MM`, with a `timezone` field); a time that happens twice
  carries its UTC offset, so send it back as you got it.
- The project zone runs working hours and `session.operating_state`, sending
  windows, reservation slots, and the crons of periodic announcements,
  automations, statistics generators, product data sources and knowledge web
  pages. Statistics buckets are cut at the platform zone's midnight, and new
  campaign quota windows in the platform zone, until the deployment moves
  them to the project zone.
- The platform zone runs `cron_schedule` in `billing/generator.yaml`
  (superuser); its default `0 3 1 * *` is 03:00 platform time on the 1st.
- Write crons in project local time and keep them out of the hours in which
  daylight saving time changes the clocks (01:00-02:00 in Europe/London,
  02:00-03:00 in Europe/Berlin). The run already scheduled when a zone
  changes keeps its old instant; later runs follow the new zone. Random or
  hashed cron values (`R`, `H`) are not supported (such a cron fails at its
  next run), and a statistics report generator's runs must stay at least 3
  hours apart.
- Holidays come from the project's holiday calendar (country plus optional
  subdivision) once the deployment switches its holiday source; until then
  the Turkish official holidays apply to every project. Never hardcode
  holiday dates; read `session.operating_state` and `session.next_open_at`.
- A time in a text for a customer names its zone: project time first
  (`session.to_project_time(instant)` with `session.project_timezone`), then
  the customer's own time next to it when `session.to_customer_time(instant)`
  is not `None` and its offset differs.
- `get_platform_message(..., platform_created_at=...)` takes an aware
  `datetime`, an RFC 3339 string with an offset or `Z`, or an epoch number
  with `platform_created_at_unit="unix_s"` or `"unix_ms"`. Zone-less text, a
  naive `datetime` or a `date` (its midnight) is read in the project zone with
  a warning in the script log; any other shape, and an epoch without its
  unit, raises an error that names the accepted forms.
- Provider-bound formats stay the provider's: send and read the format and unit
  its API documents, never the wire format.
- Stored zone aliases were rewritten to canonical names (`Turkey` and
  `Asia/Istanbul` became `Europe/Istanbul`, `Europe/Kiev` became
  `Europe/Kyiv`); compare zones by their canonical names.
- Once, after the timezone release is deployed, the first sync publishes one
  new revision on every branch (the managed references, plus
  `holiday_country` and `holiday_subdivision` in `project.yaml`). A checkout
  with uncommitted edits then gets `stale_branch_head` on commit: run
  `palmate pull` and re-apply the edits, as the CLI says.
