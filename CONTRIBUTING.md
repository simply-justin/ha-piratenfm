# Contributing

Thanks for helping out! This guide covers how the code is organised, how to run it locally and
what a good pull request looks like.

## Ground rules

- **Safety first.** This integration deletes things from someone's Music Assistant library. Any
  change that touches adding, renaming or removing radios needs a test that proves unrelated radios
  are left alone. See `tests/test_sync.py` for examples.
- **No invented APIs.** If you use a new Music Assistant command, link to the line in the
  [server source](https://github.com/music-assistant/server) that defines it in your PR.
- **Keep it small.** Prefer a few clear lines over a new abstraction. No new runtime dependencies
  unless they are clearly needed.
- Be kind in issues and reviews.

## Project layout

```
custom_components/piratenfm/
├── __init__.py          Setup/unload, wiring, the remove_managed_stations service
├── const.py             Domain, option keys and defaults
├── piratenfm.py         Piraten.FM HTTP client + validation of untrusted input
├── music_assistant.py   Thin adapter over music-assistant-client (list/upsert/remove radios)
├── storage.py           Persisted state (Store helper, versioned, atomic)
├── sync.py              The reconciliation algorithm (the core of the integration)
├── coordinator.py       DataUpdateCoordinator: schedules syncs, builds entity data
├── entity.py            Shared base entity / device info
├── sensor.py, button.py, switch.py   Entities
├── diagnostics.py       Redacted diagnostics download
├── config_flow.py       Setup, reauth, reconfigure and options flows
├── strings.json         Source strings; translations/en.json must be an exact copy
└── translations/        en.json, nl.json
tests/
├── fakes.py             In-memory fakes for Piraten.FM and the MA library
├── test_piratenfm.py    Parsing, validation, retries, stream probe
├── test_music_assistant.py  Adapter: identity matching, pagination, error mapping
├── test_sync.py         Reconciliation scenarios (add, rename, remove, failures, restarts…)
├── test_config_flow.py  Config/reauth/reconfigure/options flows
└── test_init.py         Full setup with entities, button, switches, service, diagnostics
```

### How the pieces fit together

```
Coordinator (timer / button)
        │
        ▼
StationSynchronizer.async_sync()      ← holds a lock: never two syncs at once
        │
        ├── PiratenFmClient.async_get_stations()     (fails → nothing changes)
        ├── async_connect() → MusicAssistantLibrary  (fails → nothing changes)
        └── _Run
              1. reconcile_with_library()  resolve library IDs, finish interrupted ops
              2. apply_active()            add / rename stations that are on air
              3. apply_absent()            count misses, remove expired managed stations
        │
        ▼
SyncStore.async_save()                ← atomic write
```

Key ideas worth knowing before changing `sync.py`:

- **Identity is the stream URL.** Music Assistant's builtin provider uses the stream URL as the
  item ID, so `https://piraten.fm/stations/<id>/listen/mp3` ties a library radio to a station.
  Names are never used for matching.
- **Ownership.** `managed_by_integration` is only set after our own add succeeded (or after a
  `pending: "add"` marker is found to have succeeded). Only managed radios are renamed or removed.
- **Write-ahead markers.** Before an add or remove, `pending` is saved. Step 1 of the next sync
  resolves it from the live library, which makes interrupted syncs safe.
- **Abort means no change.** If Music Assistant disconnects or the task is cancelled, the
  in-memory state is thrown away and reloaded from disk.

## Development setup

You need Python **3.13** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/simply-justin/ha-piratenfm.git
cd ha-piratenfm
uv sync --group dev
```

### Checks (the same ones CI runs)

```bash
uv run pytest                     # tests
uv run pytest --cov=custom_components.piratenfm --cov-report=term-missing
uv run ruff check .               # lint
uv run ruff format .              # format
uv run mypy                       # strict type checking
```

The tests use `pytest-homeassistant-custom-component`, which starts a real in-memory Home Assistant
core. All network access is mocked: you do **not** need Home Assistant, Music Assistant or internet
access to run them.

CI also runs **hassfest** and the **HACS** validator (`.github/workflows/validate.yml`). They need
Docker or GitHub Actions, so run them by pushing a branch.

### Trying it in a real Home Assistant

The quickest way is a throwaway Home Assistant in a virtualenv or container, with this repository's
`custom_components/piratenfm` linked into its `config/custom_components/`. `config/` is
git-ignored. Turn on debug logging:

```yaml
logger:
  logs:
    custom_components.piratenfm: debug
```

## Making changes

### Writing tests

- New behaviour in `sync.py` needs a scenario in `tests/test_sync.py`. The `FakeLibrary` in
  `tests/fakes.py` can make adds and removes fail (`fail_upsert`, `fail_remove`), go offline
  (`available = False`) or be interrupted (`hook`).
- Tests must not depend on timing or the network. Patch `asyncio.sleep` where retries are involved.

### Strings and translations

- Add user-facing text to `strings.json`, then copy it to `translations/en.json`
  (`cp custom_components/piratenfm/strings.json custom_components/piratenfm/translations/en.json`).
- Add the Dutch translation to `translations/nl.json`. If you don't speak Dutch, leave the key out
  and mention it in the PR; Home Assistant falls back to English.

### Changing the stored state

If you add, rename or remove fields in `TrackedStation` or `SyncState`:

1. Bump `STORAGE_MINOR_VERSION` (compatible additions) or `STORAGE_VERSION` (breaking changes) in
   `storage.py`.
2. Handle the old format in `_MigratingStore._async_migrate_func`.
3. Add a test that loads the old format.

### Commit messages and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat: …`, `fix: …`, `docs: …`,
  `test: …`, `refactor: …`, `chore: …`.
- One topic per PR. Describe **what** changed and **why**, and how you tested it.
- All CI checks must pass.

## Releasing (maintainers)

1. Update `version` in `custom_components/piratenfm/manifest.json` and in `pyproject.toml`.
2. Commit as `chore: release vX.Y.Z`, tag `vX.Y.Z` and push the tag.
3. Create a GitHub release from the tag. HACS picks up new releases automatically.

## Reporting bugs

Open an issue and include:

- Home Assistant, Music Assistant and integration versions.
- The **Last sync status** state and its attributes.
- Diagnostics (**⋮ → Download diagnostics**; connection details are already redacted).
- Debug logs around the problem.

Report security problems privately through GitHub's **Report a vulnerability** button, not in a
public issue.
