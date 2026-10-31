SECRET HATCH NOTIFER+  (v1.2.0)

RUN FROM CODE (you):   double-click start.bat
MAKE THE .EXE:         double-click build_exe.bat  ->  dist\Secret Hatch Notifer+.exe
                       (needs Python 3.10-3.12 on the building PC only)
Keep icon.ico and alert.wav in this folder when building (exe icon + click sound).

PLAYERS: open the exe, paste your Discord user ID, press START.
Settings and stats are saved in %APPDATA%\Secret Hatch Notifer+ (not next to the exe).

UPDATES INSIDE THE APP
1. Double-click set_update_url.bat once, type your GitHub username + repo name (repo must be PUBLIC), then rebuild.
2. To release an update:
     - raise APP_VERSION in hatch_watcher.py (e.g. 1.3.0) and push the code to GitHub
     - on GitHub: Releases > Draft a new release > tag "v1.3.0" > Publish.
       (or push a tag:  git tag v1.3.0 && git push origin v1.3.0)
     - the included GitHub Action builds the exe and attaches it to the release automatically
       (give it ~10 minutes; watch the Actions tab).
3. Everyone running an older version (that includes this update system) sees an "Update to v1.3.0" button at the
   bottom-left of the app. They click it, press Yes, and the app downloads the new exe, replaces itself and reopens.
   Their settings and stats are kept.
