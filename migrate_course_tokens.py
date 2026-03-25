"""
One-time migration: add `token` column to the courses table and
backfill a unique token for every existing course.

Run once while the app is stopped:
    .venv/bin/python3 migrate_course_tokens.py
"""
import os
import secrets
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "attendance.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Add the column (skip if it already exists)
existing = [row[1] for row in cur.execute("PRAGMA table_info(courses)")]
if "token" not in existing:
    cur.execute("ALTER TABLE courses ADD COLUMN token TEXT")
    print("Added 'token' column to courses table.")
else:
    print("'token' column already exists — skipping ALTER TABLE.")

# Backfill any courses that don't have a token yet
cur.execute("SELECT id FROM courses WHERE token IS NULL")
rows = cur.fetchall()
for (course_id,) in rows:
    token = secrets.token_urlsafe(32)
    cur.execute("UPDATE courses SET token=? WHERE id=?", (token, course_id))
    print(f"  Assigned token to course id={course_id}")

# Unique index for fast lookups
cur.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_courses_token ON courses (token)"
)

conn.commit()
conn.close()
print(f"Done. {len(rows)} course(s) backfilled.")
