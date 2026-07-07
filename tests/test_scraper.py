from app.scraper import (
    clean_pdf_text,
    get_google_drive_download_url,
    get_google_drive_file_id,
    is_stale_google_drive_cache,
    sanitize_filename,
    scrape_pdf,
)


class FakeResponse:
    def __init__(self, content: bytes, headers: dict | None = None, status_code: int = 200):
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code


def test_google_drive_file_id_and_download_url():
    url = "https://drive.google.com/file/d/1PUHyT-3gYak-V1gq3R2t25Xla2Kp4Att/view?usp=sharing"

    assert get_google_drive_file_id(url) == "1PUHyT-3gYak-V1gq3R2t25Xla2Kp4Att"
    assert (
        get_google_drive_download_url(url)
        == "https://drive.google.com/uc?export=download&id=1PUHyT-3gYak-V1gq3R2t25Xla2Kp4Att"
    )


def test_stale_google_drive_cache_detection():
    cached = {
        "url": "https://drive.google.com/file/d/example/view",
        "body": "DOE_Rulebook_PL_compressed.pdf - Dysk Google\nWczytuję…",
        "pdf_text_extracted": False,
    }

    assert is_stale_google_drive_cache(cached)


def test_scrape_pdf_marks_non_pdf_response_as_failed():
    response = FakeResponse(
        b"<html>Wczytuje</html>",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

    result = scrape_pdf("https://drive.google.com/file/d/example/view", response=response)

    assert result["is_pdf"] is True
    assert result["pdf_text_extracted"] is False
    assert result["body"] == ""
    assert "Nie udało się pobrać pliku PDF" in result["error_msg"]


def test_clean_pdf_text_removes_common_font_artifacts_and_page_numbers():
    raw = "1\n/N.smcp/A.smcp/T.smcp\nkomponenty\n16 kart Maga\n2\nOpis gry"

    cleaned = clean_pdf_text(raw)

    assert ".smcp" not in cleaned
    assert "\n1\n" not in f"\n{cleaned}\n"
    assert "komponenty" in cleaned
    assert "16 kart Maga" in cleaned


def test_sanitize_filename_keeps_pdf_extension():
    assert sanitize_filename("DOE Rulebook V2 PL.pdf") == "DOE_Rulebook_V2_PL.pdf"
    assert sanitize_filename("instrukcja") == "instrukcja.pdf"
