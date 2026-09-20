# Changelog

## 0.1.0 - unreleased

First version. Tested on Paris Classe Numérique with a parent account, on Home Assistant
2026.7.2 and 2026.9.3.

### Added

- `sensor` with the number of homework items due from today (14 days ahead), and the list
  in the `homework` attribute, excluded from the recorder.
- Config flow: ENT address, username, password and an optional name. Checks that the
  address is an Edifice platform, signs in, and confirms a homework diary is readable
  before saving.
- Reauthentication when the ENT rejects the saved password; polling stops until then.
- One re-login and one retry when a session expires, never a loop.
- English and French translations.
- `scripts/edifice_login.py` and `scripts/edifice_homework.py`, which print shapes and
  counts rather than school data, and audit what the parser kept against what the server
  sent.

### Known limits

- Homework diary of the primary-school module only.
- monLycée.net is not supported (Keycloak / OpenID Connect sign-in).
- Server-side session lifetime is not yet measured.
