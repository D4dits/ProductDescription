"""Persistent Rebel-to-Sky-Shop content workflow.

The module deliberately separates generation from publication. Importing and
generating can never alter the shop; publication requires approved records and
sends only the product id plus the five content fields.
"""

from __future__ import annotations

import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Iterable
import unicodedata

from bs4 import BeautifulSoup

from app.config import (
    BATCH_DATA_DIR,
    BATCH_GENERATION_WORKERS,
    REBEL_FEED_URL,
    SKYSHOP_API_KEY,
    SKYSHOP_API_URL,
    USE_LEGACY_INLINE_STYLES,
)
from app.generator import (
    apply_legacy_inline_styles,
    generate_descriptions,
    normalize_description_html,
    normalize_product_metadata,
)
from app.json_utils import parse_llm_json
from app.llm import LLMAuthenticationError, LLMError, generate_text, validate_llm_configuration
from app.logger import logger
from app.validator import validate_generated_content


DB_PATH = BATCH_DATA_DIR / "batches.sqlite3"
GENERATOR_VERSION = "rebel-batch-v1"
CONTENT_FIELDS = (
    "extended_description_html",
    "short_description",
    "seo_title",
    "meta_description",
    "tags",
)
SKY_XML_FIELDS = {
    # Sky-Shop's import XML names differ from getProductData: prod_desc is
    # imported into prod_desclong, while prod_shortdesc is returned as prod_desc.
    "extended_description_html": "prod_desc",
    "short_description": "prod_shortdesc",
    "seo_title": "prod_seotitle",
    "meta_description": "prod_seodesc",
    "tags": "prod_keywords",
}
PUBLISH_CHUNK_SIZE = 10
STALE_OPERATION_SECONDS = 15 * 60
ACTIVE_OPERATION_STATUSES = {"generating", "publishing", "rolling_back"}
_running_jobs: set[tuple[str, str]] = set()
_jobs_lock = threading.Lock()


class BatchError(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _operation_is_stale(row: sqlite3.Row | dict[str, Any], now: datetime | None = None) -> bool:
    if row["status"] not in ACTIVE_OPERATION_STATUSES:
        return False
    updated_at = _parse_utc(row["updated_at"])
    if not updated_at:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - updated_at).total_seconds() >= STALE_OPERATION_SECONDS


def _stale_operation_message(status: str) -> str:
    action = "publikacja" if status == "publishing" else "przywracanie kopii" if status == "rolling_back" else "generowanie"
    return (
        f"Wygląda na to, że {action} została przerwana. "
        "Zweryfikowane produkty nie będą wysyłane ponownie; możesz wznowić operację dla pozostałych produktów."
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                name TEXT NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                matched_ean INTEGER NOT NULL DEFAULT 0,
                matched_name INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                operation_total INTEGER NOT NULL DEFAULT 0,
                operation_done INTEGER NOT NULL DEFAULT 0,
                operation_started_at TEXT NOT NULL DEFAULT '',
                current_product TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS batch_products (
                batch_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                name TEXT NOT NULL,
                ean TEXT NOT NULL DEFAULT '',
                product_type TEXT NOT NULL,
                match_method TEXT NOT NULL,
                status TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                source_hash TEXT NOT NULL,
                source_json TEXT NOT NULL,
                current_json TEXT NOT NULL,
                content_json TEXT,
                backup_json TEXT,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (batch_id, product_id),
                FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_batch_products_status
                ON batch_products(batch_id, status);
            CREATE INDEX IF NOT EXISTS idx_batch_products_source_hash
                ON batch_products(product_id, source_hash, status);
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(batches)")}
        migrations = {
            "operation_total": "INTEGER NOT NULL DEFAULT 0",
            "operation_done": "INTEGER NOT NULL DEFAULT 0",
            "operation_started_at": "TEXT NOT NULL DEFAULT ''",
            "current_product": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE batches ADD COLUMN {column} {definition}")


def recover_interrupted_jobs() -> None:
    """Make work resumable after a server stop without touching completed rows."""
    init_db()
    now = _utcnow()
    with _connect() as conn:
        conn.execute(
            "UPDATE batch_products SET status='failed', error='Generowanie przerwane przez restart serwera.', updated_at=? "
            "WHERE status='generating'",
            (now,),
        )
        conn.execute(
            "UPDATE batches SET status='failed', message='Operacja przerwana przez restart serwera. "
            "Zweryfikowane produkty nie będą wysyłane ponownie; możesz wznowić operację dla pozostałych produktów.', updated_at=? "
            "WHERE status IN ('generating','publishing','rolling_back')",
            (now,),
        )


def decode_upload(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise BatchError("Nieprawidłowa zawartość przesłanego pliku.") from exc
    if len(decoded) > 50 * 1024 * 1024:
        raise BatchError("Plik przekracza limit 50 MB.")
    return decoded


def _decode_csv(raw: bytes, encodings: Iterable[str]) -> str:
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BatchError("Nie udało się rozpoznać kodowania pliku CSV.")


def parse_sky_csv(raw: bytes) -> list[dict[str, str]]:
    text = _decode_csv(raw, ("utf-8-sig", "utf-8"))
    rows = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=";"))
    required = {"Nazwa produktu", "ID", "EAN", "Kategoria"}
    if not rows or not required.issubset(rows[0]):
        raise BatchError("Eksport Sky-Shop nie zawiera wymaganych kolumn.")
    ids = [row["ID"].strip() for row in rows]
    if any(not re.fullmatch(r"\d+", product_id) for product_id in ids):
        raise BatchError("Eksport Sky-Shop zawiera nieprawidłowe ID produktu.")
    duplicates = {value for value, count in Counter(ids).items() if count > 1}
    if duplicates:
        raise BatchError(f"Eksport Sky-Shop zawiera powtórzone ID: {', '.join(sorted(duplicates)[:5])}")
    return rows


def parse_rebel_csv(raw: bytes) -> list[dict[str, str]]:
    # The supplier calls this encoding "latin2" (ISO-8859-2).
    text = _decode_csv(raw, ("iso-8859-2", "windows-1250", "utf-8-sig"))
    rows = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=","))
    required = {"IDProduct", "ProductName", "EAN", "Description", "FullDescription"}
    if not rows or not required.issubset(rows[0]):
        raise BatchError("Feed Rebel nie zawiera wymaganych kolumn.")
    return rows


def fetch_rebel_feed(url: str | None = None, timeout: int = 60) -> bytes:
    feed_url = url or REBEL_FEED_URL
    if not feed_url:
        raise BatchError("Brak REBEL_FEED_URL. Ustaw adres feedu w pliku .env lub prześlij plik Rebel.")
    safe_url = urllib.parse.urlsplit(feed_url)._replace(query="").geturl()
    logger.info("Downloading Rebel feed from %s", safe_url)
    request = urllib.request.Request(feed_url, headers={"User-Agent": "graszki-batch-import/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise BatchError(f"Nie udało się pobrać feedu Rebel: {exc}") from exc


def _normalize_name(value: str) -> str:
    import unicodedata

    ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(unescape(value or ""), "html.parser").get_text(" ")).strip()


def _rebel_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())).strip("-")


def parse_rebel_product_page(raw: bytes) -> dict[str, Any]:
    soup = BeautifulSoup(raw, "html.parser")
    result: dict[str, Any] = {}
    for title in soup.select("dt"):
        label = _plain_text(title.get_text(" ")).lower().rstrip(":")
        value = title.find_next_sibling("dd")
        if not value:
            continue
        items = [_plain_text(item.get_text(" ")) for item in value.select("li")]
        items = [item for item in items if item]
        text = _plain_text(value.get_text(" "))
        if "zawartość pudełka" in label and items:
            result["box_contents"] = items
        elif "liczba graczy" in label and text:
            result["players"] = text
        elif ("wiek" in label or "od lat" in label) and text:
            result["age"] = text
        elif "czas gry" in label and text:
            result["play_time"] = text
    return result


def enrich_rebel_source(source: dict[str, Any], product_type: str, timeout: int = 15) -> dict[str, Any]:
    """Add structured facts omitted from the CSV, keeping the page URL as provenance."""
    if source.get("rebel_page_url"):
        return source
    supplier_id = str(source.get("supplier_id") or "").strip()
    name = str(source.get("supplier_name") or "").strip()
    if not supplier_id or not name:
        return source
    slug = _rebel_slug(name)
    sections = ["akcesoria-do-gier", "gry-planszowe"] if product_type == "accessory" else ["gry-planszowe", "gry-rpg"]
    for section in sections:
        url = f"https://www.rebel.pl/{section}/{slug}-{supplier_id}.html"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "graszki-batch-import/1.0", "Accept-Encoding": "gzip"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                facts = parse_rebel_product_page(raw)
                enriched = dict(source)
                for key in ("box_contents", "players", "age", "play_time"):
                    if facts.get(key) and not enriched.get(key):
                        enriched[key] = facts[key]
                enriched["rebel_page_url"] = response.geturl()
                return enriched
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            logger.warning("Could not enrich Rebel product %s: HTTP %s", supplier_id, exc.code)
            break
        except Exception as exc:
            logger.warning("Could not enrich Rebel product %s: %s", supplier_id, exc)
            break
    return source


def _product_type(sky: dict[str, str], rebel: dict[str, str]) -> str:
    combined = " ".join((sky.get("Kategoria", ""), rebel.get("Category", ""))).lower()
    return "accessory" if "koszulk" in combined else "game"


def _range_value(minimum: str, maximum: str, suffix: str = "") -> str:
    minimum, maximum = (minimum or "").strip(), (maximum or "").strip()
    if minimum and maximum and minimum != maximum:
        return f"{minimum}-{maximum}{suffix}"
    return f"{minimum or maximum}{suffix}" if minimum or maximum else ""


def _source_payload(sky: dict[str, str], rebel: dict[str, str], match_method: str) -> dict[str, Any]:
    return {
        "supplier_id": rebel.get("IDProduct", "").strip(),
        "supplier_name": rebel.get("ProductName", "").strip(),
        "match_method": match_method,
        "description": _plain_text(rebel.get("Description", "")),
        "full_description": _plain_text(rebel.get("FullDescription", "")),
        "publisher": _plain_text(rebel.get("Publisher", "")) or _plain_text(sky.get("Producent", "")),
        "category": rebel.get("Category", "").strip(),
        "store_category": sky.get("Kategoria", "").strip(),
        "age": f"od {rebel.get('MinAge', '').strip()} lat" if rebel.get("MinAge", "").strip() else "",
        "players": _range_value(rebel.get("MinPlayers", ""), rebel.get("MaxPlayers", "")),
        "play_time": _range_value(rebel.get("MinPlayingTime", ""), rebel.get("MaxPlayingTime", ""), " min"),
        "language": rebel.get("Language", "").strip(),
        "release_date": rebel.get("ReleaseDate", "").strip(),
        "product_code": rebel.get("ProductCode", "").strip(),
        "ean": sky.get("EAN", "").strip(),
        "image_url": rebel.get("ImageURL", "").strip(),
    }


def _current_content(sky: dict[str, str]) -> dict[str, Any]:
    return {
        "extended_description_html": sky.get("Opis rozszerzony", ""),
        "short_description": sky.get("Opis skrócony", ""),
        "seo_title": sky.get("Tytuł strony", ""),
        "meta_description": sky.get("Opis strony", ""),
        "tags": [tag.strip() for tag in sky.get("Tagi (słowa kluczowe)", "").split(",") if tag.strip()],
    }


def match_products(
    sky_rows: list[dict[str, str]], rebel_rows: list[dict[str, str]], strict: bool = True
) -> list[dict[str, Any]]:
    by_ean: dict[str, list[dict[str, str]]] = {}
    by_name: dict[str, list[dict[str, str]]] = {}
    for row in rebel_rows:
        ean = row.get("EAN", "").strip()
        if ean:
            by_ean.setdefault(ean, []).append(row)
        by_name.setdefault(_normalize_name(row.get("ProductName", "")), []).append(row)

    matched = []
    for sky in sky_rows:
        ean = sky.get("EAN", "").strip()
        candidates = by_ean.get(ean, []) if ean else []
        method = "ean"
        if not candidates:
            candidates = by_name.get(_normalize_name(sky.get("Nazwa produktu", "")), [])
            method = "name"
        match_error = ""
        if len(candidates) != 1:
            reason = "brak dopasowania" if not candidates else "niejednoznaczne dopasowanie"
            match_error = f"{reason}: ID {sky.get('ID')} – {sky.get('Nazwa produktu')}"
            if strict:
                raise BatchError(match_error)
            rebel = {}
            method = "unmatched" if not candidates else "ambiguous"
        else:
            rebel = candidates[0]
        source = _source_payload(sky, rebel, method)
        if match_error:
            source["match_error"] = match_error
        material = {key: source[key] for key in source if key not in {"image_url", "match_method"}}
        source_hash = hashlib.sha256(
            json.dumps({"version": GENERATOR_VERSION, "source": material}, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        matched.append(
            {
                "product_id": sky["ID"].strip(),
                "name": sky["Nazwa produktu"].strip(),
                "ean": ean,
                "product_type": _product_type(sky, rebel),
                "match_method": method,
                "source_hash": source_hash,
                "source": source,
                "current": _current_content(sky),
                "initial_status": "failed" if match_error else "matched",
                "error": match_error,
            }
        )
    return matched


def create_batch(sky_raw: bytes, rebel_raw: bytes | None, name: str = "") -> dict[str, Any]:
    init_db()
    sky_rows = parse_sky_csv(sky_raw)
    rebel_rows = parse_rebel_csv(rebel_raw if rebel_raw is not None else fetch_rebel_feed())
    products = match_products(sky_rows, rebel_rows, strict=False)
    batch_id = uuid.uuid4().hex[:12]
    now = _utcnow()
    label = name.strip() or f"Import {now[:10]}"

    with _connect() as conn:
        import_errors = sum(product["initial_status"] == "failed" for product in products)
        conn.execute(
            "INSERT INTO batches(id, created_at, updated_at, status, name, total, matched_ean, matched_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (batch_id, now, now, "ready_with_errors" if import_errors else "ready", label, len(products), sum(p["match_method"] == "ean" for p in products), sum(p["match_method"] == "name" for p in products)),
        )
        conn.execute("UPDATE batches SET errors=? WHERE id=?", (import_errors, batch_id))
        for product in products:
            previous = conn.execute(
                "SELECT content_json FROM batch_products WHERE product_id=? AND source_hash=? "
                "AND status='verified' ORDER BY updated_at DESC LIMIT 1",
                (product["product_id"], product["source_hash"]),
            ).fetchone()
            status = "unchanged" if previous else product["initial_status"]
            content_json = previous["content_json"] if previous else None
            conn.execute(
                """INSERT INTO batch_products(
                    batch_id, product_id, name, ean, product_type, match_method, status,
                    source_hash, source_json, current_json, content_json, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch_id, product["product_id"], product["name"], product["ean"],
                    product["product_type"], product["match_method"], status,
                    product["source_hash"], json.dumps(product["source"], ensure_ascii=False),
                    json.dumps(product["current"], ensure_ascii=False), content_json, product["error"], now,
                ),
            )
    return get_batch(batch_id)


def _counts(conn: sqlite3.Connection, batch_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) count FROM batch_products WHERE batch_id=? GROUP BY status", (batch_id,)
    ).fetchall()
    return {row["status"]: row["count"] for row in rows}


def get_batch(batch_id: str) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise BatchError("Nie znaleziono partii.")
        result = dict(row)
        stale = _operation_is_stale(row)
        if stale:
            result["status"] = "interrupted"
            result["message"] = _stale_operation_message(row["status"])
        result["counts"] = _counts(conn, batch_id)
        total = result.get("operation_total") or 0
        done = result.get("operation_done") or 0
        started_at = result.get("operation_started_at") or ""
        elapsed = 0
        if started_at:
            parsed_started_at = _parse_utc(started_at)
            if parsed_started_at:
                elapsed = max(0, int((datetime.now(timezone.utc) - parsed_started_at).total_seconds()))
        eta = 0 if stale else int(elapsed / done * (total - done)) if done and total > done else 0
        result["progress"] = {
            "done": done,
            "total": total,
            "percent": round(done / total * 100) if total else 0,
            "elapsed_seconds": elapsed,
            "eta_seconds": eta,
            "current_product": result.get("current_product") or "",
            "workers": BATCH_GENERATION_WORKERS,
            "stale": stale,
        }
        return result


def list_batches() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM batches ORDER BY created_at DESC LIMIT 50").fetchall()
        return [dict(row) | {"counts": _counts(conn, row["id"])} for row in rows]


def _status_reason(status: str, error: str, warnings: list[str]) -> str:
    if error:
        return error
    if status == "needs_review":
        if warnings:
            return f"Treść wygenerowana. Przed zatwierdzeniem sprawdź {len(warnings)} ostrzeżenie(a) walidatora."
        return "Treść wygenerowana poprawnie. Wymaga ręcznej kontroli przed wysłaniem do Sky-Shop."
    return {
        "matched": "Produkt dopasowany do danych Rebel i oczekuje na wygenerowanie treści.",
        "generating": "Trwa pobieranie danych źródłowych lub generowanie treści przez model.",
        "approved": "Treść została ręcznie zatwierdzona i jest gotowa do wysłania.",
        "verified": "Treść wysłano i potwierdzono odczytem z API Sky-Shop.",
        "unchanged": "Dane źródłowe nie zmieniły się od poprzedniej zweryfikowanej partii.",
        "rolled_back": "Przywrócono treść zapisaną w kopii bezpieczeństwa.",
        "failed": "Operacja dla produktu zakończyła się błędem.",
    }.get(status, "")


def _decode_product(row: sqlite3.Row, include_source: bool = True) -> dict[str, Any]:
    result = dict(row)
    for key in ("content_json", "current_json", "backup_json", "warnings_json"):
        target = key.removesuffix("_json")
        result[target] = json.loads(result.pop(key) or ("[]" if key == "warnings_json" else "{}"))
    if include_source:
        result["source"] = json.loads(result.pop("source_json"))
    else:
        result.pop("source_json")
    result["approved"] = bool(result["approved"])
    return result


def list_products(batch_id: str, status: str = "", limit: int = 200, offset: int = 0) -> dict[str, Any]:
    init_db()
    limit = max(1, min(limit, 1000))
    with _connect() as conn:
        where = "batch_id=?"
        params: list[Any] = [batch_id]
        if status:
            where += " AND status=?"
            params.append(status)
        total = conn.execute(f"SELECT COUNT(*) FROM batch_products WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT batch_id, product_id, name, ean, product_type, match_method, status, approved, "
            f"source_hash, warnings_json, error, updated_at FROM batch_products WHERE {where} "
            f"ORDER BY CAST(product_id AS INTEGER) LIMIT ? OFFSET ?",
            (*params, limit, max(offset, 0)),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["approved"] = bool(item["approved"])
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            item["status_reason"] = _status_reason(item["status"], item["error"], item["warnings"])
            items.append(item)
        return {"total": total, "items": items}


def get_product(batch_id: str, product_id: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM batch_products WHERE batch_id=? AND product_id=?", (batch_id, product_id)
        ).fetchone()
        if not row:
            raise BatchError("Nie znaleziono produktu w partii.")
        product = _decode_product(row)
        product["status_reason"] = _status_reason(product["status"], product["error"], product["warnings"])
        return product


def build_report_csv(batch_id: str) -> str:
    get_batch(batch_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "ID", "Nazwa", "EAN", "Typ", "Dopasowanie", "Status", "Zatwierdzony",
            "Błąd", "Ostrzeżenia", "Opis skrócony", "Tytuł strony", "Opis strony", "Tagi",
        ]
    )
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM batch_products WHERE batch_id=? ORDER BY CAST(product_id AS INTEGER)", (batch_id,)
        ).fetchall()
    for row in rows:
        product = _decode_product(row)
        content = product.get("content") or {}
        writer.writerow(
            [
                product["product_id"], product["name"], product["ean"], product["product_type"],
                product["match_method"], product["status"], "1" if product["approved"] else "0",
                product["error"], " | ".join(product["warnings"]), content.get("short_description", ""),
                content.get("seo_title", ""), content.get("meta_description", ""),
                ", ".join(content.get("tags", [])),
            ]
        )
    return output.getvalue()


def _resolved_facts(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "publisher": source.get("publisher", ""),
        "players": source.get("players", ""),
        "age": source.get("age", ""),
        "play_time": source.get("play_time", ""),
        "edition_language": "polskie" if source.get("language") == "pl" else source.get("language", ""),
        "description": source.get("description", ""),
        "supplier_description": source.get("full_description", ""),
        "category": source.get("category", ""),
        "ean": source.get("ean", ""),
        "box_contents": source.get("box_contents", []),
    }


ACCESSORY_PROMPT = """Napisz unikalną, rzeczową treść produktu dla sklepu Graszki.pl.
To jest akcesorium do gier, nie gra. Nie opisuj zasad ani rozgrywki. Używaj tylko podanych faktów.
Opis HTML ma mieć sekcje h2: Krótko o produkcie, Najważniejsze cechy, Kompatybilność i zastosowanie, Dlaczego warto, Dane produktu.
Nie wpisuj braków, ceny, stanu magazynowego ani informacji o źródle.
Zwróć tylko JSON: short_description (max 300 znaków), seo_title (bez nazwy sklepu, max 50 znaków),
meta_description (140-160 znaków), tags (5-15 fraz), extended_description_html (czysty HTML).

Nazwa: {name}
Fakty: {facts}
"""


def _generate_accessory(name: str, source: dict[str, Any]) -> dict[str, Any]:
    facts = json.dumps(source, ensure_ascii=False, indent=2)
    raw = generate_text(
        ACCESSORY_PROMPT.format(name=name, facts=facts),
        system_instruction="Jesteś polskim redaktorem e-commerce. Nie wolno Ci dopowiadać niepotwierdzonych faktów.",
        json_mode=True,
    )
    generated = parse_llm_json(raw)
    generated["product_name"] = name
    normalize_product_metadata(generated)
    html = normalize_description_html(generated.get("extended_description_html", ""), game_name=name)
    generated["extended_description_html"] = apply_legacy_inline_styles(html) if USE_LEGACY_INLINE_STYLES else html
    return generated


def _generate_game(name: str, source: dict[str, Any]) -> dict[str, Any]:
    if not source.get("description") and not source.get("full_description"):
        # Rare fallback for future feeds without copy. Keep the normal pipeline
        # out of the 992-product fast path because it performs web research.
        from app.pipeline import run_generation_pipeline

        return run_generation_pipeline(
            {
                "product_name": name,
                "publisher": source.get("publisher", ""),
                "category": source.get("category", ""),
                "tone_preference": "sales",
            }
        )
    facts = _resolved_facts(source)
    generated = generate_descriptions(
        game_name=name,
        resolved_facts=facts,
        user_inputs={"product_name": name, "publisher": source.get("publisher", ""), "tone_preference": "sales"},
        source_context=[
            {
                "url": "rebel-feed",
                "title": "Feed hurtowni Rebel",
                "source_type": "distributor",
                "body": "\n".join(filter(None, (source.get("description", ""), source.get("full_description", "")))),
            }
        ],
    )
    generated["product_name"] = name
    normalize_product_metadata(generated)
    return generated


def infer_primary_category(name: str, source: dict[str, Any]) -> str:
    """Choose one useful storefront category instead of trusting the bulk-import default."""
    store_category = source.get("store_category") or ""
    supplier_category = source.get("category") or ""
    combined = _plain_text(
        " ".join(str(value or "") for value in (name, supplier_category, source.get("description"), source.get("full_description")))
    ).lower()

    if re.search(r"(?:^|/)akcesoria(?:/|$)|koszulki na karty|maty|tacki na kości", store_category.lower()):
        return store_category

    rules = (
        ("Dodatki do gier", r"\b(?:dodatek|rozszerzeni\w*)\b"),
        ("RPG", r"\brpg\b|\bpodręcznik\w* do gry fabularnej\b"),
        ("Logiczne", r"\b(?:gra|gry|planszówka)\s+logiczn\w*\b|\blogiczn(?:a|ej|e)\s+gra\b|\bgr[ay]\s+quizow\w*\b"),
        ("Dwuosobowe", r"\bdwuosobow\w*\b|\bdla dwóch graczy\b|\bgra dla 2 graczy\b"),
        (
            "Karciane",
            r"\b(?:gra|gry)\s+karcian\w*\b|\bkarciank\w*\b|\bgra oparta na [^.]{0,80}\bkart\w*\b|"
            r"\brywaliz\w* o karty\b|\bzarządzani\w* [^.]{0,60}\bkartami\b",
        ),
        ("Kooperacyjne", r"\bkooperacyjn\w*\b"),
        ("Imprezowe", r"\b(?:gra|gry)\s+imprezow\w*\b|\bimprezow(?:a|ej|e)\s+gra\b"),
        ("Dla dzieci", r"\b(?:gra|gry)\s+dla dzieci\b|\bdziecięc\w*\b"),
        ("Gry Solo", r"\b(?:gra|tryb|rozgrywka)\s+solo\b|\bjednoosobow\w*\b"),
        ("Ekonomiczne", r"\b(?:gra|gry)\s+ekonomiczn\w*\b|\bekonomiczn(?:a|ej|e)\s+gra\b"),
        (
            "Strategiczne",
            r"\b(?:gra|gry)\s+strategiczn\w*\b|\bstrategiczn(?:a|ej|e)\s+gra\b|"
            r"\bstrategiczn\w* (?:myśleni\w*|decyzj\w*)\b",
        ),
        ("Przygodowe", r"\b(?:gra|gry)\s+przygodow\w*\b|\bprzygodow(?:a|ej|e)\s+gra\b"),
    )
    for category, pattern in rules:
        if re.search(pattern, combined, re.IGNORECASE):
            return category
    return store_category or supplier_category


def _truncate_at_word(value: str, max_length: int, min_length: int = 0) -> str:
    value = _plain_text(value)
    if len(value) <= max_length:
        return value
    fragment = value[:max_length]
    punctuation = max(fragment.rfind("."), fragment.rfind("!"), fragment.rfind("?"))
    sentence_threshold = min_length or max_length // 2
    if punctuation >= 0 and punctuation + 1 >= sentence_threshold:
        return fragment[:punctuation + 1].strip()
    space = fragment.rfind(" ", min_length, max_length)
    shortened = fragment[:space if space >= min_length else max_length].rstrip(" ,;:-")
    if shortened.endswith((".", "!", "?")):
        return shortened
    return shortened[:max_length - 1].rstrip() + "."


def repair_generated_metadata(content: dict[str, Any]) -> list[str]:
    """Repair mechanical length violations without introducing product facts."""
    repairs: list[str] = []
    short_description = _plain_text(content.get("short_description", ""))
    if len(short_description) > 300:
        content["short_description"] = _truncate_at_word(short_description, 300)
        repairs.append("Automatycznie skrócono opis skrócony do 300 znaków.")

    meta_description = _plain_text(content.get("meta_description", ""))
    if len(meta_description) > 170:
        content["meta_description"] = _truncate_at_word(meta_description, 160, 130)
        repairs.append("Automatycznie skrócono meta opis.")
    elif meta_description and len(meta_description) < 130:
        addition = _plain_text(content.get("short_description", ""))
        candidate = f"{meta_description} {addition}".strip() if addition and addition.casefold() not in meta_description.casefold() else meta_description
        if len(candidate) < 130:
            candidate = f"{candidate} Sprawdź szczegóły produktu w Graszki.pl.".strip()
        content["meta_description"] = _truncate_at_word(candidate, 160, 130)
        repairs.append("Automatycznie uzupełniono zbyt krótki meta opis.")
    return repairs


def _content_is_complete(content: dict[str, Any]) -> bool:
    return all(content.get(field) for field in CONTENT_FIELDS)


def _generate_content_with_retry(name: str, source: dict[str, Any], product_type: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            content = _generate_accessory(name, source) if product_type == "accessory" else _generate_game(name, source)
            if _content_is_complete(content):
                return content
            last_error = LLMError("Model nie zwrócił wszystkich wymaganych pól.")
        except LLMAuthenticationError:
            raise
        except (LLMError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt == 0:
            logger.warning("Retrying incomplete generation for product %s", name)
    raise LLMError(f"Generowanie nie powiodło się po dwóch próbach: {last_error}")


def ensure_box_contents(
    content: dict[str, Any],
    name: str,
    source: dict[str, Any],
    preserve_existing: bool = False,
) -> dict[str, Any]:
    """Deterministically insert the verified list instead of asking the model to reproduce it."""
    box_contents = source.get("box_contents") or []
    if not content.get("extended_description_html"):
        return content
    store_category = infer_primary_category(name, source)
    if not box_contents:
        html = normalize_description_html(
            content["extended_description_html"],
            box_contents=[],
            game_name=name,
            category=store_category,
            replace_category=not preserve_existing,
        )
        content["extended_description_html"] = apply_legacy_inline_styles(html) if USE_LEGACY_INLINE_STYLES else html
        return content
    soup = BeautifulSoup(content["extended_description_html"], "html.parser")
    heading = next(
        (
            item for item in soup.find_all(["h1", "h2", "h3", "h4"])
            if _plain_text(item.get_text(" ")).lower().rstrip(":") == "zawartość pudełka"
        ),
        None,
    )
    corrupted_additional_list = None
    if heading is not None and not preserve_existing:
        following_heading = heading.find_next_sibling()
        if (
            following_heading
            and following_heading.name in {"h1", "h2", "h3", "h4"}
            and _plain_text(following_heading.get_text(" ")).lower().rstrip(":") == "dodatkowe informacje"
        ):
            candidate = following_heading.find_next_sibling()
            if candidate and candidate.name == "ul":
                current_items = [_plain_text(item.get_text(" ")) for item in candidate.find_all("li", recursive=False)]
                if current_items == [str(item) for item in box_contents]:
                    corrupted_additional_list = candidate
    if heading is None:
        heading = soup.new_tag("h2")
        heading.string = "Zawartość pudełka:"
        target = next(
            (
                item for item in soup.find_all(["h1", "h2", "h3", "h4"])
                if _plain_text(item.get_text(" ")).lower().rstrip(":") == "dodatkowe informacje"
            ),
            None,
        )
        if target:
            target.insert_before(heading)
        else:
            (soup.find("div", class_="def") or soup).append(heading)
    candidate = heading.find_next_sibling()
    existing_list = candidate if candidate and candidate.name == "ul" else None
    if existing_list is None:
        existing_list = soup.new_tag("ul")
        heading.insert_after(existing_list)
    elif not preserve_existing:
        existing_list.clear()
    if not preserve_existing or not existing_list.find("li", recursive=False):
        for value in box_contents:
            item = soup.new_tag("li")
            item.string = str(value)
            existing_list.append(item)
    if corrupted_additional_list is not None:
        corrupted_additional_list.clear()
        additional_values = [
            ("Wydawca", source.get("publisher")),
            ("Wydanie", "polskie" if source.get("language") == "pl" else source.get("language")),
            ("Instrukcja", "polska" if source.get("language") == "pl" else ""),
            ("Liczba graczy", source.get("players")),
            ("Zalecany wiek", source.get("age")),
            ("Czas gry", source.get("play_time")),
            ("EAN", source.get("ean")),
        ]
        for label, value in additional_values:
            if not value:
                continue
            item = soup.new_tag("li")
            strong = soup.new_tag("strong")
            strong.string = f"{label}:"
            item.append(strong)
            item.append(f" {value}")
            corrupted_additional_list.append(item)
    html = normalize_description_html(
        str(soup),
        box_contents=box_contents,
        game_name=name,
        category=store_category,
        replace_category=not preserve_existing,
    )
    content["extended_description_html"] = apply_legacy_inline_styles(html) if USE_LEGACY_INLINE_STYLES else html
    return content


def validate_batch_content(content: dict[str, Any], product_type: str, source: dict[str, Any]) -> tuple[list[str], list[str]]:
    normalize_product_metadata(content)
    errors: list[str] = []
    warnings: list[str] = []
    for field in CONTENT_FIELDS:
        if not content.get(field):
            errors.append(f"Puste pole: {field}")
    if len(content.get("short_description", "")) > 300:
        errors.append("Opis skrócony przekracza 300 znaków.")
    if len(content.get("seo_title", "")) > 65:
        errors.append("Tytuł SEO przekracza 65 znaków.")
    meta_length = len(content.get("meta_description", ""))
    if content.get("meta_description") and not 130 <= meta_length <= 170:
        errors.append(f"Meta opis ma {meta_length} znaków; wymagane 130-170.")
    tags = content.get("tags", [])
    if not isinstance(tags, list) or not 5 <= len({str(tag).lower() for tag in tags}) <= 15:
        errors.append("Tagi muszą zawierać 5-15 unikalnych fraz.")
    html = content.get("extended_description_html", "")
    if re.search(r"<script|javascript:|<iframe", html, re.I):
        errors.append("Opis HTML zawiera niedozwolony element.")

    if product_type == "game" and not errors:
        facts = _resolved_facts(source)
        warnings.extend(
            validate_generated_content(
                content.get("short_description", ""), content.get("meta_description", ""),
                content.get("seo_title", ""), html, False, facts,
                {key: "rebel-feed" for key in ("players", "age", "play_time") if facts.get(key)},
                box_contents=source.get("box_contents", []),
            )
        )
    if source.get("box_contents") and not re.search(r"<h[2-3][^>]*>\s*Zawartość pudełka", html, re.I):
        errors.append("Brak wymaganej sekcji „Zawartość pudełka” mimo dostępnej listy źródłowej.")
    if product_type == "accessory" and re.search(r"\b(?:rozgrywk|gracz(?:e|y|a)?|zasad[ya])\b", _plain_text(html), re.I):
        warnings.append("Opis akcesorium może sugerować, że produkt jest grą.")
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def _pilot_ids(conn: sqlite3.Connection, batch_id: str, limit: int = 10) -> list[str]:
    rows = conn.execute(
        "SELECT product_id, product_type, match_method, source_json FROM batch_products "
        "WHERE batch_id=? AND status IN ('matched','failed') ORDER BY CAST(product_id AS INTEGER)", (batch_id,)
    ).fetchall()
    selected: list[str] = []
    buckets = [
        lambda r: r["match_method"] == "name",
        lambda r: r["product_type"] == "accessory",
        lambda r: r["product_type"] == "game" and not json.loads(r["source_json"]).get("players"),
        lambda r: r["product_type"] == "game",
    ]
    for predicate in buckets:
        for row in rows:
            if len(selected) >= limit:
                return selected
            if row["product_id"] not in selected and predicate(row):
                selected.append(row["product_id"])
                if sum(predicate(r) and r["product_id"] in selected for r in rows) >= (2 if len(selected) < 6 else 1):
                    break
    for row in rows:
        if len(selected) >= limit:
            break
        if row["product_id"] not in selected:
            selected.append(row["product_id"])
    return selected


def _generate_batch_product(batch_id: str, product_id: str, stop: threading.Event) -> tuple[str, str]:
    if stop.is_set():
        return "skipped", ""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM batch_products WHERE batch_id=? AND product_id=?", (batch_id, product_id)
        ).fetchone()
        if not row or stop.is_set():
            return "skipped", ""
        conn.execute(
            "UPDATE batch_products SET status='generating', error='', updated_at=? WHERE batch_id=? AND product_id=?",
            (_utcnow(), batch_id, product_id),
        )
        conn.execute(
            "UPDATE batches SET current_product=?, updated_at=? WHERE id=?",
            (row["name"], _utcnow(), batch_id),
        )
    source = json.loads(row["source_json"])
    source = enrich_rebel_source(source, row["product_type"])
    with _connect() as conn:
        conn.execute(
            "UPDATE batch_products SET source_json=? WHERE batch_id=? AND product_id=?",
            (json.dumps(source, ensure_ascii=False), batch_id, product_id),
        )
    try:
        content = _generate_content_with_retry(row["name"], source, row["product_type"])
        repairs = repair_generated_metadata(content)
        content = ensure_box_contents(content, row["name"], source)
        errors, warnings = validate_batch_content(content, row["product_type"], source)
        warnings = repairs + warnings
        status = "failed" if errors else "needs_review"
        with _connect() as conn:
            conn.execute(
                "UPDATE batch_products SET status=?, content_json=?, warnings_json=?, error=?, updated_at=? "
                "WHERE batch_id=? AND product_id=?",
                (status, json.dumps(content, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), " ".join(errors), _utcnow(), batch_id, product_id),
            )
        return status, ""
    except LLMAuthenticationError as exc:
        stop.set()
        message = str(exc)
        logger.error("Batch generation stopped: %s", message)
        with _connect() as conn:
            conn.execute(
                "UPDATE batch_products SET status='matched', error='', updated_at=? WHERE batch_id=? AND product_id=?",
                (_utcnow(), batch_id, product_id),
            )
        return "authentication_error", message
    except Exception as exc:
        logger.exception("Batch generation failed for product %s", product_id)
        with _connect() as conn:
            conn.execute(
                "UPDATE batch_products SET status='failed', error=?, updated_at=? WHERE batch_id=? AND product_id=?",
                (str(exc), _utcnow(), batch_id, product_id),
            )
        return "failed", ""


def _run_generation(batch_id: str, mode: str, limit: int = 50) -> None:
    try:
        with _connect() as conn:
            ids = _pilot_ids(conn, batch_id) if mode == "pilot" else [
                row[0] for row in conn.execute(
                    "SELECT product_id FROM batch_products WHERE batch_id=? AND status IN ('matched','failed')",
                    (batch_id,),
                ).fetchall()
            ]
            if mode == "batch":
                ids = ids[:limit]
            started_at = _utcnow()
            conn.execute(
                "UPDATE batches SET status='generating', updated_at=?, message=?, operation_total=?, "
                "operation_done=0, operation_started_at=?, current_product='' WHERE id=?",
                (started_at, f"Uruchamianie generowania: 0/{len(ids)}", len(ids), started_at, batch_id),
            )

        stop = threading.Event()
        authentication_error = ""
        done = 0
        workers = min(BATCH_GENERATION_WORKERS, max(1, len(ids)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="batch-generate") as executor:
            futures = [executor.submit(_generate_batch_product, batch_id, product_id, stop) for product_id in ids]
            for future in as_completed(futures):
                status, detail = future.result()
                if status == "skipped":
                    continue
                done += 1
                if status == "authentication_error":
                    authentication_error = detail
                with _connect() as conn:
                    conn.execute(
                        "UPDATE batches SET operation_done=?, updated_at=?, message=? WHERE id=?",
                        (done, _utcnow(), f"Wygenerowano {done}/{len(ids)}; równolegle: {workers}", batch_id),
                    )

        with _connect() as conn:
            if authentication_error:
                conn.execute(
                    "UPDATE batch_products SET status='matched', error='', updated_at=? WHERE batch_id=? AND status='generating'",
                    (_utcnow(), batch_id),
                )
                conn.execute(
                    "UPDATE batches SET status='ready', updated_at=?, message=?, current_product='' WHERE id=?",
                    (_utcnow(), authentication_error, batch_id),
                )
            else:
                conn.execute(
                    "UPDATE batches SET status='review', updated_at=?, message=?, operation_done=?, current_product='' WHERE id=?",
                    (
                        _utcnow(),
                        f"Wygenerowano {done}/{len(ids)}. Status „Do kontroli” oznacza, że treść czeka na ręczną weryfikację przed publikacją.",
                        done,
                        batch_id,
                    ),
                )
    finally:
        with _jobs_lock:
            _running_jobs.discard((batch_id, "generate"))


def start_generation(batch_id: str, mode: str, limit: int = 50) -> dict[str, Any]:
    if mode not in {"pilot", "batch", "full"}:
        raise BatchError("Tryb generowania musi mieć wartość pilot, batch albo full.")
    limit = max(1, min(200, int(limit)))
    get_batch(batch_id)
    try:
        validate_llm_configuration()
    except LLMError as exc:
        raise BatchError(str(exc)) from exc
    if mode in {"batch", "full"}:
        with _connect() as conn:
            eligible = conn.execute(
                "SELECT COUNT(*) FROM batch_products WHERE batch_id=? AND status!='unchanged'", (batch_id,)
            ).fetchone()[0]
            approved = conn.execute(
                "SELECT COUNT(*) FROM batch_products WHERE batch_id=? AND approved=1", (batch_id,)
            ).fetchone()[0]
        required = min(10, eligible)
        if required and approved < required:
            raise BatchError(f"Najpierw zatwierdź komplet pilota: {approved}/{required} produktów.")
    key = (batch_id, "generate")
    with _jobs_lock:
        if key in _running_jobs:
            raise BatchError("Generowanie tej partii już trwa.")
        _running_jobs.add(key)
    threading.Thread(target=_run_generation, args=(batch_id, mode, limit), daemon=True).start()
    return {"status": "started", "mode": mode, "limit": limit}


def save_product(batch_id: str, product_id: str, content: dict[str, Any], approved: bool) -> dict[str, Any]:
    product = get_product(batch_id, product_id)
    clean = {field: content.get(field) for field in CONTENT_FIELDS}
    clean = ensure_box_contents(clean, product["name"], product["source"], preserve_existing=True)
    html = normalize_description_html(
        clean.get("extended_description_html", ""),
        box_contents=product["source"].get("box_contents", []),
        game_name=product["name"],
    )
    clean["extended_description_html"] = apply_legacy_inline_styles(html) if USE_LEGACY_INLINE_STYLES else html
    errors, warnings = validate_batch_content(clean, product["product_type"], product["source"])
    if errors:
        raise BatchError(" ".join(errors))
    status = "approved" if approved else "needs_review"
    with _connect() as conn:
        conn.execute(
            "UPDATE batch_products SET content_json=?, warnings_json=?, approved=?, status=?, error='', updated_at=? "
            "WHERE batch_id=? AND product_id=?",
            (json.dumps(clean, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), int(approved), status, _utcnow(), batch_id, product_id),
        )
    return get_product(batch_id, product_id)


def approve_products(batch_id: str, product_ids: list[str]) -> int:
    if not product_ids:
        raise BatchError("Nie wskazano produktów do zatwierdzenia.")
    placeholders = ",".join("?" for _ in product_ids)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE batch_products SET approved=1, status='approved', updated_at=? WHERE batch_id=? "
            f"AND product_id IN ({placeholders}) AND status='needs_review' AND content_json IS NOT NULL",
            (_utcnow(), batch_id, *product_ids),
        )
        return cur.rowcount


def _cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def build_update_xml(products: list[dict[str, Any]], content_key: str = "content") -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<products>"]
    for product in products:
        content = product.get(content_key) or {}
        missing = [field for field in CONTENT_FIELDS if field not in content]
        if missing:
            raise BatchError(f"Produkt {product.get('product_id')} nie ma kompletnej treści.")
        tags = content.get("tags", [])
        tags_text = ", ".join(tags) if isinstance(tags, list) else str(tags)
        values = dict(content)
        values["tags"] = tags_text
        lines.extend(("  <item>", f"    <prod_id>{product['product_id']}</prod_id>"))
        for field, xml_field in SKY_XML_FIELDS.items():
            lines.append(f"    <{xml_field}>{_cdata(str(values.get(field, '')))}</{xml_field}>")
        lines.append("  </item>")
    lines.append("</products>")
    return "\n".join(lines) + "\n"


class SkyShopClient:
    def __init__(self, endpoint: str | None = None, api_key: str | None = None, sleep: Callable[[float], None] = time.sleep):
        self.endpoint = (endpoint or SKYSHOP_API_URL or "").rstrip("/")
        self.api_key = api_key or SKYSHOP_API_KEY or ""
        self.sleep = sleep
        self._last_request = 0.0
        if not self.endpoint or not self.api_key:
            raise BatchError("Brak SKYSHOP_API_URL lub SKYSHOP_API_KEY w pliku .env.")

    def _request(self, function: str, data: dict[str, str], retries: int = 3) -> dict[str, Any]:
        url = f"{self.endpoint}/?function={urllib.parse.quote(function)}"
        payload = {"APIkey": self.api_key, **data}
        for attempt in range(retries):
            wait = 1.0 - (time.monotonic() - self._last_request)
            if wait > 0:
                self.sleep(wait)
            request = urllib.request.Request(
                url, data=urllib.parse.urlencode(payload).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    self._last_request = time.monotonic()
                    parsed = json.loads(response.read().decode("utf-8", errors="replace"))
                    if not isinstance(parsed, dict):
                        raise BatchError("Sky-Shop zwrócił nieprawidłową odpowiedź.")
                    return parsed
            except urllib.error.HTTPError as exc:
                self._last_request = time.monotonic()
                if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                    raise BatchError(f"Błąd Sky-Shop HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                self._last_request = time.monotonic()
                if attempt == retries - 1:
                    raise BatchError(f"Błąd połączenia ze Sky-Shop: {exc}") from exc
            self.sleep(2 ** attempt)
        raise BatchError("Nie udało się wykonać żądania Sky-Shop.")

    def get_products(self, product_ids: list[str]) -> dict[str, dict[str, Any]]:
        # getProducts omits SEO fields in this API version. getProductData is
        # slower, but supplies all five fields required for a safe backup and
        # post-write verification.
        result: dict[str, dict[str, Any]] = {}
        for product_id in product_ids:
            response = self._request("getProductData", {"productID": product_id})
            if response.get("response_code") == 200 and str(response.get("prod_id") or "") == product_id:
                result[product_id] = response
        return result

    def update_products(self, xml: str) -> dict[str, Any]:
        return self._request(
            "addUpdateProducts",
            {"importType": "update", "prodIndex": "prod_id", "xml": xml},
        )


def _live_content(item: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "extended_description_html": ("prod_desclong", "prod_desclong_pl", "extended_description_html"),
        "short_description": ("prod_desc", "prod_desc_pl", "short_description"),
        "seo_title": ("prod_seotitle", "seo_title"),
        "meta_description": ("prod_seodesc", "meta_description"),
        "tags": ("prod_keywords", "tags"),
    }
    result: dict[str, Any] = {}
    for field, candidates in aliases.items():
        value = next((item[key] for key in candidates if key in item), "")
        result[field] = [tag.strip() for tag in str(value or "").split(",") if tag.strip()] if field == "tags" else str(value or "")
    return result


def _normalized_hash(content: dict[str, Any]) -> str:
    normalized = _normalized_content(content)
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _normalize_text_for_readback(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    # The Sky-Shop importer normalizes some typographic punctuation.
    text = text.translate(str.maketrans({
        "–": "-", "—": "-", "−": "-",
        "„": '"', "“": '"', "”": '"',
        "‘": "'", "’": "'",
    }))
    return re.sub(r"\s+", " ", text).strip()


def _normalize_html_for_readback(value: Any) -> str:
    soup = BeautifulSoup(unescape(str(value or "")), "html.parser")
    # Sky-Shop sanitizes semantic section wrappers but retains their contents.
    # Treat the wrapper itself as insignificant during post-write verification.
    for section in soup.find_all("section"):
        section.unwrap()
    for tag in soup.find_all(True):
        classes = [name for name in tag.get("class", []) if name != "def"]
        if classes:
            tag["class"] = sorted(classes)
        elif tag.has_attr("class"):
            del tag["class"]
    html = soup.decode(formatter="minimal")
    html = re.sub(r">\s+<", "><", html)
    # The editor may insert a formatting space immediately after a line break.
    html = re.sub(r"(<br\s*/?>)\s+", r"\1", html, flags=re.IGNORECASE)
    return _normalize_text_for_readback(html)


def _normalized_content(content: dict[str, Any]) -> dict[str, Any]:
    tags = content.get("tags") or []
    if not isinstance(tags, list):
        tags = [tag.strip() for tag in str(tags).split(",") if tag.strip()]
    return {
        "extended_description_html": _normalize_html_for_readback(content.get("extended_description_html")),
        "short_description": _normalize_text_for_readback(content.get("short_description")),
        "seo_title": _normalize_text_for_readback(content.get("seo_title")),
        "meta_description": _normalize_text_for_readback(content.get("meta_description")),
        "tags": sorted(_normalize_text_for_readback(tag).casefold() for tag in tags),
    }


def _content_differences(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    expected_normalized = _normalized_content(expected)
    actual_normalized = _normalized_content(actual)
    labels = {
        "extended_description_html": "opis rozszerzony",
        "short_description": "opis skrócony",
        "seo_title": "tytuł strony",
        "meta_description": "opis strony",
        "tags": "tagi",
    }
    return [labels[field] for field in CONTENT_FIELDS if expected_normalized[field] != actual_normalized[field]]


def _invariant_hash(item: dict[str, Any]) -> str:
    """Hash commerce fields that this integration must never change."""
    candidates = (
        "prod_name", "prod_symbol", "prod_ean", "prod_price", "prod_amount",
        "prod_tax", "taxpercent", "prod_cat", "cat_id", "prod_hidden",
        "hidden", "prod_search", "external_sales",
    )
    values = {key: item[key] for key in candidates if key in item}
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _update_response_succeeded(response: dict[str, Any], expected_total: int) -> bool:
    stats = response.get("stats") or {}
    if response.get("response_code") != 200 or not stats:
        return False
    total = int(stats.get("total", 0) or 0)
    errors = int(stats.get("errors", 0) or 0)
    updated = int(stats.get("updated", 0) or 0)
    omitted = int(stats.get("omitted", 0) or 0)
    if errors or total != expected_total:
        return False
    if updated + omitted == expected_total:
        return True

    # Sky-Shop sometimes reports omitted=0 in the aggregate while listing
    # unchanged products individually as omitted.
    product_results = stats.get("products") or []
    statuses = [str(item.get("status") or "").lower() for item in product_results if isinstance(item, dict)]
    if any(status not in {"updated", "omitted"} for status in statuses):
        return False
    listed_omitted = sum(status == "omitted" for status in statuses)
    return updated + listed_omitted == expected_total or (
        len(statuses) == expected_total and all(status in {"updated", "omitted"} for status in statuses)
    )


def _publish_failure_message(rows: list[sqlite3.Row]) -> str:
    count = len(rows)
    prefix = (
        "1 produkt nie przeszedł odczytu kontrolnego"
        if count == 1 else f"{count} produktów nie przeszło odczytu kontrolnego"
    )
    details = "; ".join(
        f"{row['product_id']} {row['name']} — {row['error']}" for row in rows[:5]
    )
    if count > 5:
        details += f"; oraz {count - 5} kolejnych"
    return f"Zapis zakończony, ale {prefix}: {details}"


def _run_publish(batch_id: str, rollback: bool = False) -> None:
    action = "rollback" if rollback else "publish"
    try:
        client = SkyShopClient()
        with _connect() as conn:
            if rollback:
                rows = conn.execute("SELECT * FROM batch_products WHERE batch_id=? AND backup_json IS NOT NULL", (batch_id,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM batch_products WHERE batch_id=? AND status IN ('approved', 'failed') AND approved=1",
                    (batch_id,),
                ).fetchall()
            started_at = _utcnow()
            conn.execute(
                "UPDATE batches SET status=?, updated_at=?, message=?, operation_total=?, operation_done=0, "
                "operation_started_at=?, current_product='' WHERE id=?",
                (
                    "rolling_back" if rollback else "publishing", started_at,
                    "Przygotowywanie przywracania" if rollback else "Tworzenie kopii bezpieczeństwa przed wysłaniem",
                    len(rows), started_at, batch_id,
                ),
            )
        if not rows:
            raise BatchError("Brak produktów gotowych do operacji.")

        for start in range(0, len(rows), PUBLISH_CHUNK_SIZE):
            chunk_rows = rows[start:start + PUBLISH_CHUNK_SIZE]
            products = [_decode_product(row) for row in chunk_rows]
            ids = [product["product_id"] for product in products]
            with _connect() as conn:
                conn.execute(
                    "UPDATE batches SET current_product=?, message=?, updated_at=? WHERE id=?",
                    (", ".join(ids[:5]), "Odczyt danych i tworzenie kopii bezpieczeństwa", _utcnow(), batch_id),
                )
            live_before = client.get_products(ids)
            if len(live_before) != len(ids):
                raise BatchError("Odczyt kontrolny Sky-Shop nie zwrócił wszystkich produktów.")
            if not rollback:
                with _connect() as conn:
                    for product in products:
                        backup = _live_content(live_before[product["product_id"]])
                        conn.execute(
                            "UPDATE batch_products SET backup_json=COALESCE(backup_json, ?) WHERE batch_id=? AND product_id=?",
                            (json.dumps(backup, ensure_ascii=False), batch_id, product["product_id"]),
                        )
            xml = build_update_xml(products, "backup" if rollback else "content")
            response = client.update_products(xml)
            if not _update_response_succeeded(response, len(products)):
                raise BatchError(f"Sky-Shop odrzucił partię: {json.dumps(response, ensure_ascii=False)[:500]}")
            with _connect() as conn:
                conn.execute(
                    "UPDATE batches SET message='Weryfikacja danych po zapisie', updated_at=? WHERE id=?",
                    (_utcnow(), batch_id),
                )
            live_after = client.get_products(ids)
            for chunk_index, product in enumerate(products, start=1):
                expected = product["backup"] if rollback else product["content"]
                actual_item = live_after.get(product["product_id"])
                differences = (
                    ["brak produktu w odczycie kontrolnym"]
                    if actual_item is None
                    else _content_differences(expected, _live_content(actual_item))
                )
                commerce_changed = actual_item is not None and (
                    _invariant_hash(live_before[product["product_id"]]) != _invariant_hash(actual_item)
                )
                if commerce_changed:
                    differences.append("dane handlowe produktu")
                verified = not differences
                error = "" if verified else "Odczyt po zapisie różni się w polach: " + ", ".join(differences) + "."
                with _connect() as conn:
                    conn.execute(
                        "UPDATE batch_products SET status=?, approved=?, error=?, updated_at=? WHERE batch_id=? AND product_id=?",
                        (
                            "rolled_back" if rollback and verified else "verified" if verified else "failed",
                            0 if rollback else product["approved"], error,
                            _utcnow(), batch_id, product["product_id"],
                        ),
                    )
                    conn.execute(
                        "UPDATE batches SET operation_done=?, current_product=?, updated_at=? WHERE id=?",
                        (start + chunk_index, product["name"], _utcnow(), batch_id),
                    )
        with _connect() as conn:
            failed_rows = conn.execute(
                "SELECT product_id, name, error FROM batch_products WHERE batch_id=? AND status='failed' "
                "ORDER BY CAST(product_id AS INTEGER)",
                (batch_id,),
            ).fetchall()
            failed = len(failed_rows)
            final_status = "completed_with_errors" if failed else "rolled_back" if rollback else "completed"
            message = (
                _publish_failure_message(failed_rows)
                if failed else "Zapis i odczyt kontrolny zakończone poprawnie."
            )
            conn.execute(
                "UPDATE batches SET status=?, updated_at=?, message=?, current_product='' WHERE id=?",
                (final_status, _utcnow(), message, batch_id),
            )
    except Exception as exc:
        logger.exception("Batch %s failed", action)
        with _connect() as conn:
            conn.execute("UPDATE batches SET status='failed', updated_at=?, message=? WHERE id=?", (_utcnow(), str(exc), batch_id))
    finally:
        with _jobs_lock:
            _running_jobs.discard((batch_id, action))


def start_publish(batch_id: str, rollback: bool = False) -> dict[str, str]:
    action = "rollback" if rollback else "publish"
    SkyShopClient()  # Fail before starting a background job when credentials are absent.
    with _connect() as conn:
        batch_row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not batch_row:
            raise BatchError("Nie znaleziono partii.")
        ready = conn.execute(
            "SELECT COUNT(*) FROM batch_products WHERE batch_id=? AND "
            + ("backup_json IS NOT NULL" if rollback else "status IN ('approved', 'failed') AND approved=1"),
            (batch_id,),
        ).fetchone()[0]
    if not ready:
        raise BatchError("Brak produktów gotowych do operacji.")
    key = (batch_id, action)
    with _jobs_lock:
        if key in _running_jobs:
            raise BatchError("Ta operacja już trwa.")
        if batch_row["status"] in ACTIVE_OPERATION_STATUSES and not _operation_is_stale(batch_row):
            raise BatchError("Ta operacja już trwa.")
        _running_jobs.add(key)
    threading.Thread(target=_run_publish, args=(batch_id, rollback), daemon=True).start()
    return {"status": "started", "action": action}
