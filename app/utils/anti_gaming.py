"""
Anti-gaming utilities for the attendance system.

Flags (never silently rejects) suspicious submissions so instructors can review.
Flag reasons:
  - "late_submission"     : submitted after the session window closed
  - "short_reflection"    : fewer than 25 words
  - "repetitive_text"     : text is a near-copy of the prompt or highly repetitive
  - "duplicate_ip"        : same IP hash submitted twice in this session
  - "identical_to_peer"   : reflection is suspiciously similar to another student's in same session
"""

import hashlib
import re
from difflib import SequenceMatcher


MIN_WORD_COUNT = 25
SIMILARITY_THRESHOLD = 0.85  # 85% similarity triggers a peer-match flag


def hash_ip(ip_address):
    """One-way SHA256 hash of an IP address. Not reversible."""
    return hashlib.sha256(ip_address.encode("utf-8")).hexdigest()


def get_flag_reasons(reflection_text, submitted_at, session, existing_records, ip_hash, prompt_text=""):
    """
    Evaluate a submission and return a list of flag reasons.

    Args:
        reflection_text: The student's submitted reflection
        submitted_at: datetime of submission
        session: the Session model object
        existing_records: list of existing Attendance records for this session
        ip_hash: hashed IP address of submitter
        prompt_text: the reflection prompt shown to students

    Returns:
        list of flag reason strings (empty list = no flags)
    """
    flags = []

    if reflection_text:
        text = reflection_text.strip()

        # Check: late submission (after window closed)
        if submitted_at and session.close_at:
            from datetime import timezone
            submitted_aware = submitted_at.replace(tzinfo=timezone.utc) if submitted_at.tzinfo is None else submitted_at
            close_aware = session.close_at.replace(tzinfo=timezone.utc) if session.close_at.tzinfo is None else session.close_at
            if submitted_aware > close_aware:
                flags.append("late_submission")

        # Check: word count
        words = text.split()
        if len(words) < MIN_WORD_COUNT:
            flags.append("short_reflection")

        # Check: text is repetitive or echoes the prompt
        if _is_repetitive(text):
            flags.append("repetitive_text")

        if prompt_text and _too_similar(text, prompt_text):
            flags.append("repetitive_text")

        # Check: identical or near-identical to a peer's reflection in the same session
        peer_reflections = [
            r.reflection_text for r in existing_records
            if r.reflection_text and r.status == "present"
        ]
        for peer_text in peer_reflections:
            if _too_similar(text, peer_text):
                flags.append("identical_to_peer")
                break

    # Check: same IP hash already used in this session
    ip_matches = [r for r in existing_records if r.ip_hash == ip_hash and ip_hash]
    if ip_matches:
        flags.append("duplicate_ip")

    return list(set(flags))  # deduplicate


def _is_repetitive(text):
    """Detect highly repetitive text (e.g., copy-pasted filler)."""
    words = text.lower().split()
    if len(words) < 5:
        return True

    # Count unique words — if fewer than 40% are unique, it's repetitive
    unique_ratio = len(set(words)) / len(words)
    if unique_ratio < 0.40:
        return True

    # Check for repeated phrases (3+ word sequences appearing 3+ times)
    trigrams = [" ".join(words[i:i+3]) for i in range(len(words) - 2)]
    for trigram in trigrams:
        if trigrams.count(trigram) >= 3:
            return True

    return False


def _too_similar(text_a, text_b):
    """Return True if two texts are suspiciously similar (>= SIMILARITY_THRESHOLD)."""
    a = re.sub(r"\s+", " ", text_a.lower().strip())
    b = re.sub(r"\s+", " ", text_b.lower().strip())
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio >= SIMILARITY_THRESHOLD


def flag_label(reason):
    """Human-readable label for a flag reason."""
    labels = {
        "late_submission": "Submitted after window closed",
        "short_reflection": f"Reflection under {MIN_WORD_COUNT} words",
        "repetitive_text": "Repetitive or low-effort text",
        "duplicate_ip": "Same device used for multiple submissions",
        "identical_to_peer": "Nearly identical to another student's reflection",
    }
    return labels.get(reason, reason)
