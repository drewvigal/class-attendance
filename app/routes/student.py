"""
Student-facing routes.

/attend/course/<course_token>         — permanent per-course check-in form
/attend/course/<course_token>/submit  — POST: submit attendance via course token

Legacy session-token routes are kept below for backwards compatibility
(old tabs / bookmarks) but are no longer used in QR codes.
"""

from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.models import db, Session, Student, Attendance, Course
from app.utils.anti_gaming import hash_ip, get_flag_reasons

bp = Blueprint("student", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_active_session(course):
    # type: (Course) -> Optional[Session]
    """Return the currently open session for this course, or None."""
    for s in Session.query.filter_by(course_id=course.id).all():
        if s.is_open:
            return s
    return None


def _do_submit(session, course, course_token):
    """Shared submission logic used by both the course-token and legacy routes."""
    student_id = request.form.get("student_id", type=int)
    reflection = request.form.get("reflection", "").strip()

    if not student_id or not reflection:
        flash("Please select your name and write a reflection.", "error")
        return redirect(url_for("student.course_attend", course_token=course_token))

    student = Student.query.filter_by(id=student_id, course_id=course.id).first()
    if not student:
        flash("Name not found on this class roster. Please check your selection.", "error")
        return redirect(url_for("student.course_attend", course_token=course_token))

    # Check for duplicate submission
    existing = Attendance.query.filter_by(
        session_id=session.id, student_id=student.id
    ).first()
    if existing and existing.status == "present":
        return render_template(
            "student/confirm.html",
            session=session,
            course=course,
            student=student,
            already_submitted=True,
            flags=[],
        )

    # Gather anti-gaming data
    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    ip_address = ip_address.split(",")[0].strip()
    ip_hash = hash_ip(ip_address)

    now = datetime.now(timezone.utc)

    existing_records = Attendance.query.filter_by(session_id=session.id).filter(
        Attendance.student_id != student.id
    ).all()

    prompt_text = session.reflection_prompt or course.default_reflection_prompt
    flags = get_flag_reasons(
        reflection_text=reflection,
        submitted_at=now,
        session=session,
        existing_records=existing_records,
        ip_hash=ip_hash,
        prompt_text=prompt_text,
    )

    # Update (or create) the attendance record
    record = Attendance.query.filter_by(
        session_id=session.id, student_id=student.id
    ).first()

    if record is None:
        record = Attendance(session_id=session.id, student_id=student.id)
        db.session.add(record)

    record.status = "present"
    record.submitted_at = now
    record.reflection_text = reflection
    record.ip_hash = ip_hash

    for reason in flags:
        record.add_flag(reason)

    db.session.commit()

    return render_template(
        "student/confirm.html",
        session=session,
        course=course,
        student=student,
        flags=flags,
        already_submitted=False,
    )


# ---------------------------------------------------------------------------
# Course-token routes (permanent per-course URL — shown in QR codes)
# ---------------------------------------------------------------------------

@bp.route("/attend/course/<course_token>")
def course_attend(course_token):
    course = Course.query.filter_by(token=course_token).first_or_404()
    active_session = _find_active_session(course)

    if active_session is None:
        return render_template("student/not_open.html", course=course)

    students = Student.query.filter_by(course_id=course.id).order_by(
        Student.last_name, Student.first_name
    ).all()
    prompt = active_session.reflection_prompt or course.default_reflection_prompt

    return render_template(
        "student/form.html",
        session=active_session,
        course=course,
        students=students,
        prompt=prompt,
        window_status=active_session.status_label,
        course_token=course_token,
    )


@bp.route("/attend/course/<course_token>/submit", methods=["POST"])
def course_submit(course_token):
    course = Course.query.filter_by(token=course_token).first_or_404()

    # Re-resolve the active session at submit time (window may have closed)
    active_session = _find_active_session(course)
    if active_session is None:
        flash("The check-in window has closed.", "error")
        return redirect(url_for("student.course_attend", course_token=course_token))

    return _do_submit(active_session, course, course_token)


# ---------------------------------------------------------------------------
# Legacy session-token routes (kept for backwards compatibility only)
# ---------------------------------------------------------------------------

@bp.route("/attend/<token>")
def attend(token):
    session = Session.query.filter_by(token=token).first_or_404()
    course = Course.query.get_or_404(session.course_id)
    # Redirect to the permanent course URL
    return redirect(url_for("student.course_attend", course_token=course.token))


@bp.route("/attend/<token>/submit", methods=["POST"])
def submit(token):
    session = Session.query.filter_by(token=token).first_or_404()
    course = Course.query.get_or_404(session.course_id)
    return _do_submit(session, course, course.token)
