# Class Attendance Tracker

A lightweight web tool for UO SOJC faculty to track class attendance over a 10-week term. Students check in via QR code and submit a brief learning reflection — harder to fake than a code word, and useful for gauging class comprehension.

---

## Features

- **Upload your DuckWeb class list PDF** — student names extracted automatically (no UO IDs or emails stored)
- **QR code per session** — display on screen; students scan and submit from their phones
- **Time-limited window** — instructor controls open/close; late submissions are flagged, not rejected
- **Learning reflection** — 25-word minimum; low-effort entries auto-flagged for review
- **Anti-gaming flags**: duplicate submissions, same-device multiple entries, near-identical peer reflections
- **Instructor dashboard** — color-coded attendance grid, absence counts, grade impact preview
- **Configurable policy** — default: 2 free absences, then −5% per additional miss (no hard ceiling)
- **Excel export** — `.xlsx` with attendance grid, grade summary, and full reflection digest

---

## Quick Start (Local)

```bash
# 1. Clone and install
git clone https://github.com/YOUR_USERNAME/attendance-tracker.git
cd attendance-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set SECRET_KEY to a long random string:
python -c "import secrets; print(secrets.token_hex(32))"

# 3. Run
python run.py
# Open http://localhost:5000
```

---

## Deploy to Render (Recommended for 24/7 Access)

Each instructor gets their own isolated instance — no shared data.

1. **Fork this repository** to your own GitHub account
2. Go to [render.com](https://render.com) and sign up (free)
3. Click **New → Web Service** → connect your forked repo
4. Render auto-detects `render.yaml` — click **Deploy**
5. Set one environment variable: `SECRET_KEY` → a long random string
6. Your app is live at `https://your-app-name.onrender.com`

> **Persistent storage:** The `render.yaml` mounts a 1 GB disk at `/instance` so your SQLite database survives restarts. On the free tier, the disk persists across deploys.

---

## Usage Guide

### Setting Up a Course
1. Go to **+ New Course**
2. Upload your DuckWeb class list PDF (export from DuckWeb → Class List → Download to PDF)
3. Configure your attendance policy (or keep the defaults)
4. Click **Create Course**

### Running a Session
1. Open your course dashboard
2. Click **Open Session** — set the date and window duration
3. Display the QR code on the projector
4. Students scan, select their name, and write a reflection
5. Monitor live check-ins; extend the window if needed
6. Review flagged submissions and accept or mark absent

### End of Term
- Click **Export .xlsx** from the course dashboard
- Three sheets: Attendance Grid, Grade Summary, Reflections
- Import into Canvas gradebook or share with your department

---

## Attendance Policy (Default)

| Absences | Grade Impact |
|---|---|
| 0–2 | No deduction |
| 3 | −5% from final grade |
| 4 | −10% from final grade |
| 5 | −15% from final grade |
| … | −5% per additional miss |

All thresholds and percentages are configurable when you set up a course.

---

## Privacy

- Only student **names** are stored — no UO IDs, no email addresses
- IP addresses are stored as one-way SHA-256 hashes (fraud detection only, not identifiable)
- All data stays in your own SQLite database on your server instance
- No integration with Canvas, Qualtrics, or any external system

---

## Tech Stack

- Python + Flask
- SQLite (via Flask-SQLAlchemy)
- pdfplumber (DuckWeb PDF parsing)
- qrcode (QR generation)
- openpyxl (Excel export)
- Gunicorn (production server)
