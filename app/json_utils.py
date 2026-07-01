import json


def _strip_markdown_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start:end + 1]


def _escape_inner_quotes(text: str) -> str:
    repaired = []
    in_string = False
    escaped = False

    for idx, char in enumerate(text):
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            repaired.append(char)
            escaped = False
            continue

        if char == "\\":
            repaired.append(char)
            escaped = True
            continue

        if char == '"':
            next_idx = idx + 1
            while next_idx < len(text) and text[next_idx].isspace():
                next_idx += 1

            next_char = text[next_idx] if next_idx < len(text) else ""
            if next_char in {":", ",", "}", "]"}:
                repaired.append(char)
                in_string = False
            else:
                repaired.append('\\"')
            continue

        repaired.append(char)

    return "".join(repaired)


def _escape_control_chars_in_strings(text: str) -> str:
    repaired = []
    in_string = False
    escaped = False

    for char in text:
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            repaired.append(char)
            escaped = False
            continue

        if char == "\\":
            repaired.append(char)
            escaped = True
            continue

        if char == '"':
            repaired.append(char)
            in_string = False
            continue

        if char == "\n":
            repaired.append("\\n")
        elif char == "\r":
            repaired.append("\\r")
        elif char == "\t":
            repaired.append("\\t")
        elif ord(char) < 32:
            repaired.append(f"\\u{ord(char):04x}")
        else:
            repaired.append(char)

    return "".join(repaired)


def parse_llm_json(text: str) -> dict:
    """
    Parse JSON returned by LLMs.
    Some OpenAI-compatible providers occasionally return JSON with raw quotes
    inside long HTML strings. The second pass repairs only that common case.
    """
    cleaned = _extract_json_object(_strip_markdown_fence(text))

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = _escape_control_chars_in_strings(_escape_inner_quotes(cleaned))
        return json.loads(repaired)
