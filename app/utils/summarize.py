"""
Generate a short AI summary of student reflections for a session.

Calls claude-opus-4-6 with the collected reflection texts and asks for a
100-word aggregate summary suitable for instructor review.

Returns None (silently) if ANTHROPIC_API_KEY is not set, so the feature
degrades gracefully when the key is absent.
"""

import os
from typing import List, Optional

import anthropic


def summarize_reflections(reflections: List[str], prompt: str) -> Optional[str]:
    """
    Given a list of student reflection strings and the session prompt,
    return a ≤100-word aggregate summary, or None on failure.

    Args:
        reflections: List of raw reflection text strings from students.
        prompt:      The reflection prompt shown to students.

    Returns:
        A short summary string, or None if the API key is missing / call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    if not reflections:
        return None

    numbered = "\n".join(
        f"{i+1}. {text.strip()}" for i, text in enumerate(reflections) if text.strip()
    )

    user_message = (
        f"The following are student reflections submitted in response to this prompt:\n"
        f'"{prompt}"\n\n'
        f"Reflections:\n{numbered}\n\n"
        f"Write a single aggregate summary (strictly 100 words or fewer) that captures "
        f"the key themes, insights, and ideas students expressed. Write in third person "
        f"(e.g., 'Students noted…'). Be concise and specific — this is for the instructor "
        f"to quickly gauge class comprehension."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": user_message}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
    except Exception:
        pass

    return None
