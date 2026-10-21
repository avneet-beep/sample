# Zoho Recruit - API explorer

`explore.py` connects to Zoho Recruit over the v2 REST API and maps the account:
modules, fields, custom fields, picklists (candidate sources, statuses), lookups
between modules, layouts, related lists, users and record counts. It writes:

- `out/snapshot.json` - everything fetched (structure only, no candidate data)
- `out/diagram.md` - Mermaid flowcharts built from the snapshot: sources into
  Candidates, how modules link, and one pipeline per status/stage picklist

It only sends GET requests. `out/` is git-ignored because it holds user names.

`recruit-flow.html` is the general platform map (inputs, hiring core, outputs,
candidate path, API connection flow).

## Setup (India data centre)

1. Open https://api-console.zoho.in, *Add Client > Self Client*.
2. *Generate Code* with scopes
   `ZohoRecruit.modules.ALL,ZohoRecruit.settings.ALL,ZohoRecruit.users.ALL,ZohoRecruit.org.ALL`
   and a 10 minute duration.
3. Exchange the code for a refresh token (one time):

   ```sh
   curl -X POST https://accounts.zoho.in/oauth/v2/token \
     -d grant_type=authorization_code -d code=<CODE> \
     -d client_id=<ID> -d client_secret=<SECRET>
   ```
4. Set `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`
   (and `ZOHO_DC` if not `in`). In a Claude Code cloud session, add them as
   environment secrets and allow `accounts.zoho.in` and `recruit.zoho.in`
   in the environment's network access.

## Run

```sh
python3 zoho-recruit/explore.py                         # fetch + draw
python3 zoho-recruit/explore.py --from zoho-recruit/out/snapshot.json   # redraw only
```

`MAX_COUNT_PAGES` (default 10) caps record counting at 200 x pages per module.
