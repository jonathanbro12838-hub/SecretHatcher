SECRET HATCH NOTIFER+  (v1.3.1)

PLAYERS: open the exe, paste your Discord user ID, press START. Updates install from the button inside the app.

=====================  ONE-TIME SETUP FOR YOU (the owner)  =====================
Goal: your code and webhooks stay private; only the finished exe is public.

1) NEW WEBHOOKS
   The old main webhook was visible in your public repo, so make a NEW one in Discord (channel settings >
   Integrations > Webhooks) and delete the old one. You also have the test-channel webhook.

2) A PUBLIC REPO JUST FOR THE EXE
   github.com > New repository > name:  hatcher-releases  > Public > tick "Add a README file" > Create.

3) A TOKEN SO THE BUILD CAN PUBLISH THERE
   GitHub > your profile picture > Settings > Developer settings > Personal access tokens > Fine-grained tokens
   > Generate new token.  Name: releases.  Repository access: "Only select repositories" > hatcher-releases.
   Permissions > Repository permissions > Contents: Read and write.  Generate, then COPY the token.

4) SECRETS IN YOUR CODE REPO (hatcher)
   hatcher > Settings > Secrets and variables > Actions > New repository secret. Add these three:
     RELEASES_TOKEN        the token from step 3
     HATCH_WEBHOOK_MAIN    your NEW main webhook link
     HATCH_WEBHOOK_TEST    your test webhook link

5) UPLOAD THIS FOLDER'S FILES TO hatcher (replace the old ones), including the new workflow file
   .github/workflows/build-exe.yml.   Do NOT upload webhooks.txt, hw_secrets.py or any .exe.

6) RELEASE
   hatcher > Actions > "Build and release Secret Hatch Notifer+" > Run workflow > type  v1.3.1  > Run.
   About 10 minutes later the exe is on  hatcher-releases > Releases.  (It is also published in hatcher once,
   so people on 1.2.0 can still update to 1.3.1 through their Update button.)

7) AFTER EVERYONE IS ON 1.3.1 OR NEWER
   Make hatcher PRIVATE (Settings > bottom > Danger Zone > Change visibility). From then on only the exe is public.
   Also delete the last step of build-exe.yml ("Also publish here").

EACH FUTURE UPDATE: raise APP_VERSION in hatch_watcher.py, upload it, then Actions > Run workflow > type the new
version (for example v1.3.2). Everyone sees the Update button and installs it inside the app.

BUILDING ON YOUR OWN PC INSTEAD: create webhooks.txt next to build_exe.bat with two lines
     main=YOUR_MAIN_WEBHOOK_LINK
     test=YOUR_TEST_WEBHOOK_LINK
then double-click build_exe.bat. (webhooks.txt is ignored by git; never upload it.)

HONEST NOTE ON SAFETY: an exe can always be taken apart by a determined person, and the webhook has to be inside it
to work. This setup keeps your source code and webhooks out of public view and makes copying hard, but only a relay
server (the app talks to your server, your server holds the webhook) makes the webhook truly un-stealable.
