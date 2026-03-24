"""
console_style.py — Console log coloring for Media Organizer, AV1 Encoder, AI Scanner.
Token-level coloring: basename bright white; folder segments and path slashes distinct.
"""

import html
import re

# Dracula-inspired professional palette
FILENAME = "#f8f8f2"      # Bright white — file basename only (last path segment)
PATH_FOLDER = "#94e2d5"   # Teal — directory components inside quoted paths
PATH_SEP = "#ff79c6"      # Bright pink — / and \\ between segments
QUOTE = "#6272a4"        # Muted — quote chars
ARROW = "#8be9fd"        # Cyan — ->
DRY_RUN = "#ffb86c"      # Amber — [DRY RUN]
ACTION = "#50fa7b"       # Green — [MOVE], [COPY], [LINK]
SKIP_TAG = "#bd93f9"     # Purple — [SKIP], [DUPLICATE]
RENAME_FIX = "#ff79c6"   # Pink — [RENAME FIX]
ERROR = "#ff5555"        # Red — ERROR
WARNING = "#f1fa8c"      # Yellow — WARNING
SUCCESS = "#50fa7b"      # Green — Done, complete
INFO = "#8be9fd"         # Cyan — Scanning, starting
BASE = "#e5e7eb"         # Default text


def _span(txt: str, color: str) -> str:
    return f'<span style="color:{color}">{html.escape(txt)}</span>'


def _quoted_path_content_to_html(inner: str) -> str:
    """
    Color quoted path strings: slashes, folder names, and final filename/extension distinct.
    Single-segment strings (no separators) stay all FILENAME.
    """
    if not re.search(r"[/\\]", inner):
        return _span(inner, FILENAME)
    tokens = re.split(r"([/\\])", inner)
    last_text_i = None
    for idx in range(len(tokens) - 1, -1, -1):
        t = tokens[idx]
        if t not in ("/", "\\") and t != "":
            last_text_i = idx
            break
    if last_text_i is None:
        return _span(inner, FILENAME)
    out: list[str] = []
    for i, t in enumerate(tokens):
        if t in ("/", "\\"):
            out.append(_span(t, PATH_SEP))
        elif t == "":
            continue
        else:
            color = FILENAME if i == last_text_i else PATH_FOLDER
            out.append(_span(t, color))
    return "".join(out)


def message_to_html(msg: str) -> str:
    """
    Convert a log message to HTML with token-level coloring.
    Quoted paths: basename bright white, folder segments teal, slashes gray; [DRY RUN], [MOVE], ->, quotes distinct.
    """
    if not msg or not isinstance(msg, str):
        return _span("", BASE)

    # Determine line-level semantic color for non-structured parts
    u = msg.upper()
    if u.startswith("ERROR:") or u.startswith("FAILED:") or "ERROR:" in u[:25]:
        line_color = ERROR
    elif u.startswith("WARNING:") or "WARNING:" in u[:25]:
        line_color = WARNING
    elif u.startswith("REJECTED:") or "DELETE ERROR" in u or "EXPORT FAILED" in u:
        line_color = ERROR
    elif (
        "COMPLETE" in u
        or "BATCH ORGANIZATION COMPLETE" in u
        or "BATCH SCAN COMPLETE" in u
        or "DONE:" in u
        or "MODEL SETUP COMPLETE" in u
        or "OPENCV INSTALLED" in u
    ):
        line_color = SUCCESS
    elif u.startswith("[SKIP]") or u.startswith("[DUPLICATE]") or u.startswith("SKIP ("):
        line_color = SKIP_TAG
    elif "SCANNING" in u[:15] or "STARTING" in u[:15] or "FOUND " in u[:10] or "SCANNED:" in u[:15]:
        line_color = INFO
    else:
        line_color = BASE

    # Tokenize: [TAG], "filename", ->, and rest
    parts = []
    i = 0
    while i < len(msg):
        # [DRY RUN], [MOVE], [COPY], [LINK], [SKIP], [DUPLICATE], [RENAME FIX]
        tag_m = re.match(r"\[(DRY RUN|MOVE|COPY|LINK|SKIP|DUPLICATE|RENAME FIX)\]", msg[i:], re.I)
        if tag_m:
            tag = tag_m.group(0)
            tag_upper = tag.upper()
            if "DRY RUN" in tag_upper:
                color = DRY_RUN
            elif tag_upper in ("[MOVE]", "[COPY]", "[LINK]"):
                color = ACTION
            elif tag_upper in ("[SKIP]", "[DUPLICATE]"):
                color = SKIP_TAG
            else:
                color = RENAME_FIX
            parts.append(_span(tag, color))
            i += len(tag)
            continue

        # Quoted string: "..." — quotes muted; path inside split into folders / sep / basename
        if msg[i] == '"':
            j = i + 1
            while j < len(msg) and msg[j] != '"':
                if msg[j] == "\\":
                    j += 1
                j += 1
            if j < len(msg):
                parts.append(_span('"', QUOTE))
                parts.append(_quoted_path_content_to_html(msg[i + 1 : j]))
                parts.append(_span('"', QUOTE))
                i = j + 1
                continue

        # Arrow ->
        if msg[i : i + 2] == "->":
            parts.append(_span("->", ARROW))
            i += 2
            continue

        # Default: gather until next special
        j = i
        while j < len(msg):
            peek = msg[j : j + 2]
            if msg[j] == '"' or peek == "->":
                break
            tag_m = re.match(r"\[(DRY RUN|MOVE|COPY|LINK|SKIP|DUPLICATE|RENAME FIX)\]", msg[j:], re.I)
            if tag_m:
                break
            j += 1
        chunk = msg[i:j]
        if chunk:
            parts.append(_span(chunk, line_color))
        i = j

    return "".join(parts) if parts else _span(msg, line_color)
