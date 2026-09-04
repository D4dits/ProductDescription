import base64
import csv
import io
import json
from xml.etree import ElementTree as ET

import pytest
from bs4 import BeautifulSoup

from app import batch
from app.llm import LLMAuthenticationError, LLMError


SKY_HEADER = [
    "Nazwa produktu", "ID", "EAN", "Kategoria", "Producent",
    "Opis rozszerzony", "Opis skrócony", "Tytuł strony", "Opis strony",
    "Tagi (słowa kluczowe)", "Cena brutto", "Ilość", "Ukryty",
]
REBEL_HEADER = [
    "IDProduct", "ProductName", "EAN", "Description", "FullDescription",
    "Category", "Publisher", "MinAge", "MinPlayingTime", "MaxPlayingTime",
    "MinPlayers", "MaxPlayers", "Language", "ReleaseDate", "ProductCode", "ImageURL",
]


def csv_bytes(header, rows, delimiter, encoding):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode(encoding)


def sky_row(name="Zażółć", product_id="101", ean="5901", category="Gry planszowe/Rodzinne"):
    return [name, product_id, ean, category, "Rebel", "<p>Stary\nopis</p>", "Stary", "", "", "", "99.99", "8", "1"]


def rebel_row(name="Zażółć", ean="5901", category="REBEL - Gry planszowe familijne"):
    return ["9001", name, ean, "Krótki opis", "Pełny opis produktu", category, "Rebel", "8", "30", "45", "2", "4", "pl", "", "SKU", "https://example.test/image.jpg"]


def test_parsers_keep_polish_text_and_multiline_html():
    sky = batch.parse_sky_csv(csv_bytes(SKY_HEADER, [sky_row()], ";", "utf-8-sig"))
    rebel = batch.parse_rebel_csv(csv_bytes(REBEL_HEADER, [rebel_row()], ",", "iso-8859-2"))

    assert sky[0]["Nazwa produktu"] == "Zażółć"
    assert "\n" in sky[0]["Opis rozszerzony"]
    assert rebel[0]["ProductName"] == "Zażółć"


def test_matching_prefers_ean_and_uses_exact_name_only_without_ean():
    sky = batch.parse_sky_csv(
        csv_bytes(SKY_HEADER, [sky_row(), sky_row("Koszulki Pokémon", "102", "", "Pozostałe/Akcesoria/Koszulki na karty")], ";", "utf-8")
    )
    rebel = batch.parse_rebel_csv(
        csv_bytes(REBEL_HEADER, [rebel_row(), rebel_row("Koszulki Pokémon", "", "-- Koszulki na karty")], ",", "iso-8859-2")
    )

    result = batch.match_products(sky, rebel)

    assert [item["match_method"] for item in result] == ["ean", "name"]
    assert result[1]["product_type"] == "accessory"
    assert result[0]["source"]["players"] == "2-4"


def test_matching_rejects_similar_but_not_identical_name():
    sky = batch.parse_sky_csv(csv_bytes(SKY_HEADER, [sky_row("Gra A", ean="")], ";", "utf-8"))
    rebel = batch.parse_rebel_csv(csv_bytes(REBEL_HEADER, [rebel_row("Gra A Deluxe", ean="")], ",", "iso-8859-2"))

    with pytest.raises(batch.BatchError, match="brak dopasowania"):
        batch.match_products(sky, rebel)


def test_batch_import_keeps_unmatched_product_as_error(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    sky = csv_bytes(SKY_HEADER, [sky_row("Gra A", ean="")], ";", "utf-8")
    rebel = csv_bytes(REBEL_HEADER, [rebel_row("Gra A Deluxe", ean="")], ",", "iso-8859-2")

    created = batch.create_batch(sky, rebel, "Błędy")
    product = batch.get_product(created["id"], "101")

    assert created["status"] == "ready_with_errors"
    assert created["errors"] == 1
    assert product["status"] == "failed"
    assert "brak dopasowania" in product["error"]


def test_update_xml_contains_only_id_and_five_content_fields():
    product = {
        "product_id": "5535",
        "content": {
            "extended_description_html": "<p>Opis ]]> produktu</p>",
            "short_description": "Krótki opis",
            "seo_title": "Tytuł | Graszki.pl",
            "meta_description": "Meta opis",
            "tags": ["gra", "rodzinna"],
        },
        "price": "1.00",
        "amount": "999",
        "hidden": "0",
    }

    xml = batch.build_update_xml([product])

    assert "<prod_id>5535</prod_id>" in xml
    assert "<prod_desc>" in xml
    assert "<prod_shortdesc>" in xml
    assert "<prod_seotitle>" in xml
    assert "<prod_seodesc>" in xml
    assert "<prod_keywords>" in xml
    assert "prod_price" not in xml
    assert "prod_amount" not in xml
    assert "hidden" not in xml
    assert "prod_name" not in xml
    assert "]]]]><![CDATA[>" in xml
    item = ET.fromstring(xml).find("item")
    assert item is not None
    assert item.findtext("prod_desc") == "<p>Opis ]]> produktu</p>"
    assert item.findtext("prod_shortdesc") == "Krótki opis"


def test_create_batch_persists_counts_and_current_content(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    sky_raw = csv_bytes(SKY_HEADER, [sky_row(), sky_row("Koszulki", "102", "", "Pozostałe/Akcesoria/Koszulki")], ";", "utf-8")
    rebel_raw = csv_bytes(REBEL_HEADER, [rebel_row(), rebel_row("Koszulki", "", "-- Koszulki na karty")], ",", "iso-8859-2")

    created = batch.create_batch(sky_raw, rebel_raw, "Test")
    products = batch.list_products(created["id"])

    assert created["total"] == 2
    assert created["matched_ean"] == 1
    assert created["matched_name"] == 1
    assert products["total"] == 2
    stored = batch.get_product(created["id"], products["items"][0]["product_id"])
    assert stored["current"]["short_description"] == "Stary"


def test_full_generation_requires_approved_pilot(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    sky_raw = csv_bytes(SKY_HEADER, [sky_row()], ";", "utf-8")
    rebel_raw = csv_bytes(REBEL_HEADER, [rebel_row()], ",", "iso-8859-2")
    created = batch.create_batch(sky_raw, rebel_raw, "Test")

    with pytest.raises(batch.BatchError, match="Najpierw zatwierdź komplet pilota"):
        batch.start_generation(created["id"], "full")


def test_generation_stops_on_auth_error_without_marking_products_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    sky_raw = csv_bytes(
        SKY_HEADER,
        [sky_row("Gra A", "101", "5901"), sky_row("Gra B", "102", "5902")],
        ";",
        "utf-8",
    )
    rebel_raw = csv_bytes(
        REBEL_HEADER,
        [rebel_row("Gra A", "5901"), rebel_row("Gra B", "5902")],
        ",",
        "iso-8859-2",
    )
    created = batch.create_batch(sky_raw, rebel_raw, "Test auth")
    calls = []

    def reject(*args, **kwargs):
        calls.append(args)
        raise LLMAuthenticationError("DeepSeek odrzucił klucz API (401).")

    monkeypatch.setattr(batch, "_generate_game", reject)
    monkeypatch.setattr(batch, "enrich_rebel_source", lambda source, product_type: source)
    monkeypatch.setattr(batch, "BATCH_GENERATION_WORKERS", 1)
    batch._run_generation(created["id"], "pilot")

    result = batch.get_batch(created["id"])
    assert calls and len(calls) == 1
    assert result["status"] == "ready"
    assert "401" in result["message"]
    assert result["counts"] == {"matched": 2}


def test_start_generation_rejects_invalid_llm_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    created = batch.create_batch(
        csv_bytes(SKY_HEADER, [sky_row()], ";", "utf-8"),
        csv_bytes(REBEL_HEADER, [rebel_row()], ",", "iso-8859-2"),
        "Test config",
    )
    monkeypatch.setattr(
        batch,
        "validate_llm_configuration",
        lambda: (_ for _ in ()).throw(LLMError("Brak prawidłowego klucza DEEPSEEK_API_KEY.")),
    )

    with pytest.raises(batch.BatchError, match="DEEPSEEK_API_KEY"):
        batch.start_generation(created["id"], "pilot")


def test_batch_generation_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    sky_rows = [sky_row(f"Gra {index}", str(100 + index), str(5900 + index)) for index in range(1, 4)]
    rebel_rows = [rebel_row(f"Gra {index}", str(5900 + index)) for index in range(1, 4)]
    created = batch.create_batch(
        csv_bytes(SKY_HEADER, sky_rows, ";", "utf-8"),
        csv_bytes(REBEL_HEADER, rebel_rows, ",", "iso-8859-2"),
        "Limit",
    )
    calls = []
    monkeypatch.setattr(batch, "BATCH_GENERATION_WORKERS", 1)
    monkeypatch.setattr(batch, "enrich_rebel_source", lambda source, product_type: source)

    def fail(name, source):
        calls.append(name)
        raise RuntimeError("test")

    monkeypatch.setattr(batch, "_generate_game", fail)
    batch._run_generation(created["id"], "batch", 2)

    assert len(calls) == 2
    assert batch.get_batch(created["id"])["counts"] == {"failed": 2, "matched": 1}


def test_decode_upload_rejects_non_base64():
    assert batch.decode_upload(base64.b64encode(b"abc").decode()) == b"abc"
    with pytest.raises(batch.BatchError):
        batch.decode_upload("not base64")


def test_validation_blocks_incomplete_content():
    errors, _ = batch.validate_batch_content(
        {"short_description": "Tylko jedno pole"},
        "accessory",
        {},
    )
    assert any("extended_description_html" in error for error in errors)


def test_live_content_accepts_skyshop_field_names():
    live = batch._live_content(
        {
            "prod_desclong": "<p>Opis</p>",
            "prod_desc": "Krótki",
            "prod_seotitle": "Tytuł",
            "prod_seodesc": "Meta",
            "prod_keywords": "jeden, dwa",
        }
    )
    assert live["tags"] == ["jeden", "dwa"]
    assert json.loads(json.dumps(live, ensure_ascii=False))["short_description"] == "Krótki"
    assert batch._live_content({"prod_keywords": None})["tags"] == []


def test_rebel_product_page_extracts_box_contents():
    html = b"""
        <dl><dt>Zawarto\xc5\x9b\xc4\x87 pude\xc5\x82ka:</dt><dd><ul>
        <li>1x Gra podstawowa</li><li>2x figurka</li>
        </ul></dd></dl>
    """

    assert batch.parse_rebel_product_page(html)["box_contents"] == ["1x Gra podstawowa", "2x figurka"]


def test_validation_requires_box_section_when_source_has_contents():
    content = {
        "short_description": "Krótki opis produktu",
        "seo_title": "Tytuł produktu | Graszki.pl",
        "meta_description": "Opis produktu przeznaczony do testu walidacji i posiadający odpowiednią długość dla pola opisu strony w sklepie internetowym Graszki.pl.",
        "tags": ["jeden", "dwa", "trzy", "cztery", "pięć"],
        "extended_description_html": "<h2>Krótko o grze</h2><p>Opis.</p>",
    }

    errors, _ = batch.validate_batch_content(content, "accessory", {"box_contents": ["1x plansza"]})

    assert any("Zawartość pudełka" in error for error in errors)


def test_box_contents_are_inserted_before_additional_information():
    content = {
        "extended_description_html": (
            "<h2>Krótko o grze</h2><p>Opis.</p>"
            "<h2>Dodatkowe informacje:</h2><ul><li>Wydawca</li></ul>"
        )
    }

    result = batch.ensure_box_contents(content, "Gra", {"box_contents": ["1x plansza", "2x pionek"]})
    html = result["extended_description_html"]

    assert "Zawartość pudełka" in html
    assert "1x plansza" in html
    assert html.index("Zawartość pudełka") < html.index("Dodatkowe informacje")


def test_box_contents_survive_legacy_wrapper_without_additional_information():
    content = {"extended_description_html": '<div class="def"><h3>Dane produktu</h3></div>'}

    result = batch.ensure_box_contents(content, "Koszulki", {"box_contents": ["100 koszulek"]})

    assert "Zawartość pudełka" in result["extended_description_html"]
    assert "100 koszulek" in result["extended_description_html"]


def test_manual_save_preserves_edited_html_and_box_contents():
    content = {
        "extended_description_html": (
            "<h2>Krótko o produkcie</h2><p>Ręcznie poprawiony opis.</p>"
            "<h2>Zawartość pudełka:</h2><ul><li>Ręcznie poprawiona zawartość</li></ul>"
            "<h2>Dane produktu</h2><ul><li>EAN: 123</li></ul>"
        )
    }

    result = batch.ensure_box_contents(
        content,
        "Koszulki",
        {"box_contents": ["100 koszulek"], "store_category": "Pozostałe/Akcesoria"},
        preserve_existing=True,
    )

    html = result["extended_description_html"]
    assert "Ręcznie poprawiony opis." in html
    assert "Ręcznie poprawiona zawartość" in html
    assert "100 koszulek" not in html
    assert html.index("Zawartość pudełka") < html.index("Dane produktu")


def test_primary_category_uses_product_kind_instead_of_import_default():
    default_source = {"store_category": "Gry planszowe/Rodzinne", "category": "REBEL - Gry planszowe familijne"}

    assert batch.infer_primary_category(
        "Abalone Classic",
        {**default_source, "full_description": "Klasyczna dwuosobowa gra logiczna."},
    ) == "Logiczne"
    assert batch.infer_primary_category(
        "6. bierze",
        {**default_source, "full_description": "Dynamiczna gra karciana dla całej rodziny."},
    ) == "Karciane"
    assert batch.infer_primary_category(
        "100 Pics: Zagadki",
        {**default_source, "full_description": "Poręczna gra quizowa z zagadkami."},
    ) == "Logiczne"
    assert batch.infer_primary_category(
        "Rozszerzenie",
        {**default_source, "full_description": "To dodatek wymagający gry podstawowej."},
    ) == "Dodatki do gier"
    assert batch.infer_primary_category(
        "Nieokreślona gra",
        {**default_source, "full_description": "Opis bez informacji o rodzaju gry."},
    ) == "Gry planszowe/Rodzinne"


def test_corrupted_additional_list_is_rebuilt_from_source():
    content = {
        "extended_description_html": (
            "<h3>Zawartość pudełka:</h3><h3>Dodatkowe informacje:</h3>"
            "<ul><li>1x plansza</li></ul>"
        )
    }
    source = {"box_contents": ["1x plansza"], "publisher": "Wydawca", "language": "pl", "players": "2-4"}

    result = batch.ensure_box_contents(content, "Gra", source)
    soup = BeautifulSoup(result["extended_description_html"], "html.parser")
    headings = soup.find_all(["h2", "h3"])
    box_list = headings[0].find_next_sibling()
    additional_list = headings[1].find_next_sibling()

    assert box_list.get_text(" ", strip=True) == "1x plansza"
    assert "Wydawca: Wydawca" in additional_list.get_text(" ", strip=True)
    assert "Liczba graczy: 2-4" in additional_list.get_text(" ", strip=True)


def test_skyshop_product_details_are_read_one_by_one(monkeypatch):
    client = object.__new__(batch.SkyShopClient)
    calls = []

    def fake_request(function, data):
        calls.append((function, data))
        product_id = data["productID"]
        return {"response_code": 200, "prod_id": product_id, "prod_desc": f"Opis {product_id}"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.get_products(["101", "102"])

    assert list(result) == ["101", "102"]
    assert calls == [
        ("getProductData", {"productID": "101"}),
        ("getProductData", {"productID": "102"}),
    ]


def test_publish_backs_up_writes_and_verifies_five_content_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    created = batch.create_batch(
        csv_bytes(SKY_HEADER, [sky_row()], ";", "utf-8"),
        csv_bytes(REBEL_HEADER, [rebel_row()], ",", "iso-8859-2"),
        "Publikacja",
    )
    content = {
        "extended_description_html": "<h2>Opis</h2><p>Nowa treść.</p>",
        "short_description": "Nowy krótki opis",
        "seo_title": "Nowy tytuł | Graszki.pl",
        "meta_description": "Nowy opis strony przygotowany na potrzeby bezpiecznego testu publikacji produktu w sklepie internetowym wraz z kontrolą danych po wykonanym zapisie.",
        "tags": ["jeden", "dwa", "trzy", "cztery", "pięć"],
    }
    with batch._connect() as conn:
        conn.execute(
            "UPDATE batch_products SET status='approved', approved=1, content_json=? WHERE batch_id=? AND product_id='101'",
            (json.dumps(content, ensure_ascii=False), created["id"]),
        )

    class FakeClient:
        def __init__(self):
            self.written = False

        def get_products(self, product_ids):
            assert product_ids == ["101"]
            values = content if self.written else {
                "extended_description_html": "<p>Stary opis</p>",
                "short_description": "Stary",
                "seo_title": "",
                "meta_description": "",
                "tags": [],
            }
            return {
                "101": {
                    "prod_id": "101", "prod_price": "99.99", "prod_amount": "8", "prod_hidden": "1",
                    "prod_desclong": values["extended_description_html"], "prod_desc": values["short_description"],
                    "prod_seotitle": values["seo_title"], "prod_seodesc": values["meta_description"],
                    "prod_keywords": ", ".join(values["tags"]),
                }
            }

        def update_products(self, xml):
            assert "<prod_desc>" in xml and "<prod_shortdesc>" in xml and "<prod_keywords>" in xml
            assert "<prod_desclong>" not in xml
            assert "prod_price" not in xml and "prod_hidden" not in xml
            self.written = True
            return {"response_code": 200, "stats": {"errors": 0, "total": 1, "updated": 1}}

    client = FakeClient()
    monkeypatch.setattr(batch, "SkyShopClient", lambda: client)

    batch._run_publish(created["id"])

    product = batch.get_product(created["id"], "101")
    assert product["status"] == "verified"
    assert product["backup"]["short_description"] == "Stary"
    assert batch.get_batch(created["id"])["status"] == "completed"


def test_publish_accepts_omitted_product_and_verifies_readback(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    created = batch.create_batch(
        csv_bytes(SKY_HEADER, [sky_row()], ";", "utf-8"),
        csv_bytes(REBEL_HEADER, [rebel_row()], ",", "iso-8859-2"),
        "Ponowiona publikacja",
    )
    content = {
        "extended_description_html": "<h2>Opis</h2><p>Gotowa treść.</p>",
        "short_description": "Gotowy krótki opis",
        "seo_title": "Gotowy tytuł | Graszki.pl",
        "meta_description": "Gotowy opis strony produktu przygotowany do sprawdzenia poprawnego odczytu po pominięciu identycznych danych przez importer Sky-Shop.",
        "tags": ["jeden", "dwa", "trzy", "cztery", "pięć"],
    }
    with batch._connect() as conn:
        conn.execute(
            "UPDATE batch_products SET status='failed', approved=1, content_json=? WHERE batch_id=? AND product_id='101'",
            (json.dumps(content, ensure_ascii=False), created["id"]),
        )

    class OmittedClient:
        def get_products(self, product_ids):
            assert product_ids == ["101"]
            return {
                "101": {
                    "prod_id": "101", "prod_price": "99.99", "prod_amount": "8", "prod_hidden": "1",
                    "prod_desclong": content["extended_description_html"],
                    "prod_desc": content["short_description"],
                    "prod_seotitle": content["seo_title"],
                    "prod_seodesc": content["meta_description"],
                    "prod_keywords": ", ".join(content["tags"]),
                }
            }

        def update_products(self, xml):
            return {
                "response_code": 200,
                "stats": {"total": 1, "updated": 0, "omitted": 1, "inserted": 0, "errors": 0},
            }

    monkeypatch.setattr(batch, "SkyShopClient", OmittedClient)

    batch._run_publish(created["id"])

    assert batch.get_product(created["id"], "101")["status"] == "verified"
    assert batch.get_batch(created["id"])["status"] == "completed"


def test_update_response_accepts_individual_omissions_when_aggregate_is_wrong():
    response = {
        "response_code": 200,
        "stats": {
            "total": 50,
            "updated": 30,
            "omitted": 0,
            "errors": 0,
            "products": [
                {"prod_id": product_id, "status": "omitted"}
                for product_id in range(20)
            ],
        },
    }

    assert batch._update_response_succeeded(response, 50)


def test_update_response_rejects_unaccounted_or_failed_products():
    incomplete = {"response_code": 200, "stats": {"total": 50, "updated": 30, "omitted": 0, "errors": 0}}
    failed = {
        "response_code": 200,
        "stats": {"total": 1, "updated": 0, "omitted": 0, "errors": 0, "products": [{"status": "failed"}]},
    }

    assert not batch._update_response_succeeded(incomplete, 50)
    assert not batch._update_response_succeeded(failed, 1)


def test_invariant_hash_ignores_content_but_detects_commerce_changes():
    before = {"prod_id": 1, "prod_price": "10.00", "prod_amount": 5, "prod_desc": "stary"}
    content_only = {**before, "prod_desc": "nowy", "prod_meta_title": "SEO"}
    changed_price = {**content_only, "prod_price": "11.00"}

    assert batch._invariant_hash(before) == batch._invariant_hash(content_only)
    assert batch._invariant_hash(before) != batch._invariant_hash(changed_price)


def test_readback_comparison_tolerates_skyshop_text_normalization():
    expected = {
        "extended_description_html": '<div class="def">\n<p>Gra&nbsp;rodzinna – szybka.</p><ul><li>Test</li></ul>\n</div>',
        "short_description": "Gra rodzinna – szybka „edycja”.",
        "seo_title": "Gra – rodzinna | Graszki.pl",
        "meta_description": "Opis – dla 2–4 graczy.",
        "tags": ["Gra rodzinna", "Kolej"],
    }
    actual = {
        "extended_description_html": '<div class="def"><p>Gra rodzinna - szybka.</p><ul class="def"><li class="def">Test</li></ul></div>',
        'short_description': 'Gra rodzinna - szybka "edycja".',
        "seo_title": "Gra - rodzinna | Graszki.pl",
        "meta_description": "Opis - dla 2-4 graczy.",
        "tags": ["kolej", "gra rodzinna"],
    }

    assert batch._content_differences(expected, actual) == []
    assert batch._normalized_hash({"extended_description_html": None})


def test_readback_comparison_names_different_fields():
    expected = {field: "wartość" for field in batch.CONTENT_FIELDS}
    expected["tags"] = ["tag"]
    actual = dict(expected)
    actual["short_description"] = "inna wartość"
    actual["tags"] = ["inny tag"]

    assert batch._content_differences(expected, actual) == ["opis skrócony", "tagi"]


def test_publish_failure_message_contains_product_and_reason():
    rows = [
        {"product_id": "5523", "name": "Azul: Witraże Sintry", "error": "Różni się: opis rozszerzony."},
    ]

    message = batch._publish_failure_message(rows)

    assert "5523 Azul: Witraże Sintry" in message
    assert "opis rozszerzony" in message


def test_batch_report_is_semicolon_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "DB_PATH", tmp_path / "batch.sqlite3")
    created = batch.create_batch(
        csv_bytes(SKY_HEADER, [sky_row()], ";", "utf-8"),
        csv_bytes(REBEL_HEADER, [rebel_row()], ",", "iso-8859-2"),
        "Raport",
    )
    report = batch.build_report_csv(created["id"])
    parsed = list(csv.reader(io.StringIO(report), delimiter=";"))
    assert parsed[0][:3] == ["ID", "Nazwa", "EAN"]
    assert parsed[1][0:3] == ["101", "Zażółć", "5901"]
