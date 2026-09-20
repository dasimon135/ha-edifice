# Changelog

## 0.2.0 - unreleased

### Added

- **Calendar** entity: the whole diary as all-day events on the day each item is due, past
  weeks included. On while something is due today.
- **Event** entity: `homework_added`, fired once for each entry that appears in the diary
  and is due today or later. The list of entries already announced is kept on disk, so a
  restart neither repeats the diary nor loses what was added while Home Assistant was down.
  The first run only records what exists.

### Changed

- The coordinator now keeps the whole diary and derives the sensor's "next 14 days" from it.
  The sensor itself is unchanged.
- `scripts/edifice_homework.py` loads `api.py` by path: the integration now contains a
  `calendar.py`, which would otherwise shadow the standard library's module.

## 0.1.0 - internal

First version, never published. Tested on Paris Classe Numérique with a parent account, on
Home Assistant 2026.7.2 and 2026.9.3.

### Added

- `sensor` with the number of homework items due from today (14 days ahead), and the list
  in the `homework` attribute, excluded from the recorder.
- Config flow: ENT address, username, password and an optional name. Checks that the
  address is an Edifice platform, signs in, and confirms a homework diary is readable
  before saving.
- Reauthentication when the ENT rejects the saved password; polling stops until then.
- One re-login and one retry when a session expires, never a loop.
- English and French translations.
- Brand icons (`brand/icon.png`, `brand/icon@2x.png`), which HACS requires. Drawn for this
  project; they reuse no logo from Edifice or from any ENT.
- `scripts/edifice_login.py` and `scripts/edifice_homework.py`, which print shapes and
  counts rather than school data, and audit what the parser kept against what the server
  sent.

### Known limits

- Homework diary of the primary-school module only.
- monLycée.net is not supported (Keycloak / OpenID Connect sign-in).
- Server-side session lifetime is not yet measured.
