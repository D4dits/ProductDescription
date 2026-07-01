import json
from app.llm import generate_text, LLMError
from app.logger import logger
from app.json_utils import parse_llm_json

EXTRACTOR_SYSTEM_INSTRUCTION = """Jesteś ekspertem w dziedzinie gier planszowych i precyzyjnej ekstrakcji danych tekstowych.
Twoim zadaniem jest przeanalizowanie tekstów z różnych stron internetowych i wyodrębnienie z nich faktów technicznych oraz informacji o grze planszowej.

Dla każdego podanego źródła (URL) musisz określić jego typ (source_type) oraz wyodrębnić wyłącznie fakty potwierdzone w tekście tej konkretnej strony.

Typy źródeł (source_type):
- publisher: oficjalna strona wydawcy gry
- distributor: oficjalna strona polskiego dystrybutora / polskiego wydawcy
- bgg: strona BoardGameGeek
- manual_pdf: instrukcja obsługi w formacie PDF
- shop: sklepy internetowe
- review: recenzje, blogi
- official: inne oficjalne strony produktu
- other: pozostałe strony

Fakty do wyodrębnienia (wypełnij tylko te, które są wyraźnie podane w tekście danego źródła. Jeśli czegoś nie ma, pozostaw puste lub null):
1. publisher: wydawca gry (szczególnie wydawca polskiej edycji)
2. designer: projektant / autor gry
3. illustrator: ilustrator / autor grafik
4. players: liczba graczy (np. "2-4", "1-5", "2")
5. age: zalecany wiek (np. "8+", "14")
6. play_time: czas rozgrywki w minutach (np. "30-45", "90")
7. edition_language: język wydania (np. "polski", "angielski")
8. manual_language: język instrukcji w pudełku (np. "polski", "angielski")
9. release_date: orientacyjna data premiery / rok wydania (np. "Q3 2026", "2024")
10. box_contents: lista elementów w pudełku jako tablica stringów (np. ["1 plansza", "100 kart"])
11. instruction_pdf: link url do instrukcji PDF, jeśli został znaleziony na tej stronie

Zasady:
1. Nie wymyślaj żadnych danych. Jeśli źródło nie wspomina o danej informacji, ustaw wartość na null lub puste tablice.
2. Zwróć wynik jako poprawny obiekt JSON.
"""

EXTRACTOR_PROMPT_TEMPLATE = """Gra planszowa: {game_name}
Podane przez użytkownika informacje pomocnicze:
- Oryginalny tytuł: {original_title}
- Sugerowany wydawca: {suggested_publisher}
- Własny link do oficjalnej strony: {official_link}
- Własny link do instrukcji PDF: {manual_link}

Poniżej znajdują się pobrane treści stron internetowych (maksymalnie 4000 znaków na stronę).
Przeanalizuj każdą z nich i wyodrębnij fakty.

{sources_text}

Zwróć wynik w formacie JSON o następującej strukturze:
{{
  "sources_analysis": [
    {{
      "url": "dokładny_url_źródła",
      "source_type": "bgg|publisher|distributor|shop|review|manual_pdf|official|other",
      "facts": {{
        "publisher": "nazwa wydawcy lub null",
        "designer": "projektant lub null",
        "illustrator": "ilustrator lub null",
        "players": "liczba graczy lub null",
        "age": "sugerowany wiek lub null",
        "play_time": "czas gry lub null",
        "edition_language": "język wydania lub null",
        "manual_language": "język instrukcji lub null",
        "release_date": "data premiery lub null",
        "box_contents": ["element 1", "element 2"],
        "instruction_pdf": "link do pdf lub null"
      }}
    }}
  ]
}}
"""

def extract_facts(game_name: str, sources: list, user_inputs: dict = None) -> dict:
    """
    Extract facts from multiple sources using LLM.
    
    Args:
        game_name: Name of the board game.
        sources: List of dicts representing scraped pages [{"url": str, "title": str, "body": str}]
        user_inputs: Optional dictionary of user inputs (original_title, publisher, etc.)
        
    Returns:
        Dict containing facts extracted per source.
    """
    user_inputs = user_inputs or {}
    original_title = user_inputs.get("original_title", "")
    suggested_publisher = user_inputs.get("publisher", "")
    official_link = user_inputs.get("official_link", "")
    manual_link = user_inputs.get("manual_link", "")
    
    sources_text_list = []
    for src in sources:
        # Cap text size to avoid bloating prompt
        body_capped = src.get("body", "")[:4000]
        sources_text_list.append(
            f"--- ŹRÓDŁO: {src.get('url')} ---\n"
            f"Tytuł strony: {src.get('title')}\n"
            f"Zawartość:\n{body_capped}\n"
        )
        
    sources_text = "\n".join(sources_text_list)
    
    prompt = EXTRACTOR_PROMPT_TEMPLATE.format(
        game_name=game_name,
        original_title=original_title,
        suggested_publisher=suggested_publisher,
        official_link=official_link,
        manual_link=manual_link,
        sources_text=sources_text
    )
    
    try:
        response_text = generate_text(
            prompt=prompt,
            system_instruction=EXTRACTOR_SYSTEM_INSTRUCTION,
            json_mode=True,
            api_key=user_inputs.get("api_key"),
            provider=user_inputs.get("api_provider"),
            base_url=user_inputs.get("api_base_url"),
            model_name=user_inputs.get("api_model")
        )
        
        # Parse JSON output
        extracted_data = parse_llm_json(response_text)
        logger.info(f"Successfully extracted facts for: {game_name}")
        return extracted_data
        
    except json.JSONDecodeError as je:
        logger.error(f"Failed to parse JSON from LLM: {je}. Raw output was: {response_text}")
        return {"sources_analysis": []}
    except LLMError as e:
        logger.error(f"Error during facts extraction: {e}")
        raise
    except Exception as e:
        logger.error(f"Error during facts extraction: {e}")
        return {"sources_analysis": []}
