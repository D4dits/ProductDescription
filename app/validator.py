import os
import re
import json
from pathlib import Path
from app.logger import logger
from app.config import OUTPUT_DIR

# Forbidden phrases
FORBIDDEN_PHRASES = [
    "najlepsza gra na rynku",
    "gwarantowana premiera",
    "najtańsza oferta",
    "hit sprzedaży",
]

# Source type priorities
SOURCE_PRIORITY = [
    "publisher",
    "official",
    "distributor",
    "manual_pdf",
    "bgg",
    "shop",
    "review",
    "other"
]

def clean_text_for_similarity(text: str) -> str:
    """Normalize text by converting to lowercase and keeping only alphanumeric words."""
    if not text:
        return ""
    # Strip HTML tags
    text_no_html = re.sub(r"<[^>]*>", " ", text)
    # Lowercase and clean characters
    cleaned = re.sub(r"[^\w\s]", "", text_no_html.lower())
    return cleaned

def compute_jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate word-level Jaccard similarity between two texts."""
    words1 = set(clean_text_for_similarity(text1).split())
    words2 = set(clean_text_for_similarity(text2).split())
    
    if not words1 or not words2:
        return 0.0
        
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union)

def check_similarity_with_existing(new_description_html: str) -> tuple:
    """
    Check if the newly generated description is too similar to any previously generated descriptions.
    
    Returns:
        (is_too_similar: bool, max_similarity: float, file_path: str)
    """
    max_similarity = 0.0
    matching_file = ""
    
    try:
        # Search all JSON files in the output directory
        json_files = list(OUTPUT_DIR.glob("*.json"))
        
        for file_path in json_files:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                old_html = data.get("extended_description_html", "")
                
                if old_html:
                    sim = compute_jaccard_similarity(new_description_html, old_html)
                    if sim > max_similarity:
                        max_similarity = sim
                        matching_file = file_path.name
                        
        is_too_similar = max_similarity > 0.70
        return is_too_similar, max_similarity, matching_file
        
    except Exception as e:
        logger.error(f"Error checking text similarity: {e}")
        return False, 0.0, ""

def resolve_facts_conflicts(sources_analysis: list, user_inputs: dict = None) -> tuple:
    """
    Resolves data conflicts between different sources using priority rules.
    
    Priority:
    1. User inputs (explicitly entered by user)
    2. Publisher (official/publisher page)
    3. Distributor (Polish distributor / Polish publisher)
    4. Manual PDF
    5. BGG (BoardGameGeek)
    6. Shop / Review / Other
    
    Returns:
        (resolved_info: dict, resolved_sources: list, warnings: list)
    """
    user_inputs = user_inputs or {}
    resolved_info = {}
    warnings = []
    
    # 1. Structure the facts by source type
    sources_by_type = {t: [] for t in SOURCE_PRIORITY}
    
    # Let's map facts to source URLs for validation checks
    fact_sources = {
        "publisher": None,
        "designer": None,
        "illustrator": None,
        "players": None,
        "age": None,
        "play_time": None,
        "edition_language": None,
        "manual_language": None,
        "release_date": None,
        "box_contents": None,
        "instruction_pdf": None
    }
    
    for src in sources_analysis:
        url = src.get("url")
        s_type = src.get("source_type", "other")
        facts = src.get("facts", {})
        
        if s_type not in sources_by_type:
            s_type = "other"
            
        sources_by_type[s_type].append({"url": url, "facts": facts})
        
    # Helper to resolve field value based on priority
    def resolve_field(field_name: str, user_override_val: str = None):
        # 1. User input override
        if user_override_val:
            fact_sources[field_name] = "user_input"
            return user_override_val
            
        # 2. Check sources in priority order
        for s_type in SOURCE_PRIORITY:
            for item in sources_by_type[s_type]:
                val = item["facts"].get(field_name)
                if val: # If value is not None, not empty string, and not empty list
                    fact_sources[field_name] = item["url"]
                    return val
        return ""

    # Resolve each field
    resolved_info["publisher"] = resolve_field("publisher", user_inputs.get("publisher"))
    resolved_info["designer"] = resolve_field("designer")
    resolved_info["illustrator"] = resolve_field("illustrator")
    resolved_info["players"] = resolve_field("players")
    resolved_info["age"] = resolve_field("age")
    resolved_info["play_time"] = resolve_field("play_time")
    resolved_info["edition_language"] = resolve_field("edition_language", user_inputs.get("edition_language"))
    resolved_info["manual_language"] = resolve_field("manual_language", user_inputs.get("manual_language"))
    
    # Release date and Preorder checks
    is_preorder = user_inputs.get("is_preorder", False)
    release_date_note = user_inputs.get("release_date_note", "")
    
    resolved_release = resolve_field("release_date", release_date_note)
    resolved_info["release_date"] = resolved_release
    
    # Box contents: pick the longest/most complete list among sources, or use user input
    box_contents = user_inputs.get("box_contents", [])
    if not box_contents:
        max_len = 0
        longest_contents = []
        best_source_url = None
        
        for s_type in SOURCE_PRIORITY:
            for item in sources_by_type[s_type]:
                contents = item["facts"].get("box_contents", [])
                if contents and len(contents) > max_len:
                    max_len = len(contents)
                    longest_contents = contents
                    best_source_url = item["url"]
                    
        if longest_contents:
            box_contents = longest_contents
            fact_sources["box_contents"] = best_source_url
    else:
        fact_sources["box_contents"] = "user_input"
        
    resolved_info["box_contents"] = box_contents
    
    # Instruction PDF
    resolved_info["instruction_pdf"] = resolve_field("instruction_pdf", user_inputs.get("manual_link"))

    # Generate BGG stats comparison / warnings if there is a conflict
    # e.g., if publisher has age = 8+, and BGG has age = 10+, warn the user
    for field_name in ["players", "age", "play_time"]:
        vals_found = {}
        for s_type in SOURCE_PRIORITY:
            for item in sources_by_type[s_type]:
                val = item["facts"].get(field_name)
                if val:
                    vals_found[s_type] = (val, item["url"])
                    
        if len(set(v[0] for v in vals_found.values())) > 1:
            conflict_details = ", ".join([f"{k}: {v[0]}" for k, v in vals_found.items()])
            warnings.append(
                f"Konflikt danych dla '{field_name}'. Wykryto różne wartości: {conflict_details}. "
                f"Wybrano wartość z najwyższego priorytetu: {resolved_info[field_name]}."
            )
            
    # Warnings for missing key data
    if not resolved_info["players"]:
        warnings.append("Brak potwierdzonych danych dotyczących liczby graczy.")
    elif not fact_sources["players"]:
        warnings.append("Dane o liczbie graczy nie posiadają zweryfikowanego źródła URL.")
        
    if not resolved_info["age"]:
        warnings.append("Brak potwierdzonych danych dotyczących zalecanego wieku.")
    elif not fact_sources["age"]:
        warnings.append("Dane o zalecanym wieku nie posiadają zweryfikowanego źródła URL.")
        
    if not resolved_info["play_time"]:
        warnings.append("Brak potwierdzonych danych dotyczących czasu rozgrywki.")
    elif not fact_sources["play_time"]:
        warnings.append("Dane o czasie gry nie posiadają zweryfikowanego źródła URL.")

    if is_preorder and not resolved_info["release_date"]:
        warnings.append("Gra oznaczona jako przedsprzedaż, ale nie znaleziono/nie podano daty premiery.")

    # Structure sources list for final JSON output
    formatted_sources = []
    for src in sources_analysis:
        url = src.get("url")
        s_type = src.get("source_type")
        facts = src.get("facts", {})
        
        # Build list of facts found
        facts_found = []
        for k, v in facts.items():
            if v:
                if isinstance(v, list):
                    facts_found.append(f"{k}: {len(v)} elementów")
                else:
                    facts_found.append(f"{k}: {v}")
                    
        formatted_sources.append({
            "url": url,
            "title": src.get("title", url),
            "source_type": s_type,
            "facts_found": facts_found
        })

    return resolved_info, formatted_sources, warnings, fact_sources

def validate_generated_content(
    short_desc: str,
    meta_desc: str,
    seo_title: str,
    html_desc: str,
    is_preorder: bool,
    additional_info: dict,
    fact_sources: dict
) -> list:
    """
    Validates final descriptions and metadata against business requirements.
    
    Returns:
        List of warning strings. Empty if all checks pass.
    """
    warnings = []
    
    # 1. Compare short description and meta description
    if short_desc and meta_desc and short_desc.strip() == meta_desc.strip():
        warnings.append("Opis skrócony jest identyczny z meta opisem.")
        
    # 2. Check meta description length
    if meta_desc:
        meta_len = len(meta_desc)
        if meta_len < 130 or meta_len > 170:
            warnings.append(f"Meta opis ma długość {meta_len} znaków (zalecane: 140-160 znaków).")
            
    # 3. Check SEO Title
    if not seo_title:
        warnings.append("Tytuł SEO jest pusty.")
    elif len(seo_title) > 65:
        warnings.append(f"Tytuł SEO jest długi ({len(seo_title)} znaków). Zalecane maksymalnie ok. 60 znaków.")
        
    # 4. Check HTML sections
    required_sections = {
        r"<h[23][^>]*>\s*Krótko o grze\s*</h[23]>": "Krótko o grze",
        r"<h[23][^>]*>\s*Na czym polega rozgrywka\?\s*</h[23]>": "Na czym polega rozgrywka?",
        r"<h[23][^>]*>\s*Dlaczego warto\?\s*</h[23]>": "Dlaczego warto?",
        r"<h[23][^>]*>\s*Dla kogo będzie dobra\?\s*</h[23]>": "Dla kogo będzie dobra?",
        r"<h[23][^>]*>\s*Zawartość pudełka:\s*</h[23]>": "Zawartość pudełka:",
        r"<h[23][^>]*>\s*Dodatkowe informacje:\s*</h[23]>": "Dodatkowe informacje:"
    }
    
    for regex, section_name in required_sections.items():
        if not re.search(regex, html_desc, re.IGNORECASE):
            # "Dla kogo będzie dobra" is optional according to requirements ("Tylko jeśli wynika to z charakteru gry")
            # We can log this but not necessarily warn unless it's a strict requirement.
            # Let's check requirements: "Dla kogo będzie dobra? - Opis grupy docelowej ... Tylko jeśli wynika to z charakteru gry."
            if section_name != "Dla kogo będzie dobra?":
                warnings.append(f"HTML nie zawiera wymaganej sekcji: '{section_name}'.")

    # 5. Check preorder rules
    if is_preorder:
        if "Orientacyjna premiera" not in html_desc:
            warnings.append("Produkt w przedsprzedaży, ale w opisie HTML brakuje pozycji 'Orientacyjna premiera'.")
        if not seo_title.startswith("Przedsprzedaż"):
            warnings.append("Produkt w przedsprzedaży, ale tytuł SEO nie rozpoczyna się od słowa 'Przedsprzedaż'.")
            
    # 6. Check for forbidden phrases
    combined_texts = f"{short_desc} {meta_desc} {seo_title} {html_desc}".lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in combined_texts:
            # "hit sprzedaży" is allowed ONLY if there is a source (checked elsewhere or warn)
            if phrase == "hit sprzedaży":
                warnings.append("Wykryto frazę 'hit sprzedaży' - upewnij się, że posiadasz dowód w źródłach.")
            else:
                warnings.append(f"Tekst zawiera niedozwoloną frazę: '{phrase}'.")
                
    # 7. Check source URLs for numeric fields
    for field in ["players", "age", "play_time"]:
        val = additional_info.get(field)
        source = fact_sources.get(field)
        if val and (not source or source == "user_input" and not additional_info.get(field)):
            warnings.append(f"Parametr '{field}' nie ma udokumentowanego źródła URL.")

    return warnings
