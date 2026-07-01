import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from app.logger import logger
from app.config import SCRAPE_TIMEOUT_SECONDS

# Headers to make request look like standard browser
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
}

def search_web_links(query: str, limit: int = 5) -> list:
    """
    Search DuckDuckGo HTML interface for a given query and return list of results.
    
    Returns:
        List of dicts: [{"title": str, "url": str}]
    """
    results = []
    try:
        # URL encode query
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        logger.info(f"Searching DuckDuckGo for: '{query}'")
        response = requests.get(url, headers=HEADERS, timeout=SCRAPE_TIMEOUT_SECONDS)
        
        if response.status_code != 200:
            logger.warning(f"DuckDuckGo search failed with status code: {response.status_code}")
            return results
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # In DuckDuckGo HTML, search results are represented by elements with class 'result__body'
        result_elements = soup.find_all("div", class_="result__body")
        
        for element in result_elements:
            if len(results) >= limit:
                break
                
            title_elem = element.find("a", class_="result__url")
            snippet_elem = element.find("a", class_="result__snippet")
            
            # If result__url class isn't directly on 'a', look inside title elements
            if not title_elem:
                title_elem = element.find("h2", class_="result__title")
                if title_elem:
                    title_elem = title_elem.find("a")
            
            if not title_elem:
                continue
                
            raw_url = title_elem.get("href", "")
            title = title_elem.get_text(strip=True)
            
            # DuckDuckGo sometimes encodes URLs or routes them through ddg links, let's extract the actual URL
            # e.g. /l/?kh=-1&uddg=https%3A%2F%2Fboardgamegeek.com%2F...
            parsed_url = raw_url
            if "/l/?kh=" in raw_url or "uddg=" in raw_url:
                match = re.search(r"uddg=([^&]+)", raw_url)
                if match:
                    parsed_url = urllib.parse.unquote(match.group(1))
            
            # Exclude duckduckgo itself
            if "duckduckgo.com" in parsed_url:
                continue
                
            results.append({
                "title": title,
                "url": parsed_url
            })
            
        logger.info(f"Found {len(results)} links for query: '{query}'")
        
    except Exception as e:
        logger.error(f"Error while searching web links: {e}")
        
    return results

def get_combined_search_queries(game_name: str, publisher: str = None) -> list:
    """
    Generate different search queries to find the official publisher page, 
    general information, and instruction manuals in Polish.
    """
    queries = []
    
    # 1. General Polish search
    queries.append(f'"{game_name}" gra planszowa')
    
    # 2. Search with publisher if provided
    if publisher:
        queries.append(f'"{game_name}" "{publisher}" wydawca')
    else:
        queries.append(f'"{game_name}" wydawnictwo gra planszowa')
        
    # 3. PDF manual search
    queries.append(f'"{game_name}" instrukcja pdf pl')
    
    return queries
