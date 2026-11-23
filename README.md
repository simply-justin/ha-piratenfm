# Piraten.FM for Home Assistant

Automatically keeps the **Music Assistant** radio library in sync with the Dutch pirate radio
stations that are on air on [Piraten.FM](https://piraten.fm).

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by Piraten.FM,
> Music Assistant, or Home Assistant.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Supported versions](#2-supported-versions)
3. [Installation via HACS](#3-installation-via-hacs)
4. [Manual installation](#4-manual-installation)
5. [Configuration](#5-configuration)
6. [Music Assistant authentication](#6-music-assistant-authentication)
7. [How synchronization works](#7-how-synchronization-works)
8. [How offline stations are removed](#8-how-offline-stations-are-removed)
9. [Persistent state and recovery](#9-persistent-state-and-recovery)
10. [Troubleshooting](#10-troubleshooting)
11. [Logs and diagnostics](#11-logs-and-diagnostics)
12. [Security and limitations](#12-security-and-limitations)
13. [Development and testing](#13-development-and-testing)
14. [Uninstalling and cleanup](#14-uninstalling-and-cleanup)

---

## 1. What it does

Every few minutes (default: 5) the integration:

1. Fetches the list of stations that are currently broadcasting from `https://piraten.fm/stations/`.
2. Adds new stations to Music Assistant as radio stations, named like
   `Radio Dop 2 Dop • 97.00 MHz • Gelselaar`.
3. Renames stations when their frequency, location or name changes.
4. Removes stations that have been off air for 3 successful syncs in a row.

Music Assistant plays the stream **directly** from Piraten.FM
(`https://piraten.fm/stations/<id>/listen/mp3`). There is no proxy, no extra container, no cron
job and no YAML.

In Home Assistant you get one device, **Piraten.FM**, with:

| Entity | Type | What it shows / does |
| --- | --- | --- |
| Active stations | sensor | Number of stations on air. The `stations` attribute lists id, name, frequency, location, listeners, now playing and stream URL. |
| Managed stations | sensor | Number of radios this integration created in Music Assistant. |
| Last successful sync | sensor | When the last complete sync finished. |
| Last sync status | sensor | `success`, `partial`, `empty_response`, `piratenfm_unavailable`, `music_assistant_unavailable` or `auth_failed`, plus counters in the attributes. |
| Last sync duration | sensor (diagnostic) | Seconds the last sync took. |
| Synchronize now | button | Runs a sync immediately. |
| Automatic synchronization | switch | Turns the periodic sync on or off. |
| Automatic removal of offline stations | switch | Turns removal on or off. |

There is deliberately no entity per station: the station list lives in the
**Active stations** attributes, and Music Assistant is where you actually play them.

## 2. Supported versions

| Component | Version |
| --- | --- |
| Home Assistant | 2025.2 or newer (tested with 2026.2) |
| Music Assistant server | A server that supports the `music/library/add_item`, `music/library/remove_item` and `music/radios/library_items` API commands, which recent 2.x servers do. Checked against the Music Assistant server source of November 2026. |
| `music-assistant-client` | 1.3.3 or newer (installed automatically; tested with 1.8.1) |

The Music Assistant behaviour was checked by reading the server source code and is covered by
mocked tests. It has **not** been tested end-to-end against a running Music Assistant server.
Please [open an issue](https://github.com/simply-justin/ha-piratenfm/issues) if something does not
work with your version.

## 3. Installation via HACS

1. In Home Assistant open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/simply-justin/ha-piratenfm` with the type **Integration**.
3. Search for **Piraten.FM** in HACS and click **Download**.
4. Restart Home Assistant.
5. Continue with [Configuration](#5-configuration).

## 4. Manual installation

1. Download the latest release (or clone this repository).
2. Copy `custom_components/piratenfm` to `<your config>/custom_components/piratenfm`.
   You should end up with `<config>/custom_components/piratenfm/manifest.json`.
3. Restart Home Assistant.

## 5. Configuration

Go to **Settings → Devices & services → Add integration → Piraten.FM**.

**Step 1: connect to Music Assistant**

| Field | Description |
| --- | --- |
| Music Assistant URL | For example `http://homeassistant.local:8095`. If the official Music Assistant integration is already set up, its URL is filled in for you. |
| Access token | A Music Assistant long-lived token (see [section 6](#6-music-assistant-authentication)). |

The integration tests the connection before saving. You can add one entry per Music Assistant
server.

**Options**: open the integration → **Configure**. They take effect immediately, without
reinstalling.

| Option | Default | Description |
| --- | --- | --- |
| Automatic synchronization | on | Run a sync on a schedule. When off, only the button (or an automation pressing it) syncs. |
| Sync interval | 300 s | Time between syncs (60 to 86400 seconds). |
| Automatically remove offline stations | on | Remove managed stations that have gone off air. |
| Missed syncs before removal | 3 | How many successful syncs in a row a station must be missing before it is removed. |
| Show frequency in station name | on | `Name • 97.00 MHz`. |
| Show location in station name | on | `Name • … • Gelselaar`. |

These two name options are the naming format. The stream format is always MP3, because that is
the only verified Piraten.FM stream endpoint.

To change the URL or token later, use **⋮ → Reconfigure** on the integration.

## 6. Music Assistant authentication

Music Assistant servers with authentication (API schema 28 and newer) require a token:

1. Open the Music Assistant web UI.
2. Go to **Settings → Profile** and create a **long-lived access token**.
3. Paste it in the **Access token** field.

The token must be allowed to **write to the library** (add and remove radios). If you leave the
field empty, the integration connects without a token. That only works on older servers or
servers without authentication.

The token is stored in the Home Assistant config entry, like every other integration's
credentials. It is never logged and is redacted from diagnostics. If Music Assistant rejects it
later, Home Assistant shows a **Reauthenticate** notification where you can enter a new one.

## 7. How synchronization works

Each sync runs these steps. Two syncs never run at the same time; a second request while one
is running is ignored.

1. **Fetch** `https://piraten.fm/stations/`. Timeout: 15 s. Up to 3 attempts, waiting 2 s
   and then 4 s between them.
2. **Validate**: the response must be a JSON array. Station IDs must be 1 to 32 letters or digits,
   and entries with any other ID are dropped. If half or more of the entries are invalid, the whole
   response is rejected. Text is trimmed (the live API sends e.g. `"Gelselaar\r"`).
3. **Connect** to Music Assistant. Each sync uses a fresh, short-lived connection, so a
   Music Assistant restart is simply picked up by the next sync.
4. **Reconcile with the library**: list the library radios and find the ones whose builtin stream
   URL is exactly a Piraten.FM stream URL. Library IDs always come from this list; IDs saved
   earlier are never trusted on their own.
5. **Add** stations that are not in the library yet. First, a light check fetches at most 4 KB of
   the stream with an HTTP `Range` request, to make sure it really is audio. If the check fails,
   the station is added on the next sync. A failed check never counts as the station being offline.
6. **Rename** stations whose name, frequency or location changed (see the limitation in
   [section 12](#12-security-and-limitations)).
7. **Count absences** and remove stations that are past the threshold ([section 8](#8-how-offline-stations-are-removed)).
8. **Save** the new state.

### Which radios the integration manages

A radio is **managed** only if the integration created it itself. Matching is done on the exact
stream URL, never on the name:

- A radio with a different stream URL is never touched, even if it has the same name.
- If you already added a Piraten.FM stream yourself, the integration sees it, does not add a
  duplicate, and **never renames or removes it**. It counts as an *unmanaged matching station*,
  shown in the attributes of **Managed stations**.

## 8. How offline stations are removed

A managed station is removed after it has been missing from **N successful syncs in a row**
(default N = 3, which is 15 minutes with the default interval).

A sync only counts towards removal if Piraten.FM returned a valid, non-empty list **and**
the Music Assistant library could be read. These never count as a missed sync, and never cause
removals:

- Piraten.FM cannot be reached, or returns an HTTP error, a timeout or invalid JSON.
- Piraten.FM returns an **empty** list. That cannot be told apart from an API glitch, so the sync is
  skipped with status `empty_response`.
- Music Assistant cannot be reached or drops the connection.
- The sync was interrupted (for example by a Home Assistant restart).

If a station comes back on air before it reaches the threshold, its counter goes back to 0. If it
comes back after it was removed, it is added again.

If you turn off **Automatic removal**, the counters keep running but nothing is removed.

## 9. Persistent state and recovery

The state is stored with Home Assistant's own storage helper in
`<config>/.storage/piratenfm.<entry_id>`. It is versioned so that it can be migrated later, and it
is written atomically: first to a temporary file, which is then renamed. For every station it
stores:

```json
{
  "F9O5Z8": {
    "stream_url": "https://piraten.fm/stations/F9O5Z8/listen/mp3",
    "music_assistant_library_id": "123",
    "name": "Verzet Radio",
    "frequency": "94.30 MHz",
    "location": "Vriezenveen",
    "display_name": "Verzet Radio • 94.30 MHz • Vriezenveen",
    "last_seen": "2026-11-23T10:00:00+00:00",
    "missing_count": 0,
    "managed_by_integration": true,
    "pending": null
  }
}
```

It also stores `last_successful_sync`.

**Crash safety.** Before every add or remove, the integration saves a `pending` marker. If Home
Assistant stops halfway through:

| What happened | What the next sync does |
| --- | --- |
| The add reached Music Assistant, but the result was not saved | Finds the radio by its stream URL and marks it as managed. No duplicate is created. |
| The add never reached Music Assistant | Clears the marker and adds the station again. |
| The removal finished, but the result was not saved | Sees the radio is gone and forgets the station. |
| The removal failed | Tries the removal again. |

## 10. Troubleshooting

| Symptom | What to check |
| --- | --- |
| *Cannot connect to Music Assistant* | Is the URL reachable from Home Assistant? Use the MA web UI port (default `8095`), not the stream port. |
| *Invalid token* or a reauthentication notification | Create a new long-lived token in Music Assistant. Make sure the user is allowed to edit the library. |
| Status `piratenfm_unavailable` | Piraten.FM is down or blocking requests. Nothing is changed; the integration retries on the next sync. |
| Status `empty_response` | Piraten.FM returned no stations. Nothing is removed. |
| Status `partial` | Some stations could not be added or removed. The `failures` attribute of **Last sync status** lists them, and they are retried on the next sync. |
| A station does not appear | Check the `deferred` counter. If its stream did not answer the light check, it is added once the stream works. |
| A station I added myself is not renamed or removed | That is intended: the integration only manages radios it created. |
| I renamed a managed station in MA | Your name is kept until the station's name, frequency or location changes on Piraten.FM. |
| I deleted a managed station in MA | It is added again on the next sync while it is on air. Turn off **Automatic synchronization**, or remove the integration, if you do not want that. |

## 11. Logs and diagnostics

Turn on debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.piratenfm: debug
```

or use **Enable debug logging** on the integration page. Each sync logs one summary line, for example:

```
Piraten.FM sync success: added=1 updated=0 removed=0 deferred=0 failed=0
```

To download diagnostics, open the integration, click **⋮ → Download diagnostics**. They contain the
options, the last sync result and the full station state. The Music Assistant URL and token are
redacted.

## 12. Security and limitations

**Security**

- Everything Piraten.FM returns is treated as untrusted. Station IDs are checked against
  `^[A-Za-z0-9]{1,32}$` before they are used in a URL, so a response cannot make the integration
  request any other host or path. Redirects are not followed.
- All Piraten.FM requests use HTTPS. The only other host the integration talks to is the Music
  Assistant URL you configured.
- Nothing is deleted based on a name. Removal requires both proof that the integration created the
  radio and an exact stream-URL match in the live library list.
- The token is never logged and is redacted from diagnostics.
- The station phone numbers in the Piraten.FM API are ignored and never stored.

**Limitations**

- **Renaming replaces the radio's library record.** Music Assistant has a dedicated
  `music/radios/update` command, but it needs admin (library-manage) rights. To work with a normal
  library-write token, the integration renames by re-adding the same stream with
  `overwrite_existing=True`. Music Assistant matches it to the existing radio (same library ID, no
  duplicate), but replaces its stored fields. Custom artwork you set on a managed radio may be
  replaced by Music Assistant's own metadata lookup.
- **Listener count and now playing** are only shown in Home Assistant, in the **Active stations**
  attributes. Music Assistant has no fitting radio field for them, so they are not written there.
- The shape of a non-empty `nowPlaying` has never been seen in the live API. Plain strings and
  `{artist, title}` objects are both handled.
- If every station really goes off air at once, the API returns an empty list, which is ignored for
  safety. The stations then stay in Music Assistant until at least one station is back on air.
- Piraten.FM blocks some HTTP clients (for example plain `curl`). Home Assistant's own HTTP client is
  accepted. If that ever changes, syncs fail safely with status `piratenfm_unavailable`.

## 13. Development and testing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. In short:

```bash
uv sync --group dev
uv run pytest            # all tests, no network or real servers needed
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

## 14. Uninstalling and cleanup

**Radios stay in Music Assistant when you remove the integration.** Removing an integration should
not delete things from another system without you asking.

To remove the radios as well, **before** uninstalling:

1. Go to **Developer tools → Actions**, choose **Piraten.FM: Remove managed stations**, pick your
   entry and run it. Only radios the integration created are removed; radios you added yourself
   are kept. The response lists how many were removed.
2. Turn off **Automatic synchronization**, so the radios are not added again before you finish.
3. Remove the integration in **Settings → Devices & services**. This also deletes its stored state.
4. In HACS, remove the repository, then restart Home Assistant.

If you already removed the integration, the stored state is gone. Delete the radios by hand in
Music Assistant: their stream URL starts with `https://piraten.fm/stations/`.

## License

[MIT](LICENSE)
