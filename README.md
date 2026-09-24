# Edifice ENT for Home Assistant

School homework, notes from the teachers and unread mail from your child's ENT, in Home
Assistant.

> **Unofficial.** This project is not affiliated with, endorsed by or supported by
> Edifice, CGI, or any school authority. It reads a web service that has no public
> documentation, using an account you already have.

## Is this for you?

Many French schools give parents access to an **ENT** (*espace numérique de travail*)
built on Edifice, formerly Open ENT NG. This integration reads three things and shows them
in Home Assistant:

- the **homework diary** (*cahier de textes*) of the primary-school module;
- the **cahier de liaison**, the notes teachers send to parents, for each child;
- how many **unread messages** are in the inbox.

The second and the third are optional: an ENT that has only the homework diary still works,
and gets only the homework entities.

It works if all of these are true:

- your ENT is Edifice-based **and** you sign in by typing a username and a password on
  the ENT's own login page;
- the ENT has the homework module (the app named `homeworks`);
- you run Home Assistant 2026.7 or newer.

It will **not** work if you sign in "with EduConnect", through a CAS or OpenID Connect
service, or if your ENT is not Edifice. See [Compatibility](#compatibility): in
particular, **monLycée.net is not supported**.

It only reads. The single request it sends that is not a plain read is the login.

## What you get

Each account gets one device, named after the class (or the name you choose), that holds
the homework entities and the mailbox counter. **Each child gets a device of their own**,
named after their first name, that holds the cahier de liaison. Entity ids follow Home
Assistant's language: `…_devoirs`, `…_mots_non_lus` on a French installation, `…_homework`,
`…_unread_school_notes` on an English one. You can rename them as usual.

### Sensor: what is still to do

| | |
|---|---|
| **State** | how many homework items are due from today, looking 14 days ahead |
| `next_due` | date of the next homework, or `null` when nothing is due |
| `homework` | the list: `date`, `subject`, `content` (plain text), `entry_id`, `diary` |

The `homework` list is kept out of the recorder, so the database does not grow by a few
kilobytes at every teacher edit. The count and `next_due` are recorded normally.

### Calendar: the whole diary

Every homework item is an all-day event on the day it is **due**: the official mobile app
groups the diary under "Pour *date*", so that is what the date of an entry means. The
subject is the title and the text is the description. Any calendar card shows it, and the
calendar keeps the **past** weeks that the sensor leaves out.

The calendar is *on* while something is due today. Its `message` is today's first homework,
or the next one when nothing is due today.

### Event: a new homework was published

The event entity fires `homework_added` once for every entry that was not in the diary at
the previous refresh, and only if it is due today or later, so a teacher back-filling last
week notifies nobody. The event carries `date`, `subject`, `content`, `entry_id` and
`diary`, and none of them is written to the database.

The first time the integration runs it only records what already exists. The list of
entries already announced is kept on disk, so a restart neither repeats the whole diary
nor loses what a teacher added while Home Assistant was down.

### Cahier de liaison, for each child

On the child's device, when the ENT has the module:

| | |
|---|---|
| **Sensor** *unread school notes* | how many words **you** have not acknowledged. Another parent's acknowledgment does not count for you. |
| `words` | the latest ten words: `id`, `title`, `date`, `sender`, `category`, `acknowledged` |
| **Event** *new school note* | fires `word_added` for each word that appears, with the same fields |

**The text of a word is never kept.** It is part of what the ENT sends with the list, and is
dropped at once: only the title, the date, the sender, the category and whether you
acknowledged it reach Home Assistant, and none of them is written to the database. Open the
ENT to read the note.

As with homework, the first run records the existing words and announces none, per child, and
what was announced is remembered across restarts.

The integration never acknowledges a word for you: that would be a write, and it only reads.

### Unread messages

On the account's device, when the ENT uses the classic `conversation` mailbox: the number of
unread messages in the inbox. Only the number is read, never a message. An ENT whose mail
runs on Carbonio is not supported, and simply gets no such sensor.

### Refresh button

On the account's device, a **Refresh** button reads the ENT right away instead of waiting for
the next scheduled read. Use it after you mark something as read in the ENT, or when a teacher
tells you something was just posted.

It stays available while the ENT is unreachable, so pressing it is also how you retry. Home
Assistant merges presses made in quick succession: the first one reads at once, and however
many follow within the next few seconds cost one more read when the cooldown ends.

An automation or a dashboard can press it too: `button.press` on that entity.

### Examples

Remind yourself at 18:00 when there is homework for tomorrow:

```yaml
automation:
  - alias: "Homework for tomorrow"
    triggers:
      - trigger: time
        at: "18:00:00"
    conditions:
      - condition: template
        value_template: >
          {{ state_attr('sensor.school_emma_devoirs', 'next_due')
             == (now().date() + timedelta(days=1)).isoformat() }}
    actions:
      - action: notify.notify
        data:
          title: "Homework for tomorrow"
          message: >
            {% set tomorrow = (now().date() + timedelta(days=1)).isoformat() %}
            {% for hw in state_attr('sensor.school_emma_devoirs', 'homework')
                 if hw.date == tomorrow %}
            - {{ hw.subject }}: {{ hw.content }}
            {% endfor %}
```

Be told when a teacher adds homework:

```yaml
automation:
  - alias: "New homework"
    triggers:
      - trigger: state
        entity_id: event.school_emma_new_homework
        # Do not add `not_from: unavailable`: what was added while Home Assistant was
        # down is announced when the entity is set up, and that event arrives from
        # "unavailable".
        not_to:
          - unavailable
          - unknown
    conditions:
      # After an outage the entity comes back from "unavailable" with its previous
      # timestamp, which would replay an old event. Only a recent one is news.
      - condition: template
        value_template: "{{ (now() - trigger.to_state.state | as_datetime).total_seconds() < 300 }}"
    actions:
      - action: notify.notify
        data:
          title: "New homework: {{ trigger.to_state.attributes.subject }}"
          message: >
            For {{ trigger.to_state.attributes.date }}:
            {{ trigger.to_state.attributes.content }}
```

Be told when a teacher writes a note:

```yaml
automation:
  - alias: "New school note"
    triggers:
      - trigger: state
        entity_id: event.emma_new_school_note
        not_to:
          - unavailable
          - unknown
    conditions:
      - condition: template
        value_template: "{{ (now() - trigger.to_state.state | as_datetime).total_seconds() < 300 }}"
    actions:
      - action: notify.notify
        data:
          title: "New note for Emma"
          message: >
            {{ trigger.to_state.attributes.title }}
            ({{ trigger.to_state.attributes.sender }})
```

Dashboard cards: see [Dashboard examples](#dashboard-examples).

## Dashboard examples

These cards use only Home Assistant's own markdown, calendar and button cards, so there is
nothing to install. Replace the entity ids with yours (they follow Home Assistant's language:
`sensor.school_emma_devoirs` on a French installation) and translate the words between quotes.

A markdown card redraws itself when the entities it reads change, and the sensors change at
every refresh, so nothing has to be triggered. The test suite renders each template below
against sample data, so an example that stops working is caught there rather than by you.

### Homework by day

```yaml
type: markdown
content: |
  {%- macro text(h) -%}
  {{ h.content.split('\n') | map('regex_replace', '^\\s*-\\s*', '') | reject('eq', '') | join(' · ') }}
  {%- endmacro -%}
  {%- set hw = state_attr('sensor.school_emma_homework', 'homework') or [] -%}
  {%- set today = now().date() -%}
  {%- for d in hw | map(attribute='date') | unique | sort %}
  {%- set day = strptime(d, '%Y-%m-%d') %}
  {%- set delta = (day.date() - today).days %}
  **{{ 'Today' if delta == 0 else 'Tomorrow' if delta == 1 else day.strftime('%A %d %B') }}**
  {% for h in hw | selectattr('date', 'eq', d) %}
  - **{{ h.subject }}**: {{ text(h) }}
  {% endfor %}
  {% endfor %}
  {%- if not hw %}Nothing due.{% endif %}
```

### Tomorrow at a glance

One line, made for a phone.

```yaml
type: markdown
content: |
  {%- set hw = state_attr('sensor.school_emma_homework', 'homework') or [] -%}
  {%- set tomorrow = (now().date() + timedelta(days=1)).isoformat() -%}
  {%- set subjects = hw | selectattr('date', 'eq', tomorrow) | map(attribute='subject') | unique | list -%}
  {% if subjects %}**Tomorrow**: {{ subjects | join(', ') }}{% else %}Nothing due tomorrow.{% endif %}
```

### The whole diary, past weeks included

The sensor only looks ahead. The calendar keeps the past.

```yaml
type: calendar
initial_view: listWeek
entities:
  - calendar.school_emma_homework
```

### Notes to acknowledge

The cahier de liaison, for one child, limited to the last 30 days. The sensor's own count goes
back further, and a note from last year that nobody acknowledged is noise, not urgency. Dates
are written year first, so there is no doubt about which year a note is from.

```yaml
type: markdown
content: |
  {%- set since = (now().date() - timedelta(days=30)).isoformat() -%}
  {%- set words = state_attr('sensor.emma_unread_school_notes', 'words') or [] -%}
  {%- set todo = words | rejectattr('acknowledged') | selectattr('date') | selectattr('date', 'ge', since) | list -%}
  {% if todo %}**To acknowledge** ({{ todo | count }}):
  {% for w in todo %}
  - {{ w.date }}: {{ w.title }}
  {% endfor %}{% else %}Nothing to acknowledge from the last 30 days.{% endif %}
```

Only the ENT can acknowledge a note: this integration never does.

### Refresh, and when the ENT was last read

The [Refresh button](#refresh-button), and a line that says how old what you are looking at is.

```yaml
type: button
entity: button.school_emma_refresh
name: Refresh
show_state: false
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.school_emma_refresh
```

```yaml
type: markdown
content: |
  Last read: {{ relative_time(states['sensor.school_emma_homework'].last_reported) }} ago
```

## Installation

### With HACS

1. In HACS, open the menu (⋮) → **Custom repositories**.
2. Add `https://github.com/dasimon135/ha-edifice` with the category **Integration**.
3. Download **Edifice ENT**, then restart Home Assistant.

### Manually

Copy the `custom_components/edifice` folder into the `custom_components` folder of your
Home Assistant configuration, then restart.

## Configuration

**Settings → Devices & services → Add integration → Edifice ENT.**

| Field | |
|---|---|
| ENT address | what you type in your browser to reach the ENT, for example `https://ent.parisclassenumerique.fr` |
| Username | your ENT login |
| Password | your ENT password |
| Name | optional; names the device and the sensor. Defaults to the name of the class diary |

Before saving anything, the integration checks that the address is an Edifice ENT, signs
in once, and confirms the account can read a homework diary.

Add the integration again for another account. The same account cannot be added twice.

If the ENT stops accepting the saved password, Home Assistant asks you for the new one
and refreshes stop meanwhile: a changed password costs **one** failed login, not one per
refresh.

### How often it reads the ENT

Every 20 minutes by default. To change it, open **Settings → Devices & services → Edifice ENT →
Configure** and enter a whole number of minutes, from 5 to 1440 (24 hours). Saving reloads the
integration.

There is a lower bound because every reading is a handful of requests to a school platform
that is not yours; the [Refresh button](#refresh-button) covers the times when waiting is the
problem. A value outside the bounds written into the configuration by hand is ignored, and the
default is used instead.

## How it behaves

- It refreshes every **20 minutes** unless you choose otherwise
  ([how often it reads the ENT](#how-often-it-reads-the-ent)), reusing one session: two
  requests for the diary, two per child for the cahier de liaison, one for the mailbox. The list of children is asked for
  only every six hours. A module the ENT does not have answers 404 once and is not asked
  for again until the next reload.
- A module that is missing or answers something unreadable costs only its own entities,
  never the homework. A network failure, on the other hand, fails the whole refresh.
- A child enrolled after the integration was set up gets their entities after a reload.
- When the session has expired it signs in again **once**, retries **once**, and reports an
  error if that also fails. It never loops.
- If the ENT is unreachable the sensor becomes *unavailable* and is retried at the next
  refresh. If the credentials are rejected it asks for reauthentication instead.
- It counts homework **from today**, so past weeks are not included. Around midnight the
  count can lag by up to one refresh.
- A diary belongs to a **class**, not to a child: an account with two children in the same
  class sees one diary.

## Compatibility

| Platform | Status |
|---|---|
| Paris Classe Numérique (`ent.parisclassenumerique.fr`) | **Works**: homework, cahier de liaison and the classic mailbox. Tested by the author, parent account. |
| `ent77.seine-et-marne.fr`, `enthdf.fr`, `mon.lyceeconnecte.fr` | Answer as Edifice platforms. Login and homework **not tested**. |
| monLycée.net | **Not supported.** It signs in through a Keycloak / OpenID Connect page, not the Edifice form. |
| Secondary-school diary (`diary` module, *cahier de textes 2D*) | Not supported. Not deployed on Paris Classe Numérique, so not tested. |
| Cahier de liaison (`schoolbook` module) | Supported, per child. Read-only: acknowledging a word is not done. |
| Mailbox on Carbonio (Zimbra) instead of the classic `conversation` module | Not supported. The mailbox counter is simply absent. |
| School agenda, news, blog, forms | Not supported. |
| Two-factor authentication | Untested, and most likely unsupported. |

Tried another ENT? Please [open an issue](../../issues) with its address and what
happened, so this table can be corrected. Leave out any personal data.

## Privacy and responsibility

- Everything runs on **your** Home Assistant, with **your** account. Nothing is sent to
  any third party.
- Home Assistant stores the password in plain text in its configuration storage
  (`.storage/core.config_entries`), like every integration that needs one.
- The homework list is readable by anything that can read entity states: dashboards,
  other integrations, voice assistants if you expose the sensor, notifications. It is a
  child's school data; expose it accordingly.
- Your children's **first names** become the names of their devices, and the cahier de
  liaison exposes the **title, date and sender** of each note (never its text). Keep that
  in mind before exposing those entities outside your home.
- An ENT's terms of use generally make credentials personal and non-transferable. Use this
  with your own account on your own installation. **Do not run it as a hosted service for
  other people, and do not give your ENT login to any third-party service.**
- The service it talks to is not documented and not guaranteed. The login route has been
  unchanged since 2015 and the homework routes since at least 2023, as far as public
  history shows, but it can change without notice. If the ENT ever puts a bot-protection
  challenge in front of the login, this integration will stop working and will **not**
  try to get around it.
- It identifies itself honestly in the `User-Agent` header and makes few requests.

## Troubleshooting

| Message | What to check |
|---|---|
| The ENT rejected this username or password | Sign in on the ENT website with the same details. |
| This does not look like an Edifice ENT with a homework diary | The address may be wrong; the ENT may sign in through an external service; it may be waiting for a password change or for you to accept its terms, which must be done once in a browser; or the homework module may not be enabled. |
| Could not reach the ENT | Check the address, and try again later. |
| Signed in, but this account can read no homework diary | The account has no access to the homework module. |

To see what the integration is doing, add this to `configuration.yaml`, restart, then
read **Settings → System → Logs**:

```yaml
logger:
  logs:
    custom_components.edifice: debug
```

The logs contain no password and no homework text. Check them anyway before posting them
in a public issue.

## How it works

The ENT signs users in with a plain form (`POST /auth/login`) and answers with a session
cookie; the integration then reads `/homeworks/list` and `/homeworks/get/{id}`. Two
details cost the author time and are written down in [docs/](docs/):

- [docs/session.md](docs/session.md): a **failed login answers HTTP 200** and an
  **expired session answers a redirect**, never 401. A client that follows redirects
  reads a login page as if it were data.
- [docs/homework-api.md](docs/homework-api.md): the routes and the payload, observed
  because the server side of this module is not open source.

The routes were learned by reading the public source of the official mobile app and by
observing a live account. No code was copied from Edifice's repositories.

## Development

```
python -m pytest tests/test_api.py          # no Home Assistant needed
docker run --rm -v "${PWD}:/src" -w /src python:3.14-slim \
  bash -c "pip install -q -r requirements-test.txt && python -m pytest tests/ -q"
```

The Home Assistant test harness does not run natively on Windows (`fcntl`), hence Docker.
`scripts/edifice_login.py` and `scripts/edifice_homework.py` exercise a real ENT from the
command line and print **shapes and counts, never homework text** unless you pass `--show`.

## License

[MIT](LICENSE)
