# Scripts

Three command-line tools that talk to a real ENT. They exist because the homework module has
no public server source: its routes and payloads had to be observed, and the same goes for
the modules a future release might read.

| Script | What it does |
|---|---|
| `edifice_login.py` | Confirms the host is an Edifice platform, signs in once, and prints the **shape** of a few answers. `--watch` measures how long a session survives. |
| `edifice_homework.py` | Runs the homework client and audits what the parser kept against what the server sent. `--show` prints the actual homework, on your own screen only. |
| `edifice_discover.py` | Reads the cahier de liaison, the mailbox and the notification feed, and prints their **shape**. |

Except for `--show`, they print keys, types, lengths and counts, never a value from your
account. The output is safe to paste into a chat or an issue. Never paste `--show` output.

## Credentials

They are looked up in this order and are never printed:

1. the environment: `EDIFICE_USERNAME`, `EDIFICE_PASSWORD`, `EDIFICE_URL`;
2. the file `~/.config/ha-edifice/credentials.env`, or the path in `EDIFICE_CREDENTIALS_FILE`;
3. an interactive prompt, the password without echo.

The file sits outside every repository so that it cannot be committed by accident. It holds
one `KEY=VALUE` per line, and only the first `=` splits a line, so a password may contain any
character. Create it **without typing the password into your shell history**.

Windows PowerShell:

```powershell
$dir = "$HOME\.config\ha-edifice"
New-Item -ItemType Directory -Force $dir | Out-Null
$user  = Read-Host "ENT login"
$pass  = Read-Host "ENT password" -AsSecureString
$plain = [System.Net.NetworkCredential]::new("", $pass).Password
Set-Content -Path "$dir\credentials.env" -Encoding utf8 `
  -Value "EDIFICE_URL=https://ent.example.org`nEDIFICE_USERNAME=$user`nEDIFICE_PASSWORD=$plain"
icacls "$dir\credentials.env" /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
```

Linux and macOS:

```sh
umask 077; mkdir -p ~/.config/ha-edifice
IFS= read -r -p "ENT login: " u; IFS= read -r -s -p "ENT password: " p; echo
printf 'EDIFICE_URL=https://ent.example.org\nEDIFICE_USERNAME=%s\nEDIFICE_PASSWORD=%s\n' "$u" "$p" \
  > ~/.config/ha-edifice/credentials.env
```

Both were checked with a password containing quotes, `$`, `#`, `=` and a trailing space.
`IFS=` matters: without it, `read` silently strips a leading or trailing space.

Anyone who can run commands as you can read that file, and so can any tool you let run in
your name. It protects against an accidental commit and a stray backup, not against a
process you have authorised.
