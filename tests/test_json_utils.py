from app.json_utils import parse_llm_json


def test_parse_llm_json_repairs_inner_quotes_in_html_string():
    raw = (
        '{"short_description": "Opis", '
        '"tags": ["Voidfall"], '
        '"extended_description_html": "<p>System "kostek Siły Floty" działa poprawnie.</p>"}'
    )

    parsed = parse_llm_json(raw)

    assert parsed["short_description"] == "Opis"
    assert parsed["tags"] == ["Voidfall"]
    assert 'System "kostek Siły Floty" działa' in parsed["extended_description_html"]


def test_parse_llm_json_strips_markdown_fence():
    raw = """```json
{"short_description": "Opis", "tags": []}
```"""

    parsed = parse_llm_json(raw)

    assert parsed == {"short_description": "Opis", "tags": []}


def test_parse_llm_json_repairs_control_chars_inside_string():
    raw = '{"short_description": "Pierwsza linia\nDruga linia", "tags": []}'

    parsed = parse_llm_json(raw)

    assert parsed["short_description"] == "Pierwsza linia\nDruga linia"
