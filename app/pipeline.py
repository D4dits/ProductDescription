from app.config import SCRAPE_PAGES_LIMIT
from app.logger import logger
from app.bgg import fetch_bgg_data
from app.search import search_web_links, get_combined_search_queries
from app.scraper import scrape_page
from app.extractor import extract_facts
from app.validator import resolve_facts_conflicts, validate_generated_content
from app.generator import generate_descriptions
from app.exporter import export_results

def _collect_sources(user_inputs: dict) -> dict:
    game_name = user_inputs.get("product_name", "").strip()
    if not game_name:
        raise ValueError("Nazwa produktu jest wymagana.")

    # 1. Automatic Preorder Detection
    # Jeśli nazwa produktu zaczyna się od "Przedsprzedaż", automatycznie ustaw tryb przedsprzedaży
    is_preorder = user_inputs.get("is_preorder", False)
    if game_name.lower().startswith("przedsprzedaz") or game_name.lower().startswith("przedsprzedaż"):
        is_preorder = True
        user_inputs["is_preorder"] = True
        logger.info("Auto-detected preorder mode from product name.")
        
    # 2. Query BGG
    bgg_data = {}
    bgg_url = ""
    # Try searching by original title if available, otherwise by name
    search_term = user_inputs.get("original_title") or game_name
    try:
        bgg_data = fetch_bgg_data(search_term)
        if bgg_data:
            bgg_url = bgg_data.get("url", "")
    except Exception as e:
        logger.error(f"Error querying BGG: {e}")
        
    # 3. Gather Web Links
    queries = get_combined_search_queries(
        game_name=game_name,
        publisher=user_inputs.get("publisher")
    )
    
    found_urls = []
    # If BGG URL is found, prioritize it
    if bgg_url:
        found_urls.append({"url": bgg_url, "title": f"BGG - {game_name}", "source_type": "bgg"})
        
    # If user provided a manual official link or manual link
    if user_inputs.get("official_link"):
        found_urls.append({"url": user_inputs.get("official_link"), "title": "Użytkownik - Oficjalna strona", "source_type": "official"})
    if user_inputs.get("manual_link"):
        found_urls.append({"url": user_inputs.get("manual_link"), "title": "Użytkownik - Instrukcja PDF", "source_type": "manual_pdf"})
        
    # Query DuckDuckGo for additional sources
    for query in queries:
        # Search links
        links = search_web_links(query, limit=3)
        for link in links:
            url = link["url"]
            # Deduplicate
            if not any(f["url"] == url for f in found_urls):
                source_type = "other"
                if url.lower().endswith(".pdf"):
                    source_type = "manual_pdf"
                elif "boardgamegeek.com" in url:
                    source_type = "bgg"
                elif "muduko" in url or "rebel" in url or "portalgames" in url or "phalanx" in url or "lacerta" in url or "foxgames" in url or "naszaksiegarnia" in url or "egmont" in url:
                    # Detect popular Polish publishers
                    source_type = "distributor"
                    
                found_urls.append({
                    "url": url,
                    "title": link["title"],
                    "source_type": source_type
                })
                
    # Limit number of pages to scrape
    scrape_limit = SCRAPE_PAGES_LIMIT
    urls_to_scrape = found_urls[:scrape_limit]
    logger.info(f"URLs queued for scraping (limit: {scrape_limit}): {[u['url'] for u in urls_to_scrape]}")
    
    # 4. Scrape the pages
    scraped_sources = []
    for u in urls_to_scrape:
        res = scrape_page(u["url"])
        if res and res.get("body") or res.get("is_pdf"):
            # Update title and source_type if they are better detected
            scraped_sources.append({
                "url": u["url"],
                "title": res.get("title") or u["title"],
                "source_type": u["source_type"],
                "body": res.get("body", "")
            })
            
    # Include BGG structured text in scraper output to help extractor
    if bgg_data and not any(s["url"] == bgg_url for s in scraped_sources):
        # If we didn't scrape BGG page but have details, simulate it
        scraped_sources.append({
            "url": bgg_url,
            "title": f"BoardGameGeek Data: {bgg_data.get('title')}",
            "source_type": "bgg",
            "body": (
                f"Tytuł: {bgg_data.get('title')}\n"
                f"Opis: {bgg_data.get('description')}\n"
                f"Liczba graczy: {bgg_data.get('players')}\n"
                f"Wiek: {bgg_data.get('age')}\n"
                f"Czas gry: {bgg_data.get('play_time')} minut\n"
                f"Wydawca: {', '.join(bgg_data.get('all_publishers', []))}\n"
                f"Projektant: {', '.join(bgg_data.get('all_designers', []))}\n"
                f"Ilustrator: {', '.join(bgg_data.get('all_illustrators', []))}\n"
            )
        })

    return {
        "game_name": game_name,
        "is_preorder": is_preorder,
        "bgg_data": bgg_data,
        "scraped_sources": scraped_sources,
        "found_urls": found_urls,
    }

def build_codex_prompt_package(user_inputs: dict) -> dict:
    """
    Collects sources and returns a copy-ready prompt for Codex/ChatGPT.
    This mode avoids any paid LLM API call inside the application.
    """
    logger.info(f"Starting Codex prompt package for game: '{user_inputs.get('product_name', '').strip()}'")
    collected = _collect_sources(user_inputs)
    game_name = collected["game_name"]
    is_preorder = collected["is_preorder"]
    scraped_sources = collected["scraped_sources"]

    sources_text = []
    for idx, src in enumerate(scraped_sources, start=1):
        body = (src.get("body") or "")[:6000]
        sources_text.append(
            f"### ŹRÓDŁO {idx}\n"
            f"- URL: {src.get('url')}\n"
            f"- Tytuł: {src.get('title')}\n"
            f"- Typ źródła: {src.get('source_type')}\n"
            f"- Treść:\n{body or '[PDF lub źródło bez pobranej treści tekstowej]'}\n"
        )

    expected_json = """{
  "product_name": "Nazwa produktu w sklepie",
  "original_title": "Oryginalny tytuł lub pusty string",
  "is_preorder": false,
  "release_date_note": "",
  "short_description": "1-2 zdania, max 300 znaków",
  "seo_title": "max ok. 60 znaków",
  "meta_description": "140-160 znaków",
  "tags": ["tag1", "tag2"],
  "extended_description_html": "<h2>Krótko o grze</h2>...",
  "box_contents": ["element 1", "element 2"],
  "additional_info": {
    "publisher": "",
    "designer": "",
    "illustrator": "",
    "edition_language": "polski",
    "manual_language": "polski",
    "players": "",
    "age": "",
    "play_time": "",
    "instruction_pdf": ""
  },
  "sources": [
    {
      "url": "https://...",
      "title": "Tytuł źródła",
      "source_type": "publisher|distributor|manual_pdf|bgg|shop|review|official|other",
      "facts_found": ["players: 1-4", "age: 12+"]
    }
  ],
  "warnings": []
}"""

    prompt = f"""Jesteś Codexem pracującym nad lokalnym projektem generatora opisów produktów graszki.pl.

Przygotuj kompletny JSON produktu dla gry planszowej: {game_name}

Parametry użytkownika:
- Nazwa produktu: {game_name}
- Oryginalny tytuł: {user_inputs.get('original_title') or ''}
- Sugerowany wydawca: {user_inputs.get('publisher') or ''}
- Czy przedsprzedaż: {'Tak' if is_preorder else 'Nie'}
- Orientacyjna premiera: {user_inputs.get('release_date_note') or ''}
- Kategoria: {user_inputs.get('category') or ''}
- Grupa docelowa: {user_inputs.get('target_audience') or ''}
- Link oficjalny użytkownika: {user_inputs.get('official_link') or ''}
- Link instrukcji użytkownika: {user_inputs.get('manual_link') or ''}
- Ton: {user_inputs.get('tone_preference') or 'standard'}

Zasady:
1. Pisz wyłącznie po polsku.
2. Bazuj tylko na źródłach i parametrach poniżej. Nie wymyślaj faktów technicznych.
3. Rozstrzygaj konflikty według priorytetu: oficjalny wydawca/dystrybutor, instrukcja PDF, BGG, sklepy, recenzje.
4. Opis HTML ma zawierać sekcje: <h2>Krótko o grze</h2>, <h2>Na czym polega rozgrywka?</h2>, <h2>Dlaczego warto?</h2>, <h2>Zawartość pudełka:</h2>, <h2>Dodatkowe informacje:</h2>. Sekcja <h2>Dla kogo będzie dobra?</h2> jest opcjonalna, gdy pasuje do produktu.
5. Nie używaj agresywnych obietnic typu "najlepsza gra na rynku", "gwarantowana premiera", "najtańsza oferta".
6. Jeśli brakuje ważnych danych, zostaw pusty string i dodaj ostrzeżenie w polu warnings.
7. Odpowiedz wyłącznie poprawnym JSON-em, bez markdown i bez komentarzy.

Wymagana struktura JSON:
{expected_json}

Źródła:
{chr(10).join(sources_text) if sources_text else '[Nie udało się pobrać źródeł. Oprzyj się tylko na parametrach użytkownika i oznacz braki w warnings.]'}
"""

    return {
        "mode": "codex_prompt",
        "product_name": game_name,
        "prompt": prompt,
        "sources": [
            {
                "url": src.get("url"),
                "title": src.get("title"),
                "source_type": src.get("source_type"),
                "facts_found": [],
            }
            for src in scraped_sources
        ],
        "warnings": [] if scraped_sources else ["Nie udało się pobrać żadnych źródeł tekstowych."],
    }

def run_generation_pipeline(user_inputs: dict) -> dict:
    """
    Orchestrates the entire data gathering, verification, 
    generation, validation, and export process.
    """
    logger.info(f"Starting pipeline for game: '{user_inputs.get('product_name', '').strip()}'")
    collected = _collect_sources(user_inputs)
    game_name = collected["game_name"]
    is_preorder = collected["is_preorder"]
    scraped_sources = collected["scraped_sources"]

    # 5. Extract facts via LLM
    extracted_raw = extract_facts(
        game_name=game_name,
        sources=scraped_sources,
        user_inputs=user_inputs
    )
    
    # 6. Reconcile facts & Resolve conflicts
    resolved_facts, formatted_sources, conflict_warnings, fact_sources = resolve_facts_conflicts(
        sources_analysis=extracted_raw.get("sources_analysis", []),
        user_inputs=user_inputs
    )
    
    # 7. Generate texts & HTML
    generated = generate_descriptions(
        game_name=game_name,
        resolved_facts=resolved_facts,
        user_inputs=user_inputs
    )
    
    # 8. Business Validation Checks
    validation_warnings = validate_generated_content(
        short_desc=generated.get("short_description", ""),
        meta_desc=generated.get("meta_description", ""),
        seo_title=generated.get("seo_title", ""),
        html_desc=generated.get("extended_description_html", ""),
        is_preorder=is_preorder,
        additional_info=resolved_facts,
        fact_sources=fact_sources
    )
    
    # Combine warnings
    all_warnings = list(set(conflict_warnings + validation_warnings))
    
    # 9. Format final data structure
    product_name_final = game_name
    if is_preorder and not (game_name.lower().startswith("przedsprzedaz") or game_name.lower().startswith("przedsprzedaż")):
        product_name_final = f"Przedsprzedaż {game_name}"
        
    final_output = {
        "product_name": product_name_final,
        "original_title": user_inputs.get("original_title") or resolved_facts.get("original_title", ""),
        "is_preorder": is_preorder,
        "release_date_note": resolved_facts.get("release_date", "") if is_preorder else "",
        "short_description": generated.get("short_description", ""),
        "seo_title": generated.get("seo_title", ""),
        "meta_description": generated.get("meta_description", ""),
        "tags": generated.get("tags", []),
        "extended_description_html": generated.get("extended_description_html", ""),
        "box_contents": resolved_facts.get("box_contents", []),
        "additional_info": {
            "publisher": resolved_facts.get("publisher", ""),
            "designer": resolved_facts.get("designer", ""),
            "illustrator": resolved_facts.get("illustrator", ""),
            "edition_language": resolved_facts.get("edition_language") or user_inputs.get("edition_language") or "polski",
            "manual_language": resolved_facts.get("manual_language") or user_inputs.get("manual_language") or "polski",
            "players": resolved_facts.get("players", ""),
            "age": resolved_facts.get("age", ""),
            "play_time": resolved_facts.get("play_time", ""),
            "instruction_pdf": resolved_facts.get("instruction_pdf", "")
        },
        "sources": formatted_sources,
        "warnings": all_warnings
    }
    
    # 10. Export results to output/ directory
    export_results(final_output)
    
    return final_output
