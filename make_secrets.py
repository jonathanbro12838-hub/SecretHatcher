"""Writes hw_secrets.py (the Discord webhooks, scrambled) just before the app is built.

The webhooks are NOT stored in the source code. They come from either:
  - GitHub Actions secrets  HATCH_WEBHOOK_MAIN and HATCH_WEBHOOK_TEST   (used by the cloud build), or
  - a local file webhooks.txt next to this script, with two lines:
        main=https://discord.com/api/webhooks/....
        test=https://discord.com/api/webhooks/....
Never upload webhooks.txt or hw_secrets.py anywhere.   Use:  python make_secrets.py [--require]
"""
import base64, os, sys

K = b"hw-community-v1"
PREFIX = "https://discord.com/api/webhooks/"


def enc(url):
    return base64.b64encode(bytes(c ^ K[i % len(K)] for i, c in enumerate(url.encode()))).decode()


main = os.environ.get("HATCH_WEBHOOK_MAIN", "").strip()
test = os.environ.get("HATCH_WEBHOOK_TEST", "").strip()
if os.path.exists("webhooks.txt"):
    for line in open("webhooks.txt", encoding="utf-8"):
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip().lower() == "main" and not main:
                main = v.strip()
            elif k.strip().lower() == "test" and not test:
                test = v.strip()

problems = []
for name, url in (("main", main), ("test", test)):
    if not url:
        problems.append(f"no {name} webhook found")
    elif not url.startswith(PREFIX):
        problems.append(f"the {name} webhook doesn't look like a Discord webhook link")
        if name == "main":
            main = ""
        else:
            test = ""

with open("hw_secrets.py", "w", encoding="utf-8") as f:
    f.write(f'MAIN = "{enc(main) if main else ""}"\nTEST = "{enc(test) if test else ""}"\n')

if problems:
    print("WARNING: " + "; ".join(problems) + ". The app will not be able to send those alerts.")
    if "--require" in sys.argv:
        sys.exit(1)
else:
    print("Webhooks added to this build (hw_secrets.py).")
