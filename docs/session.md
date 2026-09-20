# The Edifice session

How authentication works on an Edifice-based ENT, how to tell whether a session is
still valid, and what is known about when it stops being valid.

Everything below that is marked **verified** was checked against a live platform;
everything marked **unknown** was not, and is flagged rather than guessed.

## Logging in

Edifice platforms authenticate with a plain form POST, not CAS. This surprises people
because entcore *ships* CAS components -- but they point the other way: `cas-server-async`
makes the ENT a CAS provider for third-party apps, and `CasClientController` is for the
platforms that sit behind an academic CAS. A platform like Paris Classe Numerique uses
neither at its front door.

```
POST /auth/login
Content-Type: application/x-www-form-urlencoded

email=<login>&password=<password>&callBack=<url>
```

**Verified**: the route and all three field names are unchanged in `entcore` from
2015-07-07 to today, across 152 commits to `AuthController.java`.

On success the server replies `302` and sets a `oneSessionId` cookie. Every subsequent
request carries that cookie; there is no bearer token in this flow.

### The trap: failure is a 200

| Outcome | Status | `oneSessionId` |
|---|---|---|
| Success | 302 | set |
| Wrong credentials | **200** | absent |
| Federated platform (CAS / EduConnect / SAML) | 302 to another host | absent |
| Forced password renewal, activation, CGU | 302 within `/auth/` | absent |

A rejected login returns **200 with the login page**, not 401. Any client that follows
redirects and checks `response.ok` will read "success" from a failed login. Two rules
follow:

- always send the login with redirects disabled;
- treat *the presence of the cookie*, not the status code, as the proof of success.

**Verified** on a live platform with a nonexistent login: 200, no cookie.

## Checking that a session is still active

Call a cheap authenticated route and look at the status:

```
GET /auth/oauth2/userinfo      # or /userbook/api/person
```

| Status | Meaning |
|---|---|
| 200 + JSON | session valid |
| **302 to `/auth/login`** | session absent or expired |
| 404 | that module is not deployed on this platform |

**The second trap**: an expired session does not produce 401. API routes redirect to the
login page, exactly like an unauthenticated request. With redirects followed, the client
receives `200 text/html` -- a login page that will happily be parsed as if it were data.

So, for every request the client makes:

- `allow_redirects=False`, always;
- a 3xx response means *re-authenticate*, not *follow*;
- a `200` whose `Content-Type` is not JSON is a failure, not a payload.

**Verified**: unauthenticated requests to `/homeworks/list`, `/directory/user/children`,
`/userbook/api/person` and `/timeline/lastNotifications` all return 302 on PCN, while a
nonexistent route returns 404. That 302/404 split is also how to probe which modules a
given platform actually deploys.

## When the session expires

**Unknown.** The server-side lifetime is a per-deployment configuration value in
entcore's session store, not a constant in the source, and it could not be pinned down
from the public repositories. It therefore has to be measured per platform -- and a value
measured on one ENT does not transfer to another.

To measure it:

```
python scripts/edifice_login.py --watch
```

This logs in once, then re-checks the identity route every 5 minutes for up to 12 hours,
never re-authenticating, and prints the interval in which the session died. Leave it
running; Ctrl-C stops it early.

The script also prints what the server declares about the cookie itself (`expires`,
`secure`, `domain`) right after login. Note that a cookie carrying no expiry is a
*browser-side* session cookie -- it says nothing about how long the server will honour it.
The measured number is the one that matters.

### What the client should do about it

Until the number is known, and regardless of what it turns out to be:

- keep one session and reuse it across polls, rather than logging in each cycle;
- on a 3xx, re-authenticate **once**, then retry the request **once**;
- if that second attempt also fails, surface the error and stop. No loop.

Repeated failed logins are the one behaviour that could get an account restricted, so the
cost of a retry loop is not wasted requests -- it is the account.
