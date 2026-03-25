"""
Parse DuckWeb class list files — both PDF and the HTML-as-.xls export.

DuckWeb .xls exports are actually HTML tables saved with an .xls extension.
Both formats share the same logical structure; we extract names only.
No UO IDs or email addresses are stored.
"""

import re
import os
from html.parser import HTMLParser
import pdfplumber

TERM_CODE_MAP = {"F": "Fall", "W": "Winter", "S": "Spring", "U": "Summer"}

STUDENT_SKIP_NAMES = {"student name", "student", "name"}


def parse_term_code(code):
    """'26S' -> ('Spring 2026', '26S')"""
    if len(code) >= 3:
        year = code[:2]
        season = TERM_CODE_MAP.get(code[2].upper(), code[2])
        return f"{season} 20{year}", code
    return code, code


def parse_duckweb_pdf(file_path):
    """
    Parse a DuckWeb class list PDF.
    Returns a dict with course metadata and list of student name dicts.
    Only names are stored — no UO IDs, no email addresses.
    """
    result = {
        "crn": "",
        "course_name": "",
        "term": "",
        "term_code": "",
        "credits": 4,
        "meeting_days": "",
        "meeting_time": "",
        "location": "",
        "instructor_name": "",
        "enrolled": 0,
        "students": [],
    }

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables()

            # Extract term code from header text on page 1
            if page_num == 0:
                m = re.search(r"TERM:(\w+)", text)
                if m:
                    result["term"], result["term_code"] = parse_term_code(m.group(1))

            for table in tables:
                if not table:
                    continue
                _process_table(table, result, page_num)

    # Deduplicate students (same name may appear in overlapping pages)
    seen = set()
    unique = []
    for s in result["students"]:
        key = (s["last_name"].lower(), s["first_name"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(s)
    result["students"] = unique

    return result


def _process_table(table, result, page_num):
    """Dispatch rows to course-info or student-roster parsing."""
    if not table or not table[0]:
        return

    # Detect table type by examining its headers/columns
    first_row = [str(c or "").strip() for c in table[0]]

    # Student table: first row is header ['Student name', 'UO ID', ...]
    # or data starting with 'Last, First' pattern (continuation on page 2+)
    if first_row[0].lower() == "student name":
        # Skip header row, parse the rest as students
        for row in table[1:]:
            student = _parse_student_row(row)
            if student:
                result["students"].append(student)
        return

    # Page 2+ student continuation: first cell looks like a student name
    if len(first_row) >= 6 and _looks_like_student_name(first_row[0]):
        for row in table:
            student = _parse_student_row(row)
            if student:
                result["students"].append(student)
        return

    # Course/instructor table: look for the CRN row
    for row_idx, row in enumerate(table):
        cells = [str(c or "").strip() for c in row]

        # CRN row: first cell is the 5-digit CRN
        if re.match(r"^\d{5}$", cells[0]) and not result["crn"]:
            result["crn"] = cells[0]
            # Course name is cell 1; strip trailing whitespace
            raw_name = cells[1] if len(cells) > 1 else ""
            result["course_name"] = raw_name.strip()
            # Credits: find the first 1-2 digit value after the course name
            for c in cells[2:]:
                m = re.match(r"^0?(\d{1,2})$", c)
                if m:
                    result["credits"] = int(m.group(1))
                    break
            # Enrolled: next numeric value
            nums = [c for c in cells[2:] if re.match(r"^\d+$", c)]
            if len(nums) >= 2:
                result["enrolled"] = int(nums[1])
            continue

        # Instructor/meeting rows: cell at index 3 is a day code (T, R, M, W, F, etc.)
        if len(cells) > 3 and re.match(r"^[MTWRFSU]{1,3}$", cells[3]):
            day_code = cells[3]
            time_val = cells[4] if len(cells) > 4 else ""
            loc_val = cells[7] if len(cells) > 7 else ""
            name_val = cells[0] if cells[0] else ""

            # Accumulate meeting days (T first row, R second row)
            existing_days = result["meeting_days"].split(",") if result["meeting_days"] else []
            if day_code and day_code not in existing_days:
                existing_days.append(day_code)
            result["meeting_days"] = ",".join(existing_days)

            if not result["meeting_time"] and time_val:
                result["meeting_time"] = time_val

            if not result["instructor_name"] and name_val and name_val.lower() != "instructor":
                result["instructor_name"] = name_val

            continue


def _parse_student_row(row):
    """
    Parse a student table row: [name, UO_ID, class, major, opt/cr, email, notes]
    Returns {last_name, first_name, middle_initial} or None.
    NO UO ID or email stored.
    """
    if not row:
        return None
    name_cell = str(row[0] or "").strip()
    if not name_cell or not _looks_like_student_name(name_cell):
        return None
    return _parse_name(name_cell)


def _smart_title(name):
    """Title-case a name, preserving Mc/Mac prefixes (e.g. MCayden -> MCayden, McConaghie -> McConaghie)."""
    # If the original already has mixed case (not all-caps), preserve it
    if name != name.upper() and name != name.lower():
        return name  # already mixed-case — trust the source
    # All-caps or all-lower: apply title case then fix Mc/Mac
    result = name.title()
    result = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), result)
    result = re.sub(r"\bMac([a-z])", lambda m: "Mac" + m.group(1).upper(), result)
    return result


def _looks_like_student_name(text):
    """'Last, First M' pattern — contains a comma, starts with a letter."""
    if not text or "," not in text:
        return False
    if text.lower().strip() in STUDENT_SKIP_NAMES:
        return False
    return bool(re.match(r"^[A-Za-z''\-]+,\s*[A-Za-z]", text))


def _parse_name(name_str):
    """
    Parse 'Last, First M' into components.
    Returns {"last_name", "first_name", "middle_initial"} or None.
    """
    parts = name_str.split(",", 1)
    last = _smart_title(parts[0].strip())
    rest = parts[1].strip() if len(parts) > 1 else ""

    tokens = rest.split()
    if not tokens:
        return None

    first = _smart_title(tokens[0])
    middle = tokens[1][0].upper() if len(tokens) > 1 else ""

    if not last or not first:
        return None

    return {"last_name": last, "first_name": first, "middle_initial": middle}


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def parse_class_list(file_path):
    """
    Detect file type and parse accordingly.
    Accepts: DuckWeb PDF (.pdf) or DuckWeb Excel export (.xls / .xlsx).
    Returns the same dict structure as parse_duckweb_pdf().
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xls", ".xlsx"):
        return parse_duckweb_xls(file_path)
    return parse_duckweb_pdf(file_path)


# ---------------------------------------------------------------------------
# DuckWeb .xls (HTML) parser
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Collect all <table> contents as a list of lists of cell text."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._current_table = None
        self._current_row = None
        self._current_cell = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            self._current_cell = []
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_table is not None:
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag in ("td", "th") and self._current_cell is not None:
            text = " ".join(self._current_cell).strip()
            if self._current_row is not None:
                self._current_row.append(text)
            self._current_cell = None
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell and self._current_cell is not None:
            stripped = data.strip()
            if stripped:
                self._current_cell.append(stripped)


def parse_duckweb_xls(file_path):
    """
    Parse a DuckWeb class list saved as .xls (HTML format).
    Returns the same structure as parse_duckweb_pdf().
    """
    result = {
        "crn": "",
        "course_name": "",
        "term": "",
        "term_code": "",
        "credits": 4,
        "meeting_days": "",
        "meeting_time": "",
        "location": "",
        "instructor_name": "",
        "enrolled": 0,
        "students": [],
    }

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()

    # Extract term/date from the header line before any table
    term_match = re.search(r"(Spring|Fall|Winter|Summer)\s+(20\d{2})", html)
    if term_match:
        season = term_match.group(1)
        year = term_match.group(2)[2:]  # "2026" -> "26"
        season_code = {"Spring": "S", "Fall": "F", "Winter": "W", "Summer": "U"}[season]
        result["term_code"] = f"{year}{season_code}"
        result["term"] = f"{season} 20{year}"

    parser = _TableParser()
    parser.feed(html)

    for table in parser.tables:
        if not table:
            continue
        first_row = [c.strip() for c in table[0]] if table[0] else []

        # Course info table: first row has headers CRN, Course, Credits, ...
        if first_row and first_row[0].upper() == "CRN":
            if len(table) > 1:
                data = [c.strip() for c in table[1]]
                if data:
                    result["crn"] = data[0]
                    result["course_name"] = data[1] if len(data) > 1 else ""
                    if len(data) > 2:
                        m = re.match(r"0?(\d+)", data[2])
                        if m:
                            result["credits"] = int(m.group(1))
                    if len(data) > 3:
                        try:
                            result["enrolled"] = int(data[3])
                        except ValueError:
                            pass
            continue

        # Instructor/meeting table: first row has Instructor, Days, Time, Location
        if first_row and first_row[0].upper() == "INSTRUCTOR":
            days_seen = []
            for row in table[1:]:
                cells = [c.strip() for c in row]
                if not cells:
                    continue
                # When instructor cell has rowspan=2, second meeting row starts with the day code
                # Row with instructor: [name, day, time, location]
                # Row without (rowspan): [day, time, location]
                if len(cells) >= 4:
                    # Full row — instructor name in cells[0], day in cells[1]
                    if not result["instructor_name"] and cells[0]:
                        result["instructor_name"] = cells[0]
                    day = cells[1]
                    time_val = cells[2]
                elif len(cells) >= 2:
                    # Short row — day in cells[0] (rowspan means instructor col is missing)
                    day = cells[0]
                    time_val = cells[1]
                else:
                    continue

                if re.match(r"^[MTWRFSU]{1,3}$", day) and day not in days_seen:
                    days_seen.append(day)
                    if not result["meeting_time"] and time_val:
                        result["meeting_time"] = time_val
            result["meeting_days"] = ",".join(days_seen)
            continue

        # Student table: first row header is "Student name"
        if first_row and first_row[0].lower() == "student name":
            for row in table[1:]:
                if not row:
                    continue
                name_cell = row[0].strip()
                if _looks_like_student_name(name_cell):
                    student = _parse_name(name_cell)
                    if student:
                        result["students"].append(student)
            continue

    return result
