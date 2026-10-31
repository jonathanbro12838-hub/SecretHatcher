"""Puts your GitHub repo into the app so it can find new releases. Run via set_update_url.bat."""
import re, sys

user, repo = sys.argv[1].strip(), sys.argv[2].strip()
if not user or not repo:
    sys.exit("Need a GitHub username and a repo name.")

url = f"https://api.github.com/repos/{user}/{repo}/releases/latest"
src = open("hatch_watcher.py", encoding="utf-8").read()
new, n = re.subn(r'^UPDATE_URL = ".*"$', f'UPDATE_URL = "{url}"', src, flags=re.M)
if n != 1:
    sys.exit("Couldn't find the UPDATE_URL line in hatch_watcher.py.")
open("hatch_watcher.py", "w", encoding="utf-8").write(new)

print()
print("Done! The app will now look for updates at:")
print("  " + url)
print()
print("Next: run build_exe.bat, then give people the new exe.")
print("To publish an update later: raise APP_VERSION in hatch_watcher.py, push to GitHub, then push a tag like v1.3.0.")
print("(See README.txt - the GitHub Action builds the exe and makes the release for you.)")
