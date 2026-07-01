import pytest
from app.generator import (
    SEO_TITLE_MAX_LENGTH,
    apply_legacy_inline_styles,
    apply_seo_brand_suffix,
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
        "seo_title": "Gra imprezowa",
    }

    normalize_product_metadata(data)

    assert data["short_description"] == "Pierwsza linia Druga linia"
    assert data["meta_description"] == "Opis z tabulatorem i nowa linia"
    assert data["seo_title"] == "Gra imprezowa | Graszki.pl"
