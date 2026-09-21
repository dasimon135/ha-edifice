# Changelog

## 0.4.0 - unreleased

### Added

- **Refresh button** on the account's device: reads the ENT right away instead of waiting for
  the next scheduled read. It stays available while the ENT is unreachable, so pressing it is
  also how you retry. Home Assistant merges presses made in quick succession: one read at once,
  and at most one more when its cooldown ends.
- **Polling interval option** (Configure on the integration): a whole number of minutes from 5
  to 1440, 20 as before by default. Saving reloads the integration. A value outside the bounds
  written into the configuration by hand is ignored, and the default is used.

## 0.3.1 - 2026-09-21

### Fixed

- **The automation examples in the README missed what is caught up at startup.** They ignored
  every event arriving from `unavailable` (`not_from`), but an event caught up when the entity is
  set up, after a restart or a reload, arrives exactly like that: what a teacher added while Home
  Assistant was down was recorded and announced by the integration, and never reached the phone.
  The examples now keep any event less than five minutes old instead, which still ignores the old
  event an entity brings back after an outage. If you copied the earlier examples, remove
  `not_from` and add the condition. The integration itself is unchanged.

## 0.3.0 - 2026-09-21

First public release. Tested on Paris Classe Numérique with a parent account, on Home
Assistant 2026.7.2 and 2026.9.3.

### Added

- **Homework sensor**: how many homework items are due from today, looking 14 days ahead. The
  list is in the `homework` attribute, kept out of the recorder, and `next_due` is the date of
  the next one.
- **Calendar**: the whole diary as all-day events on the day each item is due, past weeks
  included. It is on while something is due today.
- **New homework event** (`homework_added`), fired once for each entry that appears in the
  diary and is due today or later. What was already announced is kept on disk, so a restart
  neither repeats the diary nor loses what was added while Home Assistant was down. The first
  run only records what exists.
- **Cahier de liaison, per child.** Each child gets a device named after their first name, with
  a sensor counting the words this account has not acknowledged, the latest ten as an attribute
  (title, date, sender, category, acknowledged), and a `word_added` event. The text of a word is
  never kept. Announcements are remembered per child, and a child met for the first time is a
  baseline, not news.
- **Unread messages** sensor, for ENTs that use the classic `conversation` mailbox. Only the
  count is read.
- **Configuration**: ENT address, username, password and an optional name. It checks that the
  address is an Edifice platform, signs in, and confirms a homework diary is readable before
  saving anything. Reauthentication when the ENT rejects the saved password; polling stops
  until then.
- English and French translations, and the brand icons HACS requires. The icons were drawn
  for this project and reuse no logo from Edifice or from any ENT.
- Command-line scripts in `scripts/` that print shapes and counts rather than school data, to
  observe an ENT and to audit what the parser kept against what the server sent.

### How it behaves

- It refreshes every 20 minutes and reuses one session. When the session has expired it signs
  in again once and retries once, and never loops.
- A module the ENT does not have costs only its own entities, never the homework, and is not
  asked for again after its first 404. A network failure still fails the whole refresh.
- The list of children is asked for every six hours, not at every refresh.

### Known limits

- The homework diary of the primary-school module only. The secondary-school `diary` module is
  not supported.
- monLycée.net is not supported: it signs in through Keycloak / OpenID Connect.
- A mailbox on Carbonio is not supported; the unread-messages sensor is simply absent.
- The integration only reads. It never acknowledges a word of the cahier de liaison.
- A child enrolled after the integration was set up gets their entities after a reload.
- Only the first ten words of each child's cahier de liaison are read.
- The server-side lifetime of a session is not measured. No re-authentication was seen over the
  hours Home Assistant's own log could show.
