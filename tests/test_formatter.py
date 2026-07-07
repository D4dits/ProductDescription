import pytest
from app.pipeline import _build_source_excerpt, _format_source_for_codex_prompt, _normalize_preorder_prefix
from app.generator import (
    SEO_TITLE_MAX_LENGTH,
    apply_legacy_inline_styles,
    apply_seo_brand_suffix,
    format_source_context_for_generation,
    normalize_description_html,
    normalize_product_metadata,
)

def test_legacy_inline_styles():
    html_input = (
        "<h2>Krótko o grze</h2>"
        "<p>Wspaniała gra karciana.</p>"
        "<ul>"
        "<li>Element 1</li>"
        "</ul>"
    )
    
    styled_html = apply_legacy_inline_styles(html_input)
    
    # Check that wrapping class .def exists
    assert 'class="def"' in styled_html
    assert 'itemprop="description"' in styled_html
    
    # Check that inline styles were injected
    assert "font-family: arial, helvetica, sans-serif;" in styled_html
    assert "font-size: medium;" in styled_html
    assert "color: #444444;" in styled_html
    assert "border-bottom: 1px solid #cccccc;" in styled_html
    assert "<h3" in styled_html
    assert "<h2" not in styled_html
    assert "<ul><li>Element 1</li></ul>" in styled_html
    assert '<ul class=' not in styled_html
    assert '<li class=' not in styled_html

def test_legacy_inline_styles_normalizes_existing_wrapper():
    html_input = (
        '<div itemprop="description" class="def">'
        '<h2 style="color:red">Nagłówek</h2>'
        '<p style="color:red">Tekst</p>'
        "</div>"
    )

    styled_html = apply_legacy_inline_styles(html_input)

    assert styled_html.count('itemprop="description"') == 1
    assert 'color:red' not in styled_html
    assert '<h3 class="def" style="' in styled_html

def test_legacy_inline_styles_removes_whitespace_from_href():
    html_input = "<p><a href='https://example.com/foo\n  bar' target='_blank'>Link</a></p>"

    styled_html = apply_legacy_inline_styles(html_input)

    assert 'href="https://example.com/foobar"' in styled_html

def test_legacy_inline_styles_empty():
    assert apply_legacy_inline_styles("") == ""
    assert apply_legacy_inline_styles(None) == ""

def test_apply_seo_brand_suffix_appends_brand():
    assert (
        apply_seo_brand_suffix("Jungle Speed Eco - gra imprezowa")
        == "Jungle Speed Eco - gra imprezowa | Graszki.pl"
    )

def test_apply_seo_brand_suffix_does_not_duplicate_brand():
    assert (
        apply_seo_brand_suffix("Jungle Speed Eco - gra imprezowa | Graszki.pl")
        == "Jungle Speed Eco - gra imprezowa | Graszki.pl"
    )

def test_apply_seo_brand_suffix_shortens_long_title():
    title = apply_seo_brand_suffix(
        "Bardzo dlugi tytul gry planszowej strategicznej dla calej rodziny"
    )

    assert title.endswith(" | Graszki.pl")
    assert len(title) <= SEO_TITLE_MAX_LENGTH

def test_normalize_product_metadata_single_line_fields():
    data = {
        "short_description": "Pierwsza linia\nDruga linia",
        "meta_description": "Opis z\t tabulatorem\n i nowa linia",
        "seo_title": "<h2>Gra imprezowa</h2>",
        "product_name": "<h2>Nazwa gry</h2>",
        "original_title": "<strong>Original</strong>",
        "release_date_note": "<h2>Premiera orientacyjna: jesień 2026</h2>",
        "tags": ["<h2>tag</h2>"],
        "box_contents": ["<strong>1 karta</strong>"],
        "additional_info": {"publisher": "<h2>Portal Games</h2>"},
    }

    normalize_product_metadata(data)

    assert data["short_description"] == "Pierwsza linia Druga linia"
    assert data["meta_description"] == "Opis z tabulatorem i nowa linia"
    assert data["seo_title"] == "Gra imprezowa | Graszki.pl"
    assert data["product_name"] == "Nazwa gry"
    assert data["original_title"] == "Original"
    assert data["release_date_note"] == "Premiera orientacyjna: jesień 2026"
    assert data["tags"] == ["tag"]
    assert data["box_contents"] == ["1 karta"]
    assert data["additional_info"]["publisher"] == "Portal Games"

def test_normalize_description_html_hides_empty_box_contents_and_bolds_specs():
    html_input = (
        "<h2>Krótko o grze</h2><p>Opis.</p>"
        "<h2>Zawartość pudełka:</h2><ul><li>brak danych</li></ul>"
        "<h2>Dodatkowe informacje:</h2>"
        "<ul><li>Autor: Jan Kowalski</li><li>Przedsprzedaż: tak</li></ul>"
    )

    normalized = normalize_description_html(
        html_input,
        box_contents=[],
        is_preorder=True,
        release_date_note="jesień 2026",
    )

    assert "Zawartość pudełka" not in normalized
    assert "<strong>Autor:</strong> Jan Kowalski" in normalized
    assert "Przedsprzedaż" not in normalized
    assert "<strong>Orientacyjna premiera:</strong> jesień 2026" in normalized

def test_normalize_description_html_repairs_merged_additional_info_items():
    html_input = (
        "<h2>Dodatkowe informacje:</h2>"
        "<ul>"
        "<li><strong>Autor:</strong> Joe Klipfel</li>"
        "<li><strong>Wydawca:</strong> Portal Games Ilustracje: Federico Pompili Wydanie: polskie "
        "Instrukcja: polska Orientacyjna premiera: Premiera orientacyjna: jesień 2026 "
        "Wymagana gra podstawowa: Dragons of Etchinstone Uwaga: kart z rozszerzenia Oblężenie nie można dodawać.</li>"
        "</ul>"
    )

    normalized = normalize_description_html(
        html_input,
        box_contents=[],
        is_preorder=True,
        release_date_note="Premiera orientacyjna: jesień 2026",
    )

    assert normalized.count("<li>") == 8
    assert "<li><strong>Wydawca:</strong> Portal Games</li>" in normalized
    assert "<li><strong>Ilustracje:</strong> Federico Pompili</li>" in normalized
    assert "<li><strong>Wydanie:</strong> polskie</li>" in normalized
    assert "<li><strong>Instrukcja:</strong> polska</li>" in normalized
    assert "<li><strong>Orientacyjna premiera:</strong> jesień 2026</li>" in normalized
    assert "Premiera orientacyjna: jesień 2026</li>" not in normalized

def test_format_source_context_prioritizes_manual_pdf():
    context = format_source_context_for_generation(
        [
            {"source_type": "official", "title": "Strona", "body": "Opis strony"},
            {"source_type": "manual_pdf", "title": "Instrukcja", "body": "Zasady z instrukcji"},
        ]
    )

    assert context.index("manual_pdf") < context.index("official")
    assert "Zasady z instrukcji" in context

def test_codex_prompt_manual_summary_uses_short_fact_blocks():
    body = (
        "Wersja 1.0\n"
        "komponenty\n16 kart Maga Eteru, 2 karty Regionu, 2 karty Smoka\n"
        "Główne założenia\nNorthvale to rozszerzenie do gry Dragons of Etchinstone.\n"
        "Przygotowanie rozgrywki\nPrzygotuj karty Regionu.\n"
        "Specjalne Zdolności\nMagowie Eteru mają specjalne zdolności.\n"
        "Twórcy\nProjekt gry: Jan Kowalski\n"
        + ("Dalsza treść instrukcji. " * 300)
    )

    excerpt, truncated = _build_source_excerpt({"source_type": "manual_pdf", "body": body})

    assert "Komponenty:" in excerpt
    assert "Opis/założenia:" in excerpt
    assert "16 kart Maga Eteru" in excerpt
    assert truncated is True
    assert "####" not in excerpt

def test_codex_prompt_manual_source_uses_local_pdf_path_instead_of_full_text():
    source = {
        "url": "https://drive.google.com/file/d/example/view",
        "title": "Instrukcja.pdf",
        "source_type": "manual_pdf",
        "local_pdf_path": "/tmp/instrukcja.pdf",
        "body": "komponenty\n16 kart\nNorthvale to rozszerzenie.\n" + ("Dalsza treść. " * 400),
    }

    formatted = _format_source_for_codex_prompt(1, source)

    assert "Lokalny plik PDF: /tmp/instrukcja.pdf" in formatted
    assert "nie wklejam pełnej instrukcji" in formatted
    assert "Wyciąg pomocniczy" in formatted
    assert "krótka lista faktów" in formatted
    assert len(formatted) < 5000

def test_normalize_preorder_prefix_handles_common_typos():
    assert (
        _normalize_preorder_prefix("Pzedsprzedaż Dragons of Etchinstone")
        == "Przedsprzedaż Dragons of Etchinstone"
    )
    assert (
        _normalize_preorder_prefix("Przedpsrzedaż Cerber")
        == "Przedsprzedaż Cerber"
    )
