import json
import re
from bs4 import BeautifulSoup
from app.llm import generate_text, LLMError
from app.config import USE_LEGACY_INLINE_STYLES
from app.logger import logger
from app.json_utils import parse_llm_json
from app.validator import check_similarity_with_existing

SEO_BRAND_SUFFIX = " | Graszki.pl"
SEO_TITLE_MAX_LENGTH = 65

GENERATOR_SYSTEM_INSTRUCTION = """Jesteś doświadczonym copywriterem specjalizującym się w branży gier planszowych oraz optymalizacji SEO/GEO. Twój cel to przygotowanie unikalnych, atrakcyjnych i zgodnych z wymaganiami opisów produktów dla sklepu graszki.pl.

Napisz tekst całkowicie po polsku, zachowując przyjazny, konkretny, lekko entuzjastyczny, ale wiarygodny ton. Unikaj agresywnego marketingu, pustych obietnic i nadmiaru przymiotników. Używaj prostego, naturalnego języka.

Zasady kluczowe:
1. Bazuj wyłącznie na podanych faktach. Nie wymyślaj informacji o grze (autorach, wydawcy, elementach itp.). Jeśli brak jakiejś informacji, pomiń ją lub napisz "brak potwierdzonych danych".
2. Opisy muszą być unikatowe. Nie kopiuj konstrukcji ani zdań z innych serwisów.
3. Rotuj style rozpoczęcia opisu (od klimatu, celu gry, sytuacji przy stole, mechaniki, grupy docelowej lub pytania).
4. Nie zaczynaj opisu od słów "To gra...", "Ta gra..." ani podobnych szablonowych zwrotów.
5. Sekcja "Dlaczego warto?" musi zawierać 3-5 krótkich, konkretnych zalet gry bez powtarzania tych samych słów i bez ogólników.
6. Jeśli produkt to Przedsprzedaż, tytuł SEO musi zaczynać się od słowa "Przedsprzedaż", a w danych technicznych i opisie musi pojawić się informacja o orientacyjnej premierze bez obiecywania sztywnej daty dostawy.
7. HTML musi posiadać ścisłą strukturę z nagłówkami <h2> i listami <ul>.
8. Zwróć wyłącznie poprawny JSON. Wartości tekstowe nie mogą zawierać nieucieczonych cudzysłowów podwójnych; w treści używaj apostrofów albo encji HTML &quot;.
9. Tytuł SEO ma kończyć się nazwą marki: | Graszki.pl.
10. Opis skrócony i meta opis muszą być jedną linią tekstu, bez znaków nowej linii.
"""

GENERATOR_PROMPT_TEMPLATE = """Przygotuj zestaw treści dla gry planszowej: {game_name}

Dane techniczne i fakty (użyj tylko tych zweryfikowanych):
{facts_text}

Parametry wejściowe od użytkownika:
- Oryginalny tytuł: {original_title}
- Czy to przedsprzedaż: {is_preorder}
- Kategoria: {category}
- Grupa docelowa: {target_audience}
- Wskazówka dotycząca stylu: {tone_instruction}
{additional_prompt_instruction}

Wymagane sekcje w opisie rozszerzonym HTML:
1. <h2>Krótko o grze</h2>
   <p>Unikatowy opis gry: temat, klimat, główna mechanika, dla kogo jest gra, co gracz robi w swojej turze albo jaki jest cel rozgrywki.</p>

2. <h2>Na czym polega rozgrywka?</h2>
   <p>Opis zasad na poziomie sprzedażowym, bez przepisywania instrukcji. Zrozumiały dla laika.</p>

3. <h2>Dlaczego warto?</h2>
   <ul>
   <li>3–5 krótkich, konkretnych powodów.</li>
   </ul>

{group_docelowa_html}

5. <h2>Zawartość pudełka:</h2>
   <ul>
   <li>Elementy pudełka (każdy element jako osobny punkt <li>).</li>
   </ul>

6. <h2>Dodatkowe informacje:</h2>
   <ul>
   <li>Wydawca: ...</li>
   <li>Projektant: ...</li>
   {illustrator_li}
   <li>Wydanie: {edition_language}</li>
   <li>Instrukcja: {manual_language}</li>
   <li>Liczba graczy: {players}</li>
   <li>Zalecany wiek: {age}</li>
   <li>Czas rozgrywki: {play_time} minut</li>
   {preorder_li}
   {pdf_manual_li}
   </ul>

*Ważne*: Jeśli dany parametr w sekcji "Dodatkowe informacje" (np. ilustrator, projektant, instrukcja PDF) jest pusty lub nieznany, POMIŃ go w wyjściowym HTML (nie wstawiaj pustego punktu <li>).
*Ważne dla JSON*: Nie używaj surowych znaków " wewnątrz wartości tekstowych. Jeśli musisz zacytować nazwę lub termin, użyj apostrofu albo encji &quot;. Atrybuty HTML zapisuj z apostrofami, np. <a href='https://...'>.

Zwróć wynik jako obiekt JSON o następującej strukturze:
{{
  "short_description": "Opis skrócony (1-2 zdania, max 300 znaków. Ma zawierać nazwę gry, typ gry, najważniejszą korzyść. Unikaj ogólników)",
  "seo_title": "Tytuł SEO (max ok. 60-65 znaków, kończy się '| Graszki.pl', np. 'Gra planszowa X - strategiczna planszówka | Graszki.pl')",
  "meta_description": "Meta opis (140-160 znaków, jedna linia, naturalny, zawiera nazwę, typ gry, najważniejsze parametry, brak cudzysłowów)",
  "tags": ["tag1", "tag2", "tag3", "słowo kluczowe", "autor", "wydawca"],
  "extended_description_html": "Wygenerowany kod HTML zawierający sekcje opisane wyżej (bez stylów inline, czyste tagi h2, p, ul, li)"
}}
"""

def normalize_single_line_text(value: str) -> str:
    """Collapse whitespace so metadata copies cleanly into shop fields."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def apply_seo_brand_suffix(title: str) -> str:
    """Append Graszki.pl while keeping the SEO title within the validator limit."""
    normalized = normalize_single_line_text(title)
    if not normalized:
        return ""

    base_title = re.sub(r"\s*(?:[|–-]\s*)?graszki\.pl\s*$", "", normalized, flags=re.IGNORECASE).strip()
    base_title = base_title.rstrip(" |-–")

    available = SEO_TITLE_MAX_LENGTH - len(SEO_BRAND_SUFFIX)
    if len(base_title) > available:
        shortened = base_title[:available].rstrip()
        if " " in shortened:
            shortened = shortened.rsplit(" ", 1)[0]
        base_title = shortened.rstrip(" |-–")

    return f"{base_title}{SEO_BRAND_SUFFIX}" if base_title else normalized

def normalize_product_metadata(product_data: dict) -> dict:
    """Normalize copy-sensitive metadata fields in-place and return the dict."""
    product_data["short_description"] = normalize_single_line_text(product_data.get("short_description", ""))
    product_data["meta_description"] = normalize_single_line_text(product_data.get("meta_description", ""))
    product_data["seo_title"] = apply_seo_brand_suffix(product_data.get("seo_title", ""))
    return product_data

def apply_legacy_inline_styles(html_content: str) -> str:
    """
    Normalizes generated HTML to the older graszki.pl store visual style.
    The wrapper carries the common typography, while headings keep the
    underlined legacy look without repeating spans in every paragraph/list item.
    """
    if not html_content:
        return ""
        
    soup = BeautifulSoup(html_content, "html.parser")

    existing_wrapper = soup.find("div", class_="def")
    source_children = list(existing_wrapper.contents) if existing_wrapper else list(soup.contents)

    normalized = BeautifulSoup("", "html.parser")
    wrapper = normalized.new_tag("div")
    wrapper["itemprop"] = "description"
    wrapper["class"] = "def"
    wrapper["style"] = (
        "font-family: arial, helvetica, sans-serif; "
        "font-size: medium; "
        "line-height: 1.5; "
        "color: #444444;"
    )

    for child in source_children:
        wrapper.append(child.extract())

    normalized.append(wrapper)

    for text_node in normalized.find_all(string=True):
        if text_node.parent and text_node.parent.name not in {"pre", "code"}:
            text_node.replace_with(re.sub(r"\s+", " ", str(text_node)))

    heading_style = (
        "box-sizing: border-box; "
        "font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; "
        "line-height: 1.1; "
        "color: #444444; "
        "margin-top: 17px; "
        "margin-bottom: 8.5px; "
        "font-size: medium; "
        "border-bottom: 1px solid #cccccc; "
        "padding-bottom: 3px;"
    )

    for tag in normalized.find_all(True):
        for attr_name, attr_value in list(tag.attrs.items()):
            if isinstance(attr_value, str):
                if attr_name in {"href", "src"}:
                    tag[attr_name] = re.sub(r"\s+", "", attr_value)
                elif attr_name != "style":
                    tag[attr_name] = re.sub(r"\s+", " ", attr_value).strip()

        if tag.name in {"ul", "ol", "li"}:
            tag.attrs.pop("class", None)
        else:
            classes = tag.get("class", [])
            if isinstance(classes, str):
                classes = [classes]
            if "def" not in classes:
                classes.append("def")
            tag["class"] = classes

        if tag.name not in {"div", "h1", "h2", "h3", "h4"}:
            tag.attrs.pop("style", None)

    for heading in normalized.find_all(["h1", "h2", "h3", "h4"]):
        heading.name = "h3"
        heading["style"] = heading_style

    for p in normalized.find_all("p"):
        p["style"] = "margin-top: 0; margin-bottom: 15px;"

    return str(normalized)

def format_facts_as_text(facts: dict) -> str:
    """Format facts dictionary into readable text block for LLM prompt."""
    lines = []
    for k, v in facts.items():
        if v:
            if isinstance(v, list):
                lines.append(f"- {k}: {', '.join(v)}")
            else:
                lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def generate_descriptions(
    game_name: str,
    resolved_facts: dict,
    user_inputs: dict,
    force_tone: str = None,
    rewrite_instruction: str = None
) -> dict:
    """
    Generates product descriptions, SEO data, and HTML using LLM.
    Includes validation for similarity and rewrite triggers.
    """
    # 1. Prepare facts for prompt
    facts_text = format_facts_as_text(resolved_facts)
    
    # 2. Get tone instruction
    tone = force_tone or user_inputs.get("tone_preference", "standard")
    if tone == "sales":
        tone_instruction = "Generuj bardziej sprzedażowo, podkreśl emocje, klimat i to, dlaczego rozgrywka wciąga."
    elif tone == "neutral":
        tone_instruction = "Generuj bardziej neutralnie, rzeczowo, skup się na faktach i precyzyjnym opisie mechaniki."
    elif tone == "family":
        tone_instruction = "Generuj z naciskiem na aspekt rodzinny, łatwe zasady, integrację pokoleń i zabawę z dziećmi."
    elif tone == "short":
        tone_instruction = "Generuj krótszy, zwięzły opis. Skróć sekcje w HTML, by tekst był bardzo zwięzły."
    else:
        tone_instruction = "Generuj zbalansowany opis: przyjazny, konkretny i lekko entuzjastyczny."
        
    # 3. Handle optional target audience section in HTML
    target_audience = user_inputs.get("target_audience", "")
    group_docelowa_html = ""
    if target_audience:
        group_docelowa_html = (
            "4. <h2>Dla kogo będzie dobra?</h2>\n"
            f"   <p>Opis grupy docelowej. Gra idealnie pasuje do: {target_audience}. "
            "Uzasadnij dlaczego, bazując na charakterze gry.</p>"
        )
        
    # 4. Handle optional details in technical specs HTML
    illustrator_li = ""
    if resolved_facts.get("illustrator"):
        illustrator_li = "<li>Ilustrator: ...</li>"
        
    is_preorder = user_inputs.get("is_preorder", False)
    preorder_li = ""
    if is_preorder:
        preorder_li = "<li>Orientacyjna premiera: ...</li>"
        
    pdf_manual_li = ""
    if resolved_facts.get("instruction_pdf"):
        pdf_manual_li = "<li>Instrukcja PDF: link</li>"
        
    # 5. Build extra prompts
    additional_prompt_instruction = ""
    if rewrite_instruction:
        additional_prompt_instruction = f"\n*UWAGA (INSTRUKCJA POPRAWKI):*\n{rewrite_instruction}"
        
    # 6. Format prompt
    prompt = GENERATOR_PROMPT_TEMPLATE.format(
        game_name=game_name,
        facts_text=facts_text,
        original_title=user_inputs.get("original_title", ""),
        is_preorder="Tak" if is_preorder else "Nie",
        category=user_inputs.get("category", ""),
        target_audience=target_audience,
        tone_instruction=tone_instruction,
        additional_prompt_instruction=additional_prompt_instruction,
        group_docelowa_html=group_docelowa_html,
        illustrator_li=illustrator_li,
        edition_language=resolved_facts.get("edition_language") or "polskie",
        manual_language=resolved_facts.get("manual_language") or "polska",
        players=resolved_facts.get("players") or "brak potwierdzonych danych",
        age=resolved_facts.get("age") or "brak potwierdzonych danych",
        play_time=resolved_facts.get("play_time") or "brak potwierdzonych danych",
        preorder_li=preorder_li,
        pdf_manual_li=pdf_manual_li
    )
    
    # 7. Generate using LLM
    try:
        response_text = generate_text(
            prompt=prompt,
            system_instruction=GENERATOR_SYSTEM_INSTRUCTION,
            json_mode=True,
            api_key=user_inputs.get("api_key"),
            provider=user_inputs.get("api_provider"),
            base_url=user_inputs.get("api_base_url"),
            model_name=user_inputs.get("api_model")
        )
        
        result = parse_llm_json(response_text)
        normalize_product_metadata(result)
        
        # Post-process HTML for inline styles if requested
        html_content = result.get("extended_description_html", "")
        
        # Check similarity with existing output files
        # Only perform the check if we're not already rewriting
        if not rewrite_instruction:
            is_too_similar, max_sim, match_file = check_similarity_with_existing(html_content)
            if is_too_similar:
                logger.info(f"Generated text is too similar to {match_file} ({max_sim:.2f}). Triggering rewrite...")
                rewrite_msg = (
                    f"Wygenerowany opis jest w {max_sim*100:.1f}% podobny do istniejącego opisu w bazie ({match_file}). "
                    "Napisz tekst całkowicie na nowo. Zmień strukturę zdań, zastosuj inne słownictwo, "
                    "zmień styl otwarcia (np. jeśli otwarcie było o klimacie, zacznij od pytania lub celu gry). "
                    "Zachowaj wszystkie fakty, ale zredaguj je zupełnie inaczej."
                )
                return generate_descriptions(
                    game_name=game_name,
                    resolved_facts=resolved_facts,
                    user_inputs=user_inputs,
                    force_tone=force_tone,
                    rewrite_instruction=rewrite_msg
                )

        # Apply legacy inline styles programmatically if config demands it
        # Or if the user specifies it in settings (which we read from config)
        if USE_LEGACY_INLINE_STYLES:
            result["extended_description_html"] = apply_legacy_inline_styles(html_content)
            
        logger.info(f"Generated descriptions and metadata for game: {game_name}")
        return result
        
    except json.JSONDecodeError as je:
        logger.error(f"Failed to parse generation JSON: {je}. Raw output was: {response_text}")
        raise LLMError("Błąd generowania danych JSON przez LLM.")
    except Exception as e:
        logger.error(f"Error in generate_descriptions: {e}")
        raise e
