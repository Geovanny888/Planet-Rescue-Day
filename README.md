# Planet Rescue Day — Club Event Signup

A signup app for a **fictional** volunteer day hosted by the fictional Green Hawks Eco Club.
Visitors enter a name, pick one activity (Beach Cleanup, Tree Planting, or Recycling Sort-Off),
and press **Count Me In**. Signups are saved in a database and shown in a searchable list.

Use made-up names only.

## Features

- **Required:** register a person · save and display signups · search by name and filter by activity
- **Bonuses:** count by activity · sort A–Z · prevent duplicate signups · switch activities ·
  mark attendance · cancel a signup · limit spots (5 per activity)
- **My own feature:** waitlist. A full activity puts new signups on a waitlist, and the first person
  in line moves in automatically when someone cancels or switches out.

## How to run it

| Item | Value | Where it comes from |
|---|---|---|
| Runtime | Python 3.12 | `.python-version` |
| Install / build command | `pip install -r requirements.txt` | `requirements.txt` |
| Start command | `python server.py` | `server.py` |
| Local address | http://localhost:8000 | `server.py` (PORT, default 8000) |
| Settings (names only) | `DATABASE_URL` (optional), `PORT` (set by Render) | `server.py` |

On a laptop, the install step is only needed for PostgreSQL. Without `DATABASE_URL` the app uses
a local SQLite file (`signups.db`, created automatically and never committed).

On Render, the server listens on `0.0.0.0` at the `PORT` Render gives it, and stores signups in
PostgreSQL through `DATABASE_URL`. One server delivers both the page and the API (`/api/signups`)
from the same address.

## One signup to test

1. Type `Maya Chen` in **Your name**.
2. Choose **Tree Planting — 11:00 AM**.
3. Press **Count Me In**.

Expected result:
`You're in, Maya Chen! Thanks for helping the planet — see you at Tree Planting — 11:00 AM.`
Then type `maya` in **Search names**: Maya Chen appears in the list.

## Files

- `server.py` — web server, API and database code
- `public/index.html` — the page (HTML, CSS and JavaScript)
- `requirements.txt` — the PostgreSQL driver
- `.python-version` — the Python version Render should use

*AI disclosure: built with help from Claude Code, from my own design.md. I chose the event,
activities, layout, messages, and features, and I tested each one.*
