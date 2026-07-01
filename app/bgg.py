import urllib.parse
import xml.etree.ElementTree as ET
import time
import requests
from app.logger import logger
from app.config import SCRAPE_TIMEOUT_SECONDS

BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search"
BGG_THING_URL = "https://boardgamegeek.com/xmlapi2/thing"
HEADERS = {
    "User-Agent": "graszki-generator/1.0 (local product description generator)",
    "Accept": "application/xml,text/xml,*/*",
}

def _get_bgg(url: str, params: dict):
    for attempt in range(3):
        response = requests.get(url, params=params, headers=HEADERS, timeout=SCRAPE_TIMEOUT_SECONDS)
        if response.status_code != 202:
            return response

        wait_seconds = attempt + 1
        logger.info(f"BGG returned 202 Accepted. Retrying in {wait_seconds}s...")
        time.sleep(wait_seconds)

    return response

def search_game_id(game_name: str) -> str:
    """
    Search BGG for a game name and return the BGG ID of the best match.
    """
    try:
        params = {"query": game_name, "type": "boardgame"}
        logger.info(f"Searching BGG ID for game: {game_name}")
        response = _get_bgg(BGG_SEARCH_URL, params=params)
        
        if response.status_code != 200:
            logger.warning(f"BGG search returned status code {response.status_code}")
            return None
            
        root = ET.fromstring(response.content)
        items = root.findall("item")
        
        if not items:
            logger.info(f"No BGG results found for query: {game_name}")
            return None
            
        # Try to find an exact match first
        for item in items:
            name_elem = item.find("name")
            if name_elem is not None and name_elem.get("value").lower() == game_name.lower():
                bgg_id = item.get("id")
                logger.info(f"Found exact match on BGG: {name_elem.get('value')} (ID: {bgg_id})")
                return bgg_id
                
        # If no exact match, return the first result
        first_id = items[0].get("id")
        first_name = items[0].find("name").get("value") if items[0].find("name") is not None else "Unknown"
        logger.info(f"Using first BGG search result: {first_name} (ID: {first_id})")
        return first_id
        
    except Exception as e:
        logger.error(f"Error searching BGG ID: {e}")
        return None

def get_game_details(bgg_id: str) -> dict:
    """
    Fetch game details from BGG XML API 2 for a specific BGG ID.
    """
    if not bgg_id:
        return {}
        
    try:
        params = {"id": bgg_id, "stats": 1}
        logger.info(f"Fetching BGG details for ID: {bgg_id}")
        response = _get_bgg(BGG_THING_URL, params=params)
        
        if response.status_code != 200:
            logger.warning(f"BGG thing details returned status code {response.status_code}")
            return {}
            
        root = ET.fromstring(response.content)
        item = root.find("item")
        
        if item is None:
            logger.warning(f"No item tag found in BGG response for ID: {bgg_id}")
            return {}
            
        # Names
        names = item.findall("name")
        primary_name = ""
        alternate_names = []
        for name in names:
            if name.get("type") == "primary":
                primary_name = name.get("value")
            else:
                alternate_names.append(name.get("value"))
                
        # Basic Stats
        description_elem = item.find("description")
        description = description_elem.text if description_elem is not None else ""
        
        year_elem = item.find("yearpublished")
        year = year_elem.get("value") if year_elem is not None else ""
        
        minplayers = item.find("minplayers").get("value") if item.find("minplayers") is not None else ""
        maxplayers = item.find("maxplayers").get("value") if item.find("maxplayers") is not None else ""
        
        minplaytime = item.find("minplaytime").get("value") if item.find("minplaytime") is not None else ""
        maxplaytime = item.find("maxplaytime").get("value") if item.find("maxplaytime") is not None else ""
        
        minage = item.find("minage").get("value") if item.find("minage") is not None else ""
        
        image_elem = item.find("image")
        image_url = image_elem.text if image_elem is not None else ""
        
        thumbnail_elem = item.find("thumbnail")
        thumbnail_url = thumbnail_elem.text if thumbnail_elem is not None else ""
        
        # Links: publisher, designer, artist, category, mechanic
        publishers = []
        designers = []
        artists = []
        categories = []
        
        for link in item.findall("link"):
            link_type = link.get("type")
            link_val = link.get("value")
            
            if link_type == "boardgamepublisher":
                publishers.append(link_val)
            elif link_type == "boardgamedesigner":
                designers.append(link_val)
            elif link_type == "boardgameartist":
                artists.append(link_val)
            elif link_type == "boardgamecategory":
                categories.append(link_val)
                
        # Parse players string, e.g., "2-4" or "2"
        players_str = ""
        if minplayers and maxplayers:
            if minplayers == maxplayers:
                players_str = minplayers
            else:
                players_str = f"{minplayers}-{maxplayers}"
                
        # Parse play time string, e.g., "30-60" or "45"
        time_str = ""
        if minplaytime and maxplaytime:
            if minplaytime == maxplaytime:
                time_str = minplaytime
            else:
                time_str = f"{minplaytime}-{maxplaytime}"
                
        # Parse age string, e.g., "10+"
        age_str = ""
        if minage and minage != "0":
            age_str = f"{minage}+"

        # Construct final dict
        bgg_data = {
            "bgg_id": bgg_id,
            "title": primary_name,
            "alternate_titles": alternate_names,
            "description": description,
            "year": year,
            "players": players_str,
            "age": age_str,
            "play_time": time_str,
            "publisher": publishers[0] if publishers else "",
            "all_publishers": publishers,
            "designer": designers[0] if designers else "",
            "all_designers": designers,
            "illustrator": artists[0] if artists else "",
            "all_illustrators": artists,
            "categories": categories,
            "image_url": image_url,
            "thumbnail_url": thumbnail_url,
            "url": f"https://boardgamegeek.com/boardgame/{bgg_id}"
        }
        
        return bgg_data
        
    except Exception as e:
        logger.error(f"Error fetching BGG details for ID {bgg_id}: {e}")
        return {}

def fetch_bgg_data(game_name: str) -> dict:
    """
    High-level entry point to search and fetch details from BGG for a game name.
    """
    bgg_id = search_game_id(game_name)
    if bgg_id:
        return get_game_details(bgg_id)
    return {}
