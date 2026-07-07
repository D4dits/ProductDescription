import hashlib
import io
import json
import os
import re
from urllib.parse import parse_qs, unquote, urlparse
from bs4 import BeautifulSoup
import requests
from app.config import CACHE_DIR, PDF_CACHE_DIR, SCRAPE_TIMEOUT_SECONDS
from app.logger import logger

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
}

def get_url_hash(url: str) -> str:
    """Generate a unique MD5 hash for the URL to use as filename in cache."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def load_from_cache(url: str) -> dict:
    """Load cached page data from disk if it exists."""
    cache_file = CACHE_DIR / f"{get_url_hash(url)}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                logger.info(f"Cache hit for URL: {url}")
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read cache for {url}: {e}")
    return None

def save_to_cache(url: str, data: dict):
    """Save page data to cache on disk."""
    cache_file = CACHE_DIR / f"{get_url_hash(url)}.json"
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved URL to cache: {url}")
    except Exception as e:
        logger.warning(f"Failed to write cache for {url}: {e}")

def is_google_drive_url(url: str) -> bool:
    """Return True for Google Drive file/share links."""
    parsed = urlparse(url)
    return parsed.netloc.lower() in {"drive.google.com", "docs.google.com"}

def get_google_drive_file_id(url: str) -> str:
    """Extract Google Drive file id from common sharing URL formats."""
    parsed = urlparse(url)
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    if query_id:
        return query_id

    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        return match.group(1)

    return ""

def get_google_drive_download_url(url: str) -> str:
    """Convert a Google Drive sharing URL into a direct download endpoint."""
    file_id = get_google_drive_file_id(url)
    if not file_id:
        return url
    return f"https://drive.google.com/uc?export=download&id={file_id}"

def is_stale_google_drive_cache(data: dict) -> bool:
    """Detect previously cached Drive loading pages that did not contain PDF text."""
    if not data:
        return False
    body = (data.get("body") or "").lower()
    return (
        is_google_drive_url(data.get("url", ""))
        and not data.get("pdf_text_extracted")
        and "dysk google" in body
        and "wczytuję" in body
    )

def get_filename_from_response(response: requests.Response, fallback_url: str) -> str:
    content_disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?", content_disposition)
    if match:
        filename = match.group(1) or match.group(2)
        return unquote(filename)
    parsed = urlparse(fallback_url)
    return os.path.basename(parsed.path) or fallback_url.split("/")[-1] or "instruction.pdf"

def sanitize_filename(filename: str) -> str:
    filename = unquote(filename or "instruction.pdf").strip()
    filename = re.sub(r"[^\w.\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]+", "_", filename)
    filename = re.sub(r"\s+", "_", filename).strip("._")
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename or 'instruction'}.pdf"
    return filename

def save_pdf_to_cache(url: str, filename: str, pdf_bytes: bytes) -> str:
    safe_name = sanitize_filename(filename)
    path = PDF_CACHE_DIR / f"{get_url_hash(url)}_{safe_name}"
    try:
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        return str(path.resolve())
    except Exception as e:
        logger.warning(f"Failed to write PDF cache for {url}: {e}")
        return ""

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract readable text from a PDF file using pypdf when available."""
    if not pdf_bytes:
        return ""

    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("Cannot extract PDF text because dependency 'pypdf' is not installed.")
        return ""

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_texts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            if text.strip():
                page_texts.append(text.strip())
        return "\n\n".join(page_texts).strip()
    except Exception as e:
        logger.warning(f"Failed to extract PDF text: {e}")
        return ""

def clean_pdf_text(text: str) -> str:
    """Remove common PDF extraction artifacts while preserving useful line breaks."""
    if not text:
        return ""

    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ".smcp" in line:
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        line = re.sub(r"/[A-Za-z]+(?:acute|slash)?\.smcp", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def scrape_pdf(url: str, response: requests.Response | None = None) -> dict:
    """Download and extract text from a PDF or Google Drive PDF link."""
    request_url = get_google_drive_download_url(url) if is_google_drive_url(url) else url
    try:
        if response is None:
            response = requests.get(request_url, headers=HEADERS, timeout=SCRAPE_TIMEOUT_SECONDS)

        content_type = response.headers.get("Content-Type", "").lower()
        content = response.content or b""
        looks_like_pdf = content.startswith(b"%PDF") or "application/pdf" in content_type

        if not looks_like_pdf:
            logger.warning(f"Expected PDF but received {content_type or 'unknown content type'} for {url}")
            return {
                "url": url,
                "title": get_filename_from_response(response, url),
                "body": "",
                "is_pdf": True,
                "pdf_text_extracted": False,
                "status_code": response.status_code,
                "error_msg": "Nie udało się pobrać pliku PDF z podanego linku."
            }

        filename = get_filename_from_response(response, url)
        local_pdf_path = save_pdf_to_cache(url, filename, content)
        text = clean_pdf_text(extract_pdf_text(content))
        data = {
            "url": url,
            "title": filename,
            "body": text,
            "is_pdf": True,
            "pdf_text_extracted": bool(text),
            "local_pdf_path": local_pdf_path,
            "status_code": response.status_code
        }
        save_to_cache(url, data)
        return data
    except Exception as e:
        logger.error(f"Error scraping PDF {url}: {e}")
        return {
            "url": url,
            "title": "PDF",
            "body": "",
            "is_pdf": True,
            "pdf_text_extracted": False,
            "status_code": 0,
            "error_msg": str(e)
        }

def clean_html(html_content: str) -> str:
    """
    Remove boilerplate elements (menu, header, footer, ads, cookies, etc.) 
    and return cleaned, human-readable text.
    """
    if not html_content:
        return ""
        
    soup = BeautifulSoup(html_content, "html.parser")
    
    # List of tags to completely remove
    tags_to_remove = [
        "script", "style", "nav", "header", "footer", "aside", 
        "form", "noscript", "iframe", "svg", "button", "input"
    ]
    for tag in soup.find_all(tags_to_remove):
        tag.decompose()
        
    # List of patterns in class/id to remove boilerplate
    boilerplate_patterns = [
        "menu", "nav", "footer", "cookie", "banner", "popup", 
        "newsletter", "social", "share", "widget", "sidebar", 
        "ad-", "header", "cart", "basket", "login", "register",
        "search", "promo", "discount"
    ]
    
    tags_to_decompose = []
    for tag in soup.find_all(True):  # True finds all tags
        if not tag or not hasattr(tag, "attrs") or tag.attrs is None:
            continue
            
        # Check class
        classes = tag.get("class", [])
        if isinstance(classes, str):
            classes = [classes]
        
        # Check id
        tag_id = tag.get("id", "") or ""
        
        # Determine if tag should be decomposed based on class or id patterns
        decompose_tag = False
        for pattern in boilerplate_patterns:
            if any(pattern in c.lower() for c in classes) or pattern in tag_id.lower():
                decompose_tag = True
                break
                
        if decompose_tag:
            tags_to_decompose.append(tag)
            
    # Decompose collected tags safely
    for tag in tags_to_decompose:
        if tag and tag.parent:
            tag.decompose()
            
    # Extract text from remaining HTML
    # We replace tag endings with newlines to keep block formatting
    for br in soup.find_all("br"):
        if br and br.parent:
            br.replace_with("\n")
        
    text = soup.get_text(separator="\n")
    
    # Clean up whitespace
    lines = [line.strip() for line in text.splitlines()]
    # Remove empty lines
    cleaned_lines = [line for line in lines if line]
    
    return "\n".join(cleaned_lines)

def scrape_page(url: str, force_refresh: bool = False) -> dict:
    """
    Fetch, clean, and cache web page. 
    If url is a PDF, returns a dict marked as PDF, with no body content.
    """
    if not url:
        return {}
        
    # Check cache first
    if not force_refresh:
        cached_data = load_from_cache(url)
        if cached_data:
            if is_stale_google_drive_cache(cached_data):
                logger.info(f"Ignoring stale Google Drive loading-page cache for URL: {url}")
            elif cached_data.get("is_pdf") and not cached_data.get("local_pdf_path"):
                logger.info(f"Refreshing cached PDF without local file path for URL: {url}")
                return scrape_pdf(url)
            else:
                if cached_data.get("is_pdf") and cached_data.get("body"):
                    cleaned_body = clean_pdf_text(cached_data.get("body", ""))
                    if cleaned_body != cached_data.get("body"):
                        cached_data["body"] = cleaned_body
                        save_to_cache(url, cached_data)
                return cached_data

    if url.lower().endswith(".pdf") or is_google_drive_url(url):
        return scrape_pdf(url)
            
    # Download page
    try:
        logger.info(f"Scraping page: {url}")
        response = requests.get(url, headers=HEADERS, timeout=SCRAPE_TIMEOUT_SECONDS)
        
        # If response is a PDF, don't read HTML
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type:
            return scrape_pdf(url, response=response)
            
        if response.status_code != 200:
            logger.warning(f"Failed to fetch {url}, status code: {response.status_code}")
            return {
                "url": url,
                "title": "Error",
                "body": "",
                "is_pdf": False,
                "status_code": response.status_code
            }
            
        # Parse title safely
        soup = BeautifulSoup(response.text, "html.parser")
        title = url
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            
        # Clean text
        cleaned_text = clean_html(response.text)
        
        data = {
            "url": url,
            "title": title,
            "body": cleaned_text,
            "is_pdf": False,
            "status_code": response.status_code
        }
        
        save_to_cache(url, data)
        return data
        
    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")
        return {
            "url": url,
            "title": "Error",
            "body": "",
            "is_pdf": False,
            "status_code": 0,
            "error_msg": str(e)
        }
