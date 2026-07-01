import hashlib
import json
import os
from bs4 import BeautifulSoup
import requests
from app.config import CACHE_DIR, SCRAPE_TIMEOUT_SECONDS
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
        
    # If it is a PDF manual link, return immediately
    if url.lower().endswith(".pdf"):
        return {
            "url": url,
            "title": url.split("/")[-1],
            "body": "",
            "is_pdf": True,
            "status_code": 200
        }
        
    # Check cache first
    if not force_refresh:
        cached_data = load_from_cache(url)
        if cached_data:
            return cached_data
            
    # Download page
    try:
        logger.info(f"Scraping page: {url}")
        response = requests.get(url, headers=HEADERS, timeout=SCRAPE_TIMEOUT_SECONDS)
        
        # If response is a PDF, don't read HTML
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type:
            data = {
                "url": url,
                "title": url.split("/")[-1],
                "body": "",
                "is_pdf": True,
                "status_code": response.status_code
            }
            save_to_cache(url, data)
            return data
            
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
