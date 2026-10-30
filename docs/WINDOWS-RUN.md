# WiseQ Hermes — how to run it from this PC

Everything below has already been done on this machine
(`C:\hermes\work\wiseq-hermes`). You do not need to install anything
again.

## 1. Show the demo to Rob (the main thing)

Double-click:

```
C:\hermes\work\wiseq-hermes\scripts\demo_windows.bat
```

It installs (if needed), runs the test suite, then runs the demo against
WiseQ's own master files. The demo prints everything: the catalogue, a
school order being parsed, the pricing, the human approval that stops
it from sending, and the list of decisions only Rob can make.

Nothing in the demo sends mail, places an order, or changes a price.
Test mail, if any is triggered, goes only to `weissvanderpol@gmail.com`.

## 2. The live API (for clicking through)

Double-click:

```
C:\hermes\work\wiseq-hermes\scripts\start_api_windows.bat
```

Then open:

```
http://100.105.54.119:8010/docs
```

That is the interactive API documentation — every endpoint you can call,
with a "Try it out" button.

### The token

The API needs a token for anything except `/health` and `/metrics`.
The token is in:

```
C:\hermes\work\wiseq-hermes\.wiseq-token
```

In the docs page, click **Authorize** at the top right and paste that
value.

To use it from a terminal:

```powershell
$token = Get-Content C:\hermes\work\wiseq-hermes\.wiseq-token -Raw
curl.exe http://100.105.54.119:8010/decisions-owed -Headers @{"X-WiseQ-Token" = $token.Trim()}
```

### The API is already running as a background service

It runs as a Windows scheduled task called `WiseQHermesAPI`, so it
survives logging out. To check it:

```powershell
Get-ScheduledTask -TaskName WiseQHermesAPI
```

To stop it:

```powershell
Stop-ScheduledTask -TaskName WiseQHermesAPI
```

To start it again:

```powershell
Start-ScheduledTask -TaskName WiseQHermesAPI
```

## 3. Get the latest changes

```powershell
cd C:\hermes\work\wiseq-hermes
& "C:\Program Files\Git\cmd\git.exe" pull --ff-only
```

## Notes

- **Port 8010, not 8000.** Port 8000 is already used by your Sazon app
  on this machine, so WiseQ was moved rather than disturbing it.
- **Docker is not installed on this PC**, so the Docker path was not
  tested here. The local Python path is the one that was tested.
- **PostgreSQL is not running here**, so 4 of the tests skip. They were
  run against PostgreSQL on the server, where they pass.
- Everything is public on GitHub:
  `github.com/Ai-Whisperers/wiseq-hermes`
