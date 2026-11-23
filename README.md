<div align="center">

# Piraten.FM for Home Assistant

**Every Dutch pirate radio station that is on air on [Piraten.FM](https://piraten.fm),
in your Music Assistant library, kept up to date automatically.**

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![CI](https://github.com/simply-justin/ha-piratenfm/actions/workflows/ci.yml/badge.svg)](https://github.com/simply-justin/ha-piratenfm/actions/workflows/ci.yml)
[![Validate](https://github.com/simply-justin/ha-piratenfm/actions/workflows/validate.yml/badge.svg)](https://github.com/simply-justin/ha-piratenfm/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

> [!NOTE]
> This is an unofficial, community-maintained project. It is not affiliated with, endorsed by or
> supported by Piraten.FM, Music Assistant or Home Assistant.

## Highlights

- **Hands-off.** New stations show up in Music Assistant within minutes of going on air. Stations
  that go off air are removed after three missed syncs.
- **Safe by design.** The integration only renames or removes radios it created itself, matched on
  the exact stream URL. Your own radios are never touched, and a failed or empty response never
  removes anything.
- **Direct playback.** Music Assistant streams straight from Piraten.FM. No proxy, no extra
  container, no YAML.
- **Readable names and artwork.** Stations appear as `Radio Dop 2 Dop • 97.00 MHz • Gelselaar`, with
  the Piraten.FM logo as cover.
- **Crash-safe.** State is saved atomically, and an interrupted sync is finished correctly on the
  next run.

## Contents

- [Quick start](#quick-start)
- [What you get](#what-you-get)
- [Requirements](#requirements)
- Installation: [HACS](#installation-with-hacs) · [Manual](#manual-installation)
- [Configuration](#configuration)
- [Music Assistant authentication](#music-assistant-authentication)
- How it works: [Synchronization](#how-synchronization-works) ·
  [Removing offline stations](#how-offline-stations-are-removed) ·
  [Stored state and recovery](#stored-state-and-recovery)
- [Troubleshooting](#troubleshooting)
- [Logs and diagnostics](#logs-and-diagnostics)
- [Security](#security) · [Known limitations](#known-limitations)
- [Uninstalling](#uninstalling)
- [Contributing](#contributing)

## Quick start

1. Add this repository to HACS:

   [![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=simply-justin&repository=ha-piratenfm&category=integration)

2. Click **Download**, then restart Home Assistant.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up Piraten.FM.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=piratenfm)

4. Enter your Music Assistant URL and a [long-lived access token](#music-assistant-authentication).

The first sync starts right away. Your stations appear in Music Assistant under **Radio**.

## What you get

Every sync (by default every 5 minutes), the integration:

1. Fetches the stations that are broadcasting from `https://piraten.fm/stations/`.
2. Adds new stations to Music Assistant as radio stations.
3. Updates a station's name when its name, frequency or location changes.
4. Removes stations that have been off air for 3 successful syncs in a row.

Home Assistant gets one device, **Piraten.FM**, with these entities:

| Entity | Type | Description |
| --- | --- | --- |
| Active stations | Sensor | Number of stations on air. The `stations` attribute lists each station's ID, name, frequency, location, listeners, now playing and stream URL. |
| Managed stations | Sensor | Number of radios this integration created in Music Assistant. |
| Last successful sync | Sensor | When the last complete sync finished. |
| Last sync status | Sensor | `success`, `partial`, `empty_response`, `piratenfm_unavailable`, `music_assistant_unavailable` or `auth_failed`. The attributes hold the counters of the last sync. |
| Last sync duration | Sensor (diagnostic) | How long the last sync took, in seconds. |
| Synchronize now | Button | Runs a sync immediately. |
| Automatic synchronization | Switch | Turns the scheduled sync on or off. |
| Automatic removal of offline stations | Switch | Turns removal of off-air stations on or off. |

There is no entity per station on purpose. The station list lives in the attributes of
**Active stations**, and Music Assistant is where you play them.

## Requirements

| Component | Version |
| --- | --- |
| Home Assistant | 2025.2 or newer |
| Music Assistant server | A 2.x server that supports the `music/library/add_item`, `music/library/remove_item` and `music/radios/library_items` commands |
| `music-assistant-client` | 1.3.3 or newer (installed automatically) |

> [!IMPORTANT]
> The Music Assistant behaviour was verified against the Music Assistant server source code and is
> covered by automated tests with a simulated server. It has not yet been tested end-to-end against
> every server version. If something does not work with yours, please
> [open an issue](https://github.com/simply-justin/ha-piratenfm/issues/new/choose).

## Installation with HACS

1. In Home Assistant, open **HACS**, click **⋮** in the top-right corner and choose
   **Custom repositories**. (The [quick start](#quick-start) button does this for you.)
2. Enter `https://github.com/simply-justin/ha-piratenfm`, choose the type **Integration** and click
   **Add**.
3. Search HACS for **Piraten.FM**, open it and click **Download**.
4. Restart Home Assistant and continue with [Configuration](#configuration).

To update, open **Piraten.FM** in HACS, choose **⋮ → Update information**, download the new version
and restart Home Assistant.

## Manual installation

1. Download this repository (**Code → Download ZIP**) or clone it.
2. Copy `custom_components/piratenfm` into the `custom_components` folder of your Home Assistant
   configuration directory, so that `<config>/custom_components/piratenfm/manifest.json` exists.
3. Restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration** and choose **Piraten.FM**.

| Field | Description |
| --- | --- |
| Music Assistant URL | The address of the Music Assistant web interface, for example `http://homeassistant.local:8095`. If the official Music Assistant integration is set up, this is filled in for you. |
| Access token | A Music Assistant long-lived access token. See [Music Assistant authentication](#music-assistant-authentication). |

The connection is tested before anything is saved. You can add one entry per Music Assistant server.
To change the URL or token later, open the integration and choose **⋮ → Reconfigure**.

### Options

Open the integration and click **Configure**. Changes apply immediately.

| Option | Default | Description |
| --- | --- | --- |
| Automatic synchronization | On | Sync on a schedule. When off, only the **Synchronize now** button (or an automation that presses it) starts a sync. |
| Sync interval | 300 seconds | Time between syncs, from 60 to 86,400 seconds. |
| Automatically remove offline stations | On | Remove managed stations that have gone off air. |
| Missed syncs before removal | 3 | How many successful syncs in a row a station must be missing before it is removed (1 to 50). |
| Show frequency in station name | On | Adds the frequency: `Name • 97.00 MHz`. |
| Show location in station name | On | Adds the location: `Name • … • Gelselaar`. |

Streams are always MP3, as that is the only stream format Piraten.FM offers.

## Music Assistant authentication

Music Assistant servers with authentication enabled (API schema 28 and newer) require a token:

1. Open the Music Assistant web interface.
2. Go to **Settings → Profile** and create a **long-lived access token**.
3. Paste the token into the **Access token** field.

The token's user must be allowed to edit the library, because the integration adds and removes
radios. Leave the field empty only for older servers or servers without authentication.

The token is stored in the Home Assistant config entry, like the credentials of any other
integration. It is never logged and is redacted from diagnostics. If Music Assistant rejects the
token later, Home Assistant shows a **Reauthenticate** notification where you can enter a new one.

## How synchronization works

Only one sync runs at a time. A sync requested while another is running is skipped.

1. **Fetch** `https://piraten.fm/stations/`, with a 15-second timeout. A failed request is retried
   up to twice, after 2 and then 4 seconds.
2. **Validate** the response. It must be a JSON array, and station IDs must be 1 to 32 letters or
   digits. Entries with any other ID are dropped, and if half or more of the entries are invalid,
   the whole response is rejected. Text is trimmed (the live API sends values like
   `"Gelselaar\r"`).
3. **Connect** to Music Assistant. Every sync opens a fresh, short-lived connection, so a restart
   of Music Assistant needs no special handling.
4. **Reconcile with the library.** The integration lists the library radios and picks out the ones
   whose stream URL is exactly a Piraten.FM stream URL. Library IDs always come from this live
   list; IDs stored earlier are never trusted on their own.
5. **Add** stations that are not in the library yet. Before adding, a quick check reads at most
   4 KB of the stream to confirm it is audio. If the check fails, the station is added on a later
   sync. A failed check never counts as the station being off air.
6. **Update** stations whose name, frequency or location changed, or that do not have the cover
   yet.
7. **Count absences** and remove stations that passed the threshold. See
   [How offline stations are removed](#how-offline-stations-are-removed).
8. **Save** the new state.

### Which radios the integration manages

A radio is **managed** only if the integration created it. Radios are matched on their exact
stream URL, never on their name:

- A radio with a different stream URL is never touched, even if it has the same name.
- If you added a Piraten.FM stream yourself, the integration recognises it and does not add a
  duplicate. It never renames or removes that radio. It is counted as an *unmanaged matching
  station* in the attributes of **Managed stations**.

## How offline stations are removed

A managed station is removed once it has been missing from **N successful syncs in a row**. The
default of 3 equals 15 minutes at the default interval.

A sync counts towards removal only if Piraten.FM returned a valid, non-empty station list **and**
the Music Assistant library could be read. The following never count as a missed sync and never
cause a removal:

- Piraten.FM cannot be reached, or returns an HTTP error, a timeout or invalid JSON.
- Piraten.FM returns an **empty** list. That cannot be told apart from an outage, so the sync is
  skipped with status `empty_response`.
- Music Assistant cannot be reached or drops the connection.
- The sync is interrupted, for example by a Home Assistant restart.

If a station comes back on air before it reaches the threshold, its counter resets to 0. If it
comes back after it was removed, it is added again.

With **Automatic removal** turned off, absences are still counted, but nothing is removed.

## Stored state and recovery

State is stored with Home Assistant's storage helper in `<config>/.storage/piratenfm.<entry_id>`.
The format is versioned, so it can be migrated by future releases, and every write is atomic
(written to a temporary file, then renamed). Per station it stores:

```json
{
  "F9O5Z8": {
    "stream_url": "https://piraten.fm/stations/F9O5Z8/listen/mp3",
    "music_assistant_library_id": "123",
    "name": "Verzet Radio",
    "frequency": "94.30 MHz",
    "location": "Vriezenveen",
    "display_name": "Verzet Radio • 94.30 MHz • Vriezenveen",
    "cover_url": "https://piraten.fm/icons/Icon-512.png",
    "last_seen": "2026-11-23T10:00:00+00:00",
    "missing_count": 0,
    "managed_by_integration": true,
    "pending": null
  }
}
```

The time of the last successful sync is stored next to it.

Before every add or remove, the integration saves a `pending` marker. If Home Assistant stops
halfway through a sync, the next sync resolves the marker against the live library:

| What happened | What the next sync does |
| --- | --- |
| The add reached Music Assistant, but the result was not saved | Finds the radio by its stream URL and marks it as managed. No duplicate is created. |
| The add never reached Music Assistant | Clears the marker and adds the station again. |
| The removal finished, but the result was not saved | Sees that the radio is gone and forgets the station. |
| The removal did not finish | Tries the removal again. |

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| *Cannot connect to Music Assistant* | Make sure Home Assistant can reach the URL. Use the port of the Music Assistant web interface (`8095` by default), not the stream port. |
| *Invalid token*, or a reauthentication notification | Create a new long-lived token in Music Assistant, for a user that is allowed to edit the library. |
| Status `piratenfm_unavailable` | Piraten.FM is down or refused the request. Nothing is changed, and the next sync tries again. |
| Status `empty_response` | Piraten.FM returned no stations. Nothing is removed. |
| Status `partial` | Some stations could not be added or removed. The `failures` attribute of **Last sync status** lists them. They are retried on the next sync. |
| A station does not appear | Check the `deferred` counter of **Last sync status**. If the stream failed the quick check, the station is added once the stream responds. |
| A radio I added myself is not renamed or removed | This is intended. The integration only manages radios it created. |
| I renamed a managed radio in Music Assistant | Your name is kept until the station's name, frequency or location changes on Piraten.FM. |
| I deleted a managed radio in Music Assistant | It is added again on the next sync while the station is on air. Turn off **Automatic synchronization** or remove the integration to prevent that. |

Still stuck? [Open an issue](https://github.com/simply-justin/ha-piratenfm/issues/new/choose) and
include the diagnostics described below.

## Logs and diagnostics

Turn on debug logging from the integration page (**⋮ → Enable debug logging**), or in
`configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.piratenfm: debug
```

Every sync logs one summary line, for example:

```text
Piraten.FM sync success: added=1 updated=0 removed=0 deferred=0 failed=0
```

To download diagnostics, open the integration and choose **⋮ → Download diagnostics**. The file
contains the options, the last sync result and the stored station state. The Music Assistant URL
and token are redacted.

## Security

- Everything Piraten.FM returns is treated as untrusted. Station IDs must match
  `^[A-Za-z0-9]{1,32}$` before they are used in a URL, so a response cannot make the integration
  contact another host or path. Redirects are not followed.
- All requests to Piraten.FM use HTTPS. The only other host the integration contacts is the Music
  Assistant URL you configured.
- Nothing is ever removed based on a name. A removal requires both a record that the integration
  created the radio and an exact stream-URL match in the live library.
- The access token is never logged and is redacted from diagnostics.
- The phone numbers in the Piraten.FM API are ignored and never stored.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Known limitations

- **Updating a radio replaces its library record.** Music Assistant's dedicated update command
  (`music/radios/update`) requires admin rights. To work with a normal token, the integration
  updates a radio by adding the same stream again with `overwrite_existing=True`. Music Assistant
  matches it to the existing radio (same library ID, no duplicate) but replaces its stored fields,
  including the cover.
- **One cover for all stations.** Piraten.FM has no per-station artwork, so every managed radio
  gets the Piraten.FM app icon (`https://piraten.fm/icons/Icon-512.png`), which Music Assistant
  loads directly from Piraten.FM. Artwork you set on a managed radio yourself is replaced whenever
  that station is updated.
- **Listener count and now playing** are shown only in Home Assistant, in the attributes of
  **Active stations**. Music Assistant has no suitable radio field for them.
- The format of a non-empty `nowPlaying` value has not been observed in the live API. Plain strings
  and `{artist, title}` objects are both supported.
- If every station goes off air at the same time, the API returns an empty list, which is ignored
  for safety. The radios then stay in Music Assistant until at least one station is back on air.
- Piraten.FM blocks some HTTP clients, such as plain `curl`. Home Assistant's HTTP client is
  accepted. If that changes, syncs fail safely with status `piratenfm_unavailable`.

## Uninstalling

Removing the integration **does not** remove its radios from Music Assistant. It should not delete
data in another system without being asked.

To remove the radios as well, do this **before** you remove the integration:

1. Turn off **Automatic synchronization**, so the radios are not added back while you finish.
2. Go to **Developer tools → Actions**, choose **Piraten.FM: Remove managed stations**, select
   your entry and click **Perform action**. Only radios the integration created are removed. The
   response shows how many were removed.
3. Remove the integration in **Settings → Devices & services**. This also deletes its stored
   state.
4. Remove Piraten.FM in HACS and restart Home Assistant.

If you already removed the integration, its stored state is gone. Delete the radios manually in
Music Assistant; their stream URLs start with `https://piraten.fm/stations/`.

## Contributing

Bug reports, ideas and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains how
the code is organised, how to run the tests and what makes a good pull request. In short:

```bash
uv sync --group dev
uv run pytest                 # no network, Home Assistant or Music Assistant needed
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

See [CHANGELOG.md](CHANGELOG.md) for the release history.

## License

Released under the [MIT License](LICENSE).
