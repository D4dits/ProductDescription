import pytest
from pathlib import Path
from bs4 import BeautifulSoup
import app.generator as generator
from app.pipeline import _build_source_excerpt, _format_source_for_codex_prompt, _normalize_preorder_prefix
from app.generator import (
    SEO_TITLE_MAX_LENGTH,
    apply_legacy_inline_styles,
    apply_seo_brand_suffix,
    format_source_context_for_generation,
    normalize_description_html,
    normalize_product_metadata,
)

@pytest.fixture(autouse=True)
def producer_url_cache(monkeypatch):
    monkeypatch.setattr(generator, "_producer_url_cache", {
        "meeplemood": "https://graszki.pl/meeplemood",
        "portal": "https://graszki.pl/portal",
        "rebel": "https://graszki.pl/rebel",
    })

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
    assert '<li><strong>Wydawca:</strong> <a href="https://graszki.pl/portal">Portal Games</a></li>' in normalized
    assert "<li><strong>Ilustracje:</strong> Federico Pompili</li>" in normalized
    assert "<li><strong>Wydanie:</strong> polskie</li>" in normalized
    assert "<li><strong>Instrukcja:</strong> polska</li>" in normalized
    assert "<li><strong>Orientacyjna premiera:</strong> jesień 2026</li>" in normalized
    assert "Premiera orientacyjna: jesień 2026</li>" not in normalized

def test_normalize_description_html_removes_unknown_additional_info_rows():
    html_input = (
        "<h2>Dodatkowe informacje:</h2>"
        "<ul>"
        "<li><strong>Wydawca:</strong> MeepleMood</li>"
        "<li><strong>Liczba graczy:</strong> brak potwierdzonych danych</li>"
        "<li><strong>Zalecany wiek:</strong> brak potweirdzonych danych</li>"
        "<li><strong>Czas gry:</strong> brak danych</li>"
        "</ul>"
    )

    normalized = normalize_description_html(html_input)

    assert '<strong>Wydawca:</strong> <a href="https://graszki.pl/meeplemood">MeepleMood</a>' in normalized
    assert "Liczba graczy" not in normalized
    assert "Zalecany wiek" not in normalized
    assert "Czas gry" not in normalized
    assert "brak potwierdzonych danych" not in normalized
    assert "brak potweirdzonych danych" not in normalized


def test_producer_link_keeps_games_in_matching_key(monkeypatch):
    monkeypatch.setattr(generator, "_producer_url_cache", {"ogrygames": "https://graszki.pl/ogrygames"})

    normalized = normalize_description_html(
        "<h2>Dodatkowe informacje:</h2><ul><li><strong>Wydawca:</strong> Ogry Games</li></ul>"
    )

    assert '<a href="https://graszki.pl/ogrygames">Ogry Games</a>' in normalized


def test_unknown_producer_remains_plain_text(monkeypatch):
    monkeypatch.setattr(generator, "_producer_url_cache", {"rebel": "https://graszki.pl/rebel"})

    normalized = normalize_description_html(
        "<h2>Dodatkowe informacje:</h2><ul><li><strong>Wydawca:</strong> Nieobecny Wydawca</li></ul>"
    )

    assert "Nieobecny Wydawca" in normalized
    assert "<a " not in normalized


def test_accessory_product_data_links_producer(monkeypatch):
    monkeypatch.setattr(generator, "_producer_url_cache", {"gamegenic": "https://graszki.pl/Gamegenic/pr/603"})

    normalized = normalize_description_html(
        "<h2>Dane produktu</h2><ul><li><strong>Producent:</strong> Gamegenic</li>"
        "<li>Kod produktu: GGS10020ML</li><li>EAN: 4251715402238</li></ul>"
    )

    assert '<a href="https://graszki.pl/Gamegenic/pr/603">Gamegenic</a>' in normalized
    assert "<strong>Kod produktu:</strong> GGS10020ML" in normalized
    assert "<strong>EAN:</strong> 4251715402238" in normalized


def test_accessory_product_data_links_existing_category(monkeypatch):
    monkeypatch.setattr(
        generator,
        "_category_url_cache",
        {"koszulki-na-karty": "https://graszki.pl/Koszulki-na-karty-c186"},
    )

    normalized = normalize_description_html(
        "<h2>Dane produktu</h2><ul><li>Kategoria: Koszulki na karty</li></ul>"
    )

    assert '<strong>Kategoria:</strong> <a href="https://graszki.pl/Koszulki-na-karty-c186">Koszulki na karty</a>' in normalized


def test_missing_category_is_added_from_store_path(monkeypatch):
    monkeypatch.setattr(generator, "_category_url_cache", {"rodzinne": "https://graszki.pl/Rodzinne-c5"})

    normalized = normalize_description_html(
        "<h2>Dodatkowe informacje:</h2><ul><li>Wydanie: polskie</li></ul>",
        category="Gry planszowe/Rodzinne",
    )

    assert '<strong>Kategoria:</strong> <a href="https://graszki.pl/Rodzinne-c5">Rodzinne</a>' in normalized


def test_generated_category_can_replace_import_default(monkeypatch):
    monkeypatch.setattr(generator, "_category_url_cache", {"logiczne": "https://graszki.pl/Logiczne-c3"})

    normalized = normalize_description_html(
        "<h2>Dodatkowe informacje:</h2><ul><li>Kategoria: Rodzinne</li></ul>",
        category="Logiczne",
        replace_category=True,
    )

    assert '<strong>Kategoria:</strong> <a href="https://graszki.pl/Logiczne-c3">Logiczne</a>' in normalized
    assert "Rodzinne" not in normalized


def test_unknown_category_remains_plain_text(monkeypatch):
    monkeypatch.setattr(generator, "_category_url_cache", {"rodzinne": "https://graszki.pl/Rodzinne-c5"})

    normalized = normalize_description_html(
        "<h2>Dane produktu</h2><ul><li>Kategoria: Nieistniejąca kategoria</li></ul>"
    )

    assert "<strong>Kategoria:</strong> Nieistniejąca kategoria" in normalized
    assert "<a " not in normalized


def test_box_contents_are_moved_before_product_data():
    normalized = normalize_description_html(
        "<h2>Dane produktu</h2><ul><li>EAN: 123</li></ul>"
        "<h2>Zawartość pudełka:</h2><ul><li>100 koszulek</li></ul>",
        box_contents=["100 koszulek"],
    )

    assert normalized.index("Zawartość pudełka") < normalized.index("Dane produktu")
    soup = BeautifulSoup(normalized, "html.parser")
    box_heading = next(heading for heading in soup.find_all("h2") if "Zawartość" in heading.get_text())
    assert box_heading.find_next_sibling("ul").get_text(" ", strip=True) == "100 koszulek"


def test_sitemap_loader_uses_user_agent_and_writes_cache(tmp_path, monkeypatch):
    xml = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://graszki.pl/ogrygames</loc></url>
    </urlset>'''
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return xml

    def fake_urlopen(request, timeout):
        seen["user_agent"] = request.get_header("User-agent")
        return Response()

    cache_path = Path(tmp_path) / "producer-sitemap.xml"
    monkeypatch.setattr(generator, "_producer_url_cache", None)
    monkeypatch.setattr(generator, "PRODUCER_SITEMAP_CACHE", cache_path)
    monkeypatch.setattr(generator.urllib.request, "urlopen", fake_urlopen)

    result = generator._load_producer_url_map()

    assert result["ogrygames"] == "https://graszki.pl/ogrygames"
    assert "GraszkiContentBot" in seen["user_agent"]
    assert cache_path.read_bytes() == xml

def test_normalize_description_html_links_publisher_and_renames_generic_manual_link():
    html_input = (
        "<h2>Dodatkowe informacje:</h2>"
        "<ul>"
        "<li>Wydawca: Rebel</li>"
        "<li><strong>Instrukcja PDF:</strong> "
        "<a href='https://example.com/download?id=123'>link</a></li>"
        "</ul>"
    )

    normalized = normalize_description_html(html_input, game_name="Patyko")

    assert '<strong>Wydawca:</strong> <a href="https://graszki.pl/rebel">Rebel</a>' in normalized
    assert '>patyko-instrukcja.pdf</a>' in normalized
    assert ">link</a>" not in normalized

def test_normalize_description_html_keeps_unknown_publisher_unlinked():
    html_input = (
        "<h2>Dodatkowe informacje:</h2>"
        "<ul><li>Wydawca: Nieznany Wydawca</li></ul>"
    )

    normalized = normalize_description_html(html_input)

    assert "<strong>Wydawca:</strong> Nieznany Wydawca" in normalized
    assert "<a " not in normalized

def test_publisher_li_keeps_unknown_publisher_unlinked():
    assert generator._publisher_li("Nieznany Wydawca") == (
        "<li><strong>Wydawca:</strong> Nieznany Wydawca</li>"
    )

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
