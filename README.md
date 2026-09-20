# Edifice ENT for Home Assistant

School homework from your child's ENT, as a Home Assistant sensor.

> **Unofficial.** This project is not affiliated with, endorsed by or supported by
> Edifice, CGI, or any school authority. It reads a web service that has no public
> documentation, using an account you already have.

## Is this for you?

Many French schools give parents access to an **ENT** (*espace numérique de travail*)
built on Edifice, formerly Open ENT NG. This integration reads the **homework diary**
(*cahier de textes*) of the primary-school module and shows it in Home Assistant.

It works if all of these are true:

- your ENT is Edifice-based **and** you sign in by typing a username and a password on
  the ENT's own login page;
- the ENT has the homework module (the app named `homeworks`);
- you run Home Assistant 2026.7 or newer.

It will **not** work if you sign in "with EduConnect", through a CAS or OpenID Connect
service, or if your ENT is not Edifice. See [Compatibility](#compatibility) — in
particular, **monLycée.net is not supported**.

It only reads. The single request it sends that is not a plain read is the login.

## What you get

Three entities per account, grouped under one device named after the class (or the name
you choose). The entity ids follow Home Assistant's language: `…_devoirs`, `…_nouveau_devoir`
on a French installation, `…_homework`, `…_new_homework` on an English one. You can rename
them as usual.

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
        # An outage flips the entity through "unavailable" and back, which would
        # replay the previous event. Neither end of that is news.
        not_from:
          - unavailable
        not_to:
          - unavailable
          - unknown
    actions:
      - action: notify.notify
        data:
          title: "New homework: {{ trigger.to_state.attributes.subject }}"
          message: >
            For {{ trigger.to_state.attributes.date }}:
            {{ trigger.to_state.attributes.content }}
```

A dashboard card:

```yaml
type: markdown
title: Homework
content: >
  {% for hw in state_attr('sensor.school_emma_devoirs', 'homework') %}
  **{{ hw.date }} - {{ hw.subject }}**

  {{ hw.content }}

  {% endfor %}
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

## How it behaves

- It refreshes every **20 minutes**, with two requests per diary, reusing one session.
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
| Paris Classe Numérique (`ent.parisclassenumerique.fr`) | **Works.** Tested by the author, parent account. |
| `ent77.seine-et-marne.fr`, `enthdf.fr`, `mon.lyceeconnecte.fr` | Answer as Edifice platforms. Login and homework **not tested**. |
| monLycée.net | **Not supported.** It signs in through a Keycloak / OpenID Connect page, not the Edifice form. |
| Secondary-school diary (`diary` module, *cahier de textes 2D*) | Not supported. Not deployed on Paris Classe Numérique, so not tested. |
| Cahier de liaison (`schoolbook` module) | Not supported yet. |
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

- [docs/session.md](docs/session.md) — a **failed login answers HTTP 200** and an
  **expired session answers a redirect**, never 401. A client that follows redirects
  reads a login page as if it were data.
- [docs/homework-api.md](docs/homework-api.md) — the routes and the payload, observed
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
