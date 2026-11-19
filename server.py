"""Planet Rescue Day - signup server.

Serves the signup page and the /api/signups API from one address.
Fictional data only.

Storage
  - DATABASE_URL set (Render):  PostgreSQL. Survives restarts and redeploys.
  - DATABASE_URL not set (laptop): SQLite file signups.db next to this file.

Run locally:  python server.py      ->  http://localhost:8000
On Render:    python server.py      (Render sets PORT and DATABASE_URL)

API
  GET    /api/signups        list every signup (with waitlist positions), plus spots per activity
  POST   /api/signups        sign up, join the waitlist if full, or switch activity if already signed up
  PATCH  /api/signups/<id>   mark attendance  {"attended": true/false}
  DELETE /api/signups/<id>   cancel a signup (the first person on that waitlist moves up)
"""

import json
import os
import re
import sqlite3
import traceback
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "signups.db"
PUBLIC = HERE / "public"

# Render tells the app which port to use through PORT, and the server must
# listen on 0.0.0.0 there. On a laptop (no PORT set) it stays private on 127.0.0.1.
PORT = int(os.environ.get("PORT", 8000))
HOST = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"

DATABASE_URL = os.environ.get("DATABASE_URL")  # a secret: never print or log it
USE_POSTGRES = bool(DATABASE_URL)
if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row

ACTIVITIES = [
    "Beach Cleanup — 9:00 AM",
    "Tree Planting — 11:00 AM",
    "Recycling Sort-Off — 1:00 PM",
]
SPOTS_PER_ACTIVITY = 5  # bonus: limit available spots

ID_PATH = re.compile(r"^/api/signups/(\d+)$")
FIELDS = "id, name, activity, attended, waitlisted, created_at"


# ---------- database ----------

class Database:
    """Small wrapper so the same queries work on SQLite and PostgreSQL.

    Queries are written with ? placeholders (parameterized, never pasted into
    the SQL text). For PostgreSQL they are switched to %s automatically.
    """

    def __init__(self, conn):
        self.conn = conn

    def run(self, sql, params=()):
        if USE_POSTGRES:
            sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def one(self, sql, params=()):
        return self.run(sql, params).fetchone()

    def all(self, sql, params=()):
        return self.run(sql, params).fetchall()

    def commit(self):
        self.conn.commit()


@contextmanager
def db():
    if USE_POSTGRES:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield Database(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def setup_database():
    """Create the table if it is missing. Safe on every start: never deletes rows."""
    with db() as d:
        if USE_POSTGRES:
            d.run(
                """CREATE TABLE IF NOT EXISTS signups (
                       id SERIAL PRIMARY KEY,
                       name TEXT NOT NULL,
                       activity TEXT NOT NULL,
                       attended INTEGER NOT NULL DEFAULT 0,
                       waitlisted INTEGER NOT NULL DEFAULT 0,
                       queued_at INTEGER,
                       created_at TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
                   )"""
            )
        else:
            d.run(
                """CREATE TABLE IF NOT EXISTS signups (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL,
                       activity TEXT NOT NULL,
                       attended INTEGER NOT NULL DEFAULT 0,
                       waitlisted INTEGER NOT NULL DEFAULT 0,
                       queued_at INTEGER,
                       created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                   )"""
            )
            # Local databases from earlier versions are missing the newer columns.
            columns = [row["name"] for row in d.all("PRAGMA table_info(signups)")]
            if "attended" not in columns:
                d.run("ALTER TABLE signups ADD COLUMN attended INTEGER NOT NULL DEFAULT 0")
            if "waitlisted" not in columns:
                d.run("ALTER TABLE signups ADD COLUMN waitlisted INTEGER NOT NULL DEFAULT 0")
            if "queued_at" not in columns:
                d.run("ALTER TABLE signups ADD COLUMN queued_at INTEGER")


def to_dict(row):
    data = dict(row)
    data["attended"] = bool(data["attended"])
    data["waitlisted"] = bool(data["waitlisted"])
    return data


def get_signup(d, row_id):
    return d.one(f"SELECT {FIELDS} FROM signups WHERE id = ?", (row_id,))


def spots_left(d):
    """Open spots per activity. Only confirmed signups take a spot."""
    left = {}
    for activity in ACTIVITIES:
        taken = d.one(
            "SELECT COUNT(*) AS n FROM signups WHERE activity = ? AND waitlisted = 0", (activity,)
        )["n"]
        left[activity] = max(SPOTS_PER_ACTIVITY - taken, 0)
    return left


def next_queue_number(d):
    """Waitlist order: a bigger number means the person joined the line later."""
    return d.one("SELECT COALESCE(MAX(queued_at), 0) + 1 AS n FROM signups")["n"]


def waitlist_position(d, row_id):
    row = d.one("SELECT activity, queued_at FROM signups WHERE id = ?", (row_id,))
    return d.one(
        "SELECT COUNT(*) AS n FROM signups WHERE activity = ? AND waitlisted = 1 AND queued_at <= ?",
        (row["activity"], row["queued_at"]),
    )["n"]


def promote_from_waitlist(d, activity):
    """Custom feature: fill open spots with the first people in line. Returns who moved up."""
    promoted = []
    while spots_left(d)[activity] > 0:
        first = d.one(
            "SELECT id, name FROM signups WHERE activity = ? AND waitlisted = 1 "
            "ORDER BY queued_at, id LIMIT 1",
            (activity,),
        )
        if not first:
            break
        d.run("UPDATE signups SET waitlisted = 0, queued_at = NULL WHERE id = ?", (first["id"],))
        promoted.append({"name": first["name"], "activity": activity})
    return promoted


# ---------- web server ----------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def api(self, action):
        """Run one API action; a database problem becomes a friendly error, not a crash."""
        try:
            action()
        except Exception:
            traceback.print_exc()  # goes to the server log; contains no connection URL
            self.send_json(500, {"error": "Oops — something went wrong on the server. Please try again."})

    def do_GET(self):
        if self.path == "/api/signups":
            self.api(self.list_signups)
        else:
            super().do_GET()  # the page itself (public/index.html)

    def do_POST(self):
        if self.path == "/api/signups":
            self.api(self.create_signup)
        else:
            self.send_json(404, {"error": "Not found"})

    def do_PATCH(self):
        match = ID_PATH.match(self.path)
        if match:
            self.api(lambda: self.set_attendance(int(match[1])))
        else:
            self.send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        match = ID_PATH.match(self.path)
        if match:
            self.api(lambda: self.cancel_signup(int(match[1])))
        else:
            self.send_json(404, {"error": "Not found"})

    # ---- list ----
    def list_signups(self):
        with db() as d:
            rows = d.all(f"SELECT {FIELDS} FROM signups ORDER BY id")
            signups = []
            for r in rows:
                item = to_dict(r)
                if item["waitlisted"]:
                    item["position"] = waitlist_position(d, item["id"])
                signups.append(item)
            result = {
                "signups": signups,
                "spotsLeft": spots_left(d),
                "spotsPerActivity": SPOTS_PER_ACTIVITY,
            }
        self.send_json(200, result)

    # ---- sign up, join the waitlist, or switch activity ----
    def create_signup(self):
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Oops — the signup could not be read."})
            return

        # The server checks the fields again, even though the page already did.
        name = str(data.get("name", "")).strip()
        activity = str(data.get("activity", ""))
        if not name:
            self.send_json(400, {"error": "Oops — please enter your name before signing up."})
            return
        if activity not in ACTIVITIES:
            self.send_json(400, {"error": "Oops — please choose an activity before signing up."})
            return

        with db() as d:
            # Bonus: prevent duplicate signups (same name, ignoring capital letters).
            existing = d.one(
                f"SELECT {FIELDS} FROM signups WHERE LOWER(name) = LOWER(?)", (name,)
            )
            if existing and existing["activity"] == activity:
                where = "on the waitlist for" if existing["waitlisted"] else "already signed up for"
                self.send_json(409, {"error": f"Oops — {existing['name']} is {where} {activity}."})
                return

            # Bonus: limit available spots. Custom feature: a full activity puts you on its waitlist.
            full = spots_left(d)[activity] == 0
            waitlisted = 1 if full else 0
            queued_at = next_queue_number(d) if full else None

            promoted = []
            if existing:
                # Bonus: switch activities. Same person, new activity, no second row.
                old_activity, was_waitlisted = existing["activity"], existing["waitlisted"]
                d.run(
                    "UPDATE signups SET activity = ?, name = ?, attended = 0, waitlisted = ?, queued_at = ? "
                    "WHERE id = ?",
                    (activity, name, waitlisted, queued_at, existing["id"]),
                )
                if not was_waitlisted:
                    promoted = promote_from_waitlist(d, old_activity)  # their old spot opened up
                row_id, status, switched = existing["id"], 200, True
            else:
                row_id = d.one(
                    "INSERT INTO signups (name, activity, waitlisted, queued_at) VALUES (?, ?, ?, ?) "
                    "RETURNING id",
                    (name, activity, waitlisted, queued_at),
                )["id"]
                status, switched = 201, False

            result = {**to_dict(get_signup(d, row_id)), "switched": switched, "promoted": promoted}
            if waitlisted:
                result["position"] = waitlist_position(d, row_id)
            d.commit()  # save before replying, so the next list read sees it
        self.send_json(status, result)

    # ---- mark attendance ----
    def set_attendance(self, row_id):
        try:
            attended = bool(self.read_json().get("attended"))
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Oops — the update could not be read."})
            return
        with db() as d:
            row = d.one("SELECT waitlisted FROM signups WHERE id = ?", (row_id,))
            if not row:
                self.send_json(404, {"error": "Oops — that signup no longer exists."})
                return
            if row["waitlisted"]:
                self.send_json(400, {"error": "Oops — people on the waitlist can't check in yet."})
                return
            d.run("UPDATE signups SET attended = ? WHERE id = ?", (int(attended), row_id))
            result = to_dict(get_signup(d, row_id))
            d.commit()
        self.send_json(200, result)

    # ---- cancel a signup ----
    def cancel_signup(self, row_id):
        with db() as d:
            row = d.one("SELECT activity, waitlisted FROM signups WHERE id = ?", (row_id,))
            if not row:
                self.send_json(404, {"error": "Oops — that signup no longer exists."})
                return
            d.run("DELETE FROM signups WHERE id = ?", (row_id,))
            # Custom feature: if a real spot opened, the first person on the waitlist moves up.
            promoted = [] if row["waitlisted"] else promote_from_waitlist(d, row["activity"])
            d.commit()
        self.send_json(200, {"deleted": row_id, "promoted": promoted})


if __name__ == "__main__":
    setup_database()
    print("Storage: PostgreSQL (DATABASE_URL is set)" if USE_POSTGRES
          else f"Storage: SQLite file {DB_PATH.name} (local only)")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Planet Rescue Day is listening on {HOST}:{PORT}"
          + ("" if "PORT" in os.environ else f"  ->  open http://localhost:{PORT}"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
