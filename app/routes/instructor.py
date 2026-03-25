"""
Instructor-facing routes.

/                       — home: list courses
/setup                  — upload DuckWeb PDF and configure policy
/course/<id>            — course dashboard (attendance grid)
/course/<id>/session/new  — open a new session
/course/<id>/session/<sid>  — session detail (QR, live submissions, flag review)
/course/<id>/session/<sid>/close  — close the session window
/course/<id>/session/<sid>/attendance  — mark absents manually
/course/<id>/export     — download .xlsx
/attendance/<id>/accept — accept a flagged record
/attendance/<id>/reject — mark a flagged record absent
"""

import secrets
import os
from datetime import datetime, timedelta, timezone, date

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, send_file, current_app
)

from app.models import db, Course, Student, Session, Attendance
from app.utils.pdf_parser import parse_class_list
from app.utils.qr_generator import generate_qr_base64
from app.utils.export import generate_export
from app.utils.summarize import summarize_reflections

bp = Blueprint("instructor", __name__)


@bp.route("/")
def index():
    courses = Course.query.order_by(Course.created_at.desc()).all()
    return render_template("instructor/index.html", courses=courses)


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        mode = request.form.get("setup_mode", "file")
        free_absences  = int(request.form.get("free_absences", 2))
        deduction      = float(request.form.get("deduction_per_absence", 5.0))
        window_minutes = int(request.form.get("default_window_minutes", 10))
        custom_prompt  = request.form.get("reflection_prompt", "").strip()

        if mode == "manual":
            # ── Manual name entry path ──────────────────────────────────────
            course_name = request.form.get("manual_course_name", "").strip()
            crn         = request.form.get("manual_crn", "").strip() or "N/A"
            term        = request.form.get("manual_term", "").strip()
            names_raw   = request.form.get("manual_names", "")

            if not course_name:
                flash("Please enter a course name.", "error")
                return redirect(url_for("instructor.setup"))
            if not term:
                flash("Please enter a term (e.g. Spring 2026).", "error")
                return redirect(url_for("instructor.setup"))

            students_parsed = _parse_name_list(names_raw)
            if not students_parsed:
                flash("No valid student names found. Please check your list.", "error")
                return redirect(url_for("instructor.setup"))

            course = Course(
                crn=crn,
                course_name=course_name,
                term=term,
                term_code=term.replace(" ", ""),
                credits=None,
                meeting_days="",
                meeting_time="",
                location="",
                instructor_name="",
                free_absences=free_absences,
                deduction_per_absence=deduction,
                default_window_minutes=window_minutes,
                token=secrets.token_urlsafe(32),
            )

        else:
            # ── DuckWeb file upload path ────────────────────────────────────
            upload = request.files.get("class_list_pdf")
            allowed = (".pdf", ".xls", ".xlsx")
            if not upload or not any(upload.filename.lower().endswith(ext) for ext in allowed):
                flash("Please upload a DuckWeb class list PDF or Excel (.xls) file.", "error")
                return redirect(url_for("instructor.setup"))

            suffix = os.path.splitext(upload.filename)[1].lower()
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                upload.save(tmp.name)
                tmp_path = tmp.name

            try:
                parsed = parse_class_list(tmp_path)
            except Exception as e:
                flash(f"Could not parse file: {e}", "error")
                return redirect(url_for("instructor.setup"))
            finally:
                os.unlink(tmp_path)

            if not parsed["students"]:
                flash("No students found in the file. Please check it and try again.", "error")
                return redirect(url_for("instructor.setup"))

            students_parsed = parsed["students"]
            course = Course(
                crn=parsed["crn"],
                course_name=parsed["course_name"],
                term=parsed["term"],
                term_code=parsed["term_code"],
                credits=parsed["credits"],
                meeting_days=parsed["meeting_days"],
                meeting_time=parsed["meeting_time"],
                location=parsed["location"],
                instructor_name=parsed["instructor_name"],
                free_absences=free_absences,
                deduction_per_absence=deduction,
                default_window_minutes=window_minutes,
                token=secrets.token_urlsafe(32),
            )

        if custom_prompt:
            course.default_reflection_prompt = custom_prompt

        db.session.add(course)
        db.session.flush()

        for s in students_parsed:
            db.session.add(Student(
                course_id=course.id,
                last_name=s["last_name"],
                first_name=s["first_name"],
                middle_initial=s.get("middle_initial", ""),
            ))

        db.session.commit()
        flash(f"Course '{course.course_name}' set up with {len(students_parsed)} students.", "success")
        return redirect(url_for("instructor.course", course_id=course.id))

    return render_template("instructor/setup.html")


def _parse_name_list(raw_text):
    """
    Parse a pasted list of student names (one per line).
    Accepts:
      - "Last, First"          → last=Last, first=First
      - "Last, First Middle"   → last=Last, first=First, middle=M
      - "First Last"           → last=Last, first=First
      - "First Middle Last"    → last=Last, first=First, middle=M
    Returns a list of dicts with last_name, first_name, middle_initial.
    """
    students = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line:
            # "Last, First [Middle]"
            parts = line.split(",", 1)
            last = parts[0].strip().title()
            rest = parts[1].strip().split()
            if not rest:
                continue
            first = rest[0].title()
            middle = rest[1][0].upper() if len(rest) > 1 else ""
        else:
            # "First [Middle] Last"
            parts = line.split()
            if len(parts) < 2:
                continue
            first = parts[0].title()
            last  = parts[-1].title()
            middle = parts[1][0].upper() if len(parts) > 2 else ""
        students.append({"last_name": last, "first_name": first, "middle_initial": middle})
    return students


@bp.route("/course/<int:course_id>")
def course(course_id):
    course = Course.query.get_or_404(course_id)
    students = Student.query.filter_by(course_id=course.id).order_by(
        Student.last_name, Student.first_name
    ).all()
    sessions = Session.query.filter_by(course_id=course.id).order_by(
        Session.session_number
    ).all()

    # Build attendance matrix: student_id -> {session_id -> Attendance}
    all_records = Attendance.query.join(Session).filter(
        Session.course_id == course.id
    ).all()
    matrix = {}
    for record in all_records:
        matrix.setdefault(record.student_id, {})[record.session_id] = record

    # Compute absence stats per student
    student_stats = []
    for student in students:
        absences = sum(
            1 for s in sessions
            if matrix.get(student.id, {}).get(s.id) is None
            or matrix.get(student.id, {}).get(s.id).status == "absent"
        )
        excess = max(0, absences - course.free_absences)
        deduction = excess * course.deduction_per_absence
        student_stats.append({
            "student": student,
            "absences": absences,
            "excess": excess,
            "deduction": deduction,
            "at_limit": absences == course.free_absences,
            "over_limit": absences > course.free_absences,
        })

    course_url = url_for("student.course_attend", course_token=course.token, _external=True)
    course_qr = generate_qr_base64(course_url)

    return render_template(
        "instructor/course.html",
        course=course,
        students=students,
        sessions=sessions,
        matrix=matrix,
        student_stats=student_stats,
        today=date.today().isoformat(),
        course_url=course_url,
        course_qr=course_qr,
    )


@bp.route("/course/<int:course_id>/session/new", methods=["POST"])
def new_session(course_id):
    course = Course.query.get_or_404(course_id)

    session_date_str = request.form.get("session_date", date.today().isoformat())
    try:
        session_date = date.fromisoformat(session_date_str)
    except ValueError:
        session_date = date.today()

    window_minutes = int(request.form.get("window_minutes", course.default_window_minutes))
    custom_prompt = request.form.get("reflection_prompt", "").strip()

    last_session = Session.query.filter_by(course_id=course.id).order_by(
        Session.session_number.desc()
    ).first()
    session_number = (last_session.session_number + 1) if last_session else 1

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)

    session = Session(
        course_id=course.id,
        session_number=session_number,
        session_date=session_date,
        token=token,
        open_at=now,
        close_at=now + timedelta(minutes=window_minutes),
        reflection_prompt=custom_prompt if custom_prompt else None,
    )
    db.session.add(session)

    # Pre-populate all students as absent; they move to "present" on submission
    students = Student.query.filter_by(course_id=course.id).all()
    for student in students:
        record = Attendance(
            session_id=session.id,
            student_id=student.id,
            status="absent",
        )
        db.session.add(record)

    db.session.commit()

    flash(f"Session #{session_number} opened. Window closes in {window_minutes} minutes.", "success")
    return redirect(url_for("instructor.session_detail", course_id=course.id, session_id=session.id))


@bp.route("/course/<int:course_id>/session/<int:session_id>")
def session_detail(course_id, session_id):
    course = Course.query.get_or_404(course_id)
    session = Session.query.get_or_404(session_id)

    student_url = url_for("student.course_attend", course_token=course.token, _external=True)
    qr_data = generate_qr_base64(student_url)

    records = Attendance.query.filter_by(session_id=session.id).all()
    present = [r for r in records if r.status == "present"]
    absent = [r for r in records if r.status == "absent"]
    flagged = [r for r in records if r.flag_list]

    # Build student lookup
    student_map = {s.id: s for s in Student.query.filter_by(course_id=course.id).all()}

    prompt = session.reflection_prompt or course.default_reflection_prompt

    return render_template(
        "instructor/session.html",
        course=course,
        session=session,
        student_url=student_url,
        qr_data=qr_data,
        present=present,
        absent=absent,
        flagged=flagged,
        student_map=student_map,
        prompt=prompt,
    )


@bp.route("/course/<int:course_id>/session/<int:session_id>/close", methods=["POST"])
def close_session(course_id, session_id):
    session = Session.query.get_or_404(session_id)
    session.close_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("Session window closed.", "success")
    return redirect(url_for("instructor.session_detail", course_id=course_id, session_id=session_id))


@bp.route("/course/<int:course_id>/session/<int:session_id>/extend", methods=["POST"])
def extend_session(course_id, session_id):
    session = Session.query.get_or_404(session_id)
    extra_minutes = int(request.form.get("extra_minutes", 5))
    now = datetime.now(timezone.utc)
    if session.close_at:
        close_aware = session.close_at.replace(tzinfo=timezone.utc) if session.close_at.tzinfo is None else session.close_at
        base = max(close_aware, now)
    else:
        base = now
    session.close_at = base + timedelta(minutes=extra_minutes)
    db.session.commit()
    flash(f"Window extended by {extra_minutes} minutes.", "success")
    return redirect(url_for("instructor.session_detail", course_id=course_id, session_id=session_id))


@bp.route("/attendance/<int:record_id>/accept", methods=["POST"])
def accept_attendance(record_id):
    record = Attendance.query.get_or_404(record_id)
    record.status = "present"
    record.flag_reasons = None  # clear flags
    db.session.commit()
    flash("Attendance accepted.", "success")
    return redirect(request.referrer or url_for("instructor.index"))


@bp.route("/attendance/<int:record_id>/reject", methods=["POST"])
def reject_attendance(record_id):
    record = Attendance.query.get_or_404(record_id)
    record.status = "absent"
    record.flag_reasons = None
    db.session.commit()
    flash("Attendance marked absent.", "success")
    return redirect(request.referrer or url_for("instructor.index"))


@bp.route("/attendance/<int:record_id>/note", methods=["POST"])
def save_note(record_id):
    """AJAX endpoint — save an instructor note on an attendance record."""
    from flask import jsonify
    record = Attendance.query.get_or_404(record_id)
    data = request.get_json()
    record.instructor_note = (data.get("note") or "").strip() or None
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/course/<int:course_id>/attendance/set", methods=["POST"])
def set_attendance(course_id):
    """AJAX endpoint — manually override a single attendance cell."""
    from flask import jsonify
    course = Course.query.get_or_404(course_id)
    data = request.get_json()
    student_id = data.get("student_id")
    session_id = data.get("session_id")
    new_status = data.get("status")  # "P", "A", or "P*"

    if new_status not in ("P", "A", "P*"):
        return jsonify({"error": "Invalid status"}), 400

    student = Student.query.filter_by(id=student_id, course_id=course_id).first_or_404()
    session = Session.query.filter_by(id=session_id, course_id=course_id).first_or_404()

    record = Attendance.query.filter_by(
        session_id=session.id, student_id=student.id
    ).first()

    if new_status == "A":
        if record:
            record.status = "absent"
            record.flag_reasons = None
        else:
            record = Attendance(session_id=session.id, student_id=student.id, status="absent")
            db.session.add(record)
    elif new_status == "P":
        if record:
            record.status = "present"
            record.flag_reasons = None
        else:
            record = Attendance(session_id=session.id, student_id=student.id, status="present")
            db.session.add(record)
    elif new_status == "P*":
        if record:
            record.status = "present"
            if not record.flag_reasons:
                record.flag_reasons = "manual_flag"
        else:
            record = Attendance(
                session_id=session.id, student_id=student.id,
                status="present", flag_reasons="manual_flag"
            )
            db.session.add(record)

    db.session.commit()
    return jsonify({"success": True, "status": new_status, "record_id": record.id, "note": record.instructor_note or ""})


@bp.route("/course/<int:course_id>/export")
def export(course_id):
    course = Course.query.get_or_404(course_id)
    output = generate_export(course)
    filename = f"{course.term_code}_{course.crn}_attendance.xlsx".replace(" ", "_")
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/course/<int:course_id>/session/<int:session_id>/summarize", methods=["POST"])
def summarize_session(course_id, session_id):
    course = Course.query.get_or_404(course_id)
    session = Session.query.get_or_404(session_id)

    # Collect present (non-flagged) reflection texts for summarization
    records = Attendance.query.filter_by(session_id=session.id, status="present").all()
    reflections = [r.reflection_text for r in records if r.reflection_text]

    if not reflections:
        flash("No reflections to summarize yet.", "warning")
        return redirect(url_for("instructor.session_detail", course_id=course_id, session_id=session_id))

    prompt = session.reflection_prompt or course.default_reflection_prompt
    summary = summarize_reflections(reflections, prompt)

    if summary:
        session.summary = summary
        db.session.commit()
        flash("Summary generated.", "success")
    else:
        flash("Could not generate summary. Make sure ANTHROPIC_API_KEY is set.", "error")

    return redirect(url_for("instructor.session_detail", course_id=course_id, session_id=session_id))


@bp.route("/course/<int:course_id>/session/<int:session_id>/delete", methods=["POST"])
def delete_session(course_id, session_id):
    session = Session.query.filter_by(id=session_id, course_id=course_id).first_or_404()
    # Cascade-delete all attendance records for this session
    Attendance.query.filter_by(session_id=session.id).delete()
    db.session.delete(session)
    db.session.commit()
    flash(f"Session #{session.session_number} deleted.", "success")
    return redirect(url_for("instructor.course", course_id=course_id))


@bp.route("/course/<int:course_id>/delete", methods=["POST"])
def delete_course(course_id):
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    flash(f"Course '{course.course_name}' deleted.", "success")
    return redirect(url_for("instructor.index"))
