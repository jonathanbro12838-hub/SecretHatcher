SECRET HATCH NOTIFER+   (v1.1.0)

RUN FROM CODE (you):   double-click start.bat
MAKE THE .EXE:         double-click build_exe.bat  ->  dist\Secret Hatch Notifer+.exe
                       (needs Python 3.10-3.12 on the building PC only; people you give the .exe to need nothing)
NO PYTHON?             upload this folder to a GitHub repo, open Actions > "Build Secret Hatch Notifer+.exe" > Run workflow,
                       then download the artifact.

Players: open the exe, paste your Discord user ID, press START.
Settings, stats and sounds live in %APPDATA%\Secret Hatch Notifer+ (not next to the exe).
TO SHARE: give people ONLY the exe.

THE UI
  Watcher tab   - your Discord ID, the round START button, today/session/all-time counters, your Roblox windows, activity.
  Stats tab     - per-account counts, recent secrets, CSV export.
  Settings tab  - detection options, button sounds on/off, update check.
  The window sizes itself to your screen. Colours: THEME = "neon" (navy/orange/violet) or "red" at the top of hatch_watcher.py.

BUTTON SOUNDS
  Small click/toggle/start/stop tones are generated on first run (no audio files needed). Turn off in Settings.

UPDATING FROM INSIDE THE APP (set up once)
  1. Put this folder in a GitHub repo (the included workflow builds the exe for you).
  2. In hatch_watcher.py set:
       UPDATE_URL = "https://api.github.com/repos/YOUR-NAME/YOUR-REPO/releases/latest"
     then build and hand out that exe ONE time. After that, people update from inside the app.
  3. To publish an update: raise APP_VERSION (e.g. "1.2.0"), commit, then run:
       git tag v1.2.0
       git push origin v1.2.0
     GitHub builds the exe and attaches it to a Release automatically.
  4. Everyone running an older version sees a purple "Update v1.2.0: click to install" button at the top.
     They click it, press Yes, and the app downloads the new exe, replaces itself and reopens. No browser needed.
  No GitHub? Host a JSON file anywhere (https) and point UPDATE_URL at it:
       {"version": "1.2.0", "download": "https://direct-link-to-the-exe", "notes": "what's new", "sha256": "optional"}
  Safety: updates must be https, must be a real .exe, and are checked against sha256 if you provide one.
  Only YOU control what gets installed, because the app only trusts the URL you set in UPDATE_URL.
  (Running from start.bat / code instead of the exe: the button opens the download page instead of self-installing.)
