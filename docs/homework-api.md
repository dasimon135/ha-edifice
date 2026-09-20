# The homework module API

The cahier de textes used by primary schools is the app `homeworks`, whose server class
is `fr.wseduc.homeworks.controllers.HomeworksController`. **It is not open source** --
not under `edificeio`, not under `OPEN-ENT-NG`, not anywhere public. Everything here was
established by reading the official mobile client and by observing a live account.

Do not confuse it with `OPEN-ENT-NG/cahier-de-textes` (`fr.openent.diary`), which is the
secondary-school module, is AGPL, and answers on `/diary/...`. A platform may deploy one,
both, or neither -- probe rather than presume.

Observed on Paris Classe Numerique, 2026-09-20, from a parent account.

## Routes

| Route | Returns |
|---|---|
| `GET /homeworks/list` | the diaries this account can read |
| `GET /homeworks/get/{diaryId}` | one diary with all its entries |
| `GET /homeworks/{diaryId}/entry/status` | done/not-done flags; `?entryid=` and `?repeatid=` optional |

Other controller methods exist -- `createHomework`, `modifyEntry`, `deleteEntry`,
`listRights`, `updateEntryStatus`, `view` -- named in the resource rights the server
returns. This client only reads.

## `GET /homeworks/list`

A JSON array of diaries. A diary belongs to a **class**, not to a child: an account with
two children in two schools was observed returning a single diary.

```jsonc
[{
  "_id": "<uuid>",
  "title": "...", "name": "...",      // observed identical
  "thumbnail": "", "description": "",
  "trashed": 0,                        // integer, not boolean
  "created":         {"$date": "2026-09-01T07:12:44.000Z"},
  "modified":        {"$date": "..."},
  "entriesModified": {"$date": "..."}, // last content change -- see below
  "owner": {"userId": "<uuid>", "displayName": "..."},
  "shared": [{"groupId": "...", "fr-wseduc-homeworks-controllers-HomeworksController|getHomework": true, ...}]
}]
```

`entriesModified` is the cheapest thing in this API: comparing it between polls says
whether re-fetching the entries is worth it at all.

## `GET /homeworks/get/{diaryId}`

The diary object again, plus a `data` array of **day buckets**.

```jsonc
{
  "_id": "<uuid>", "title": "...", "trashed": 0,
  "entriesModified": {"$date": "..."},
  "data": [{
    "date": "2026-09-21",              // plain string -- NOT $date wrapped
    "entries": [{
      "_id": "<uuid>",
      "title": "Mathematiques",        // the subject
      "value": "<p>Exercices 3 et 4</p>"
    }]
  }]
}
```

### Two date formats in one payload

Record timestamps (`created`, `modified`, `entriesModified`) are MongoDB extended JSON:
`{"$date": "<ISO-8601 with milliseconds and Z>"}`. Day buckets are a bare `YYYY-MM-DD`
string. A parser that handles only one of the two will silently lose half the dates.

### `value` is HTML

**Verified**: across 40 entries, stripping markup shortened all but a few by exactly
7 characters -- `<p>` plus `</p>`. Most entries are one paragraph; richer ones (one
measured at 420 characters, 292 after stripping) carry more markup. No entry stripped to
an empty string, so the markup always wraps real text.

### How much history is kept

The single observed diary held **40 entries across 2026-09-02 to 2026-09-25**, with
5 distinct subjects -- roughly the start of the school year up to five days ahead of the
observation date. So the diary carries past homework as well as future, and teachers fill
it about a week ahead at most. A sensor showing "upcoming" should expect a handful of
items, not forty.

## `GET /homeworks/{diaryId}/entry/status`

Returned `[]` on the observed account. Either nothing has been marked done, or a parent
account sees nothing here. Not required to read homework, and not used by this client.

## Everything is redirect-shaped

Every route above answers `302` to `/auth/login` when the session is missing or expired,
never `401`, and `404` when the module is not deployed. See `session.md` -- this is the
single most dangerous property of the API for a naive client.
