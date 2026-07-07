import pytest
from app.validator import validate_generated_content, resolve_facts_conflicts

def test_forbidden_phrases():
    # Test text containing forbidden phrases
    short_desc = "Fajna gra planszowa"
    meta_desc = "Zagraj w to ze znajomymi."
    seo_title = "Fajna gra planszowa"
    html_desc = "<h2>Krótko o grze</h2><p>To najlepsza gra na rynku!</p>"
    is_preorder = False
    additional_info = {"players": "2-4", "age": "10+", "play_time": "30-60"}
    fact_sources = {"players": "http://test.com", "age": "http://test.com", "play_time": "http://test.com"}

    warnings = validate_generated_content(
        short_desc, meta_desc, seo_title, html_desc, is_preorder, additional_info, fact_sources
    )
    
    assert any("niedozwoloną frazę: 'najlepsza gra na rynku'" in w for w in warnings)

def test_short_and_meta_identical():
    # Identical short and meta descriptions
    desc = "Papierowe Morze to szybka gra karciana dla 2 osób."
    seo_title = "Papierowe Morze - gra karciana"
    html_desc = "<h2>Krótko o grze</h2><p>Papierowe Morze...</p>"
    is_preorder = False
    additional_info = {"players": "2-4", "age": "10+", "play_time": "30-60"}
    fact_sources = {"players": "http://test.com", "age": "http://test.com", "play_time": "http://test.com"}

    warnings = validate_generated_content(
        desc, desc, seo_title, html_desc, is_preorder, additional_info, fact_sources
    )
    
    assert any("Opis skrócony jest identyczny z meta opisem" in w for w in warnings)

def test_meta_description_length():
    short_desc = "Papierowe Morze"
    seo_title = "Papierowe Morze"
    html_desc = "<h2>Krótko o grze</h2><p>Papierowe Morze...</p>"
    is_preorder = False
    additional_info = {"players": "2", "age": "8", "play_time": "30"}
    fact_sources = {"players": "http://test.com", "age": "http://test.com", "play_time": "http://test.com"}

    # Too short meta description (40 characters)
    short_meta = "Papierowe Morze to szybka gra karciana."
    warnings = validate_generated_content(
        short_desc, short_meta, seo_title, html_desc, is_preorder, additional_info, fact_sources
    )
    assert any("Meta opis ma długość" in w and "zalecane: 140-160" in w for w in warnings)

def test_h3_sections_are_accepted_for_legacy_html():
    short_desc = "Krótki opis"
    meta_desc = "To jest przykładowy meta opis o odpowiedniej długości, przygotowany wyłącznie na potrzeby testu walidatora."
    seo_title = "Testowa gra planszowa"
    html_desc = (
        "<h3>Krótko o grze</h3>"
        "<h3>Na czym polega rozgrywka?</h3>"
        "<h3>Dlaczego warto?</h3>"
        "<h3>Zawartość pudełka:</h3>"
        "<h3>Dodatkowe informacje:</h3>"
    )
    additional_info = {"players": "2-4", "age": "10+", "play_time": "30-60"}
    fact_sources = {"players": "http://test.com", "age": "http://test.com", "play_time": "http://test.com"}

    warnings = validate_generated_content(
        short_desc, meta_desc, seo_title, html_desc, False, additional_info, fact_sources
    )

    assert not any("HTML nie zawiera wymaganej sekcji" in w for w in warnings)

def test_box_contents_section_is_required_only_when_contents_exist():
    short_desc = "Krótki opis"
    meta_desc = "To jest przykładowy meta opis o odpowiedniej długości, przygotowany wyłącznie na potrzeby testu walidatora."
    seo_title = "Testowa gra planszowa"
    html_desc = (
        "<h2>Krótko o grze</h2>"
        "<h2>Na czym polega rozgrywka?</h2>"
        "<h2>Dlaczego warto?</h2>"
        "<h2>Dodatkowe informacje:</h2>"
    )
    additional_info = {"players": "2-4", "age": "10+", "play_time": "30-60"}
    fact_sources = {"players": "http://test.com", "age": "http://test.com", "play_time": "http://test.com"}

    warnings_without_contents = validate_generated_content(
        short_desc, meta_desc, seo_title, html_desc, False, additional_info, fact_sources, box_contents=[]
    )
    warnings_with_contents = validate_generated_content(
        short_desc, meta_desc, seo_title, html_desc, False, additional_info, fact_sources, box_contents=["1 plansza"]
    )

    assert not any("Zawartość pudełka" in w for w in warnings_without_contents)
    assert any("Zawartość pudełka" in w for w in warnings_with_contents)

def test_source_reference_phrases_are_forbidden():
    warnings = validate_generated_content(
        "Krótki opis",
        "To jest przykładowy meta opis o odpowiedniej długości, przygotowany wyłącznie na potrzeby testu walidatora.",
        "Testowa gra planszowa",
        "<h2>Krótko o grze</h2><p>W oficjalnym opisie gra ma dużo taktyki.</p>",
        False,
        {"players": "2-4", "age": "10+", "play_time": "30-60"},
        {"players": "http://test.com", "age": "http://test.com", "play_time": "http://test.com"},
    )

    assert any("w oficjalnym opisie" in w for w in warnings)

def test_conflict_resolution():
    # Setup sources with different values for key parameters
    sources_analysis = [
        {
            "url": "http://publisher.com",
            "source_type": "publisher",
            "facts": {
                "publisher": "Muduko (Publisher)",
                "designer": "Bruno Cathala",
                "players": "2",
                "age": "8+"
            }
        },
        {
            "url": "http://boardgamegeek.com/1234",
            "source_type": "bgg",
            "facts": {
                "publisher": "Origames",
                "designer": "Bruno Cathala, Theo Riviere",
                "players": "2-4",
                "age": "7+",
                "play_time": "30-45"
            }
        }
    ]
    
    resolved_info, _, warnings, fact_sources = resolve_facts_conflicts(
        sources_analysis=sources_analysis,
        user_inputs={"is_preorder": False}
    )
    
    # Publisher should win for publisher name
    assert resolved_info["publisher"] == "Muduko (Publisher)"
    
    # Publisher should win for player count
    assert resolved_info["players"] == "2"
    
    # Publisher should win for age
    assert resolved_info["age"] == "8+"
    
    # BGG should resolve play_time since publisher has none
    assert resolved_info["play_time"] == "30-45"
    
    # Ensure source tracking maps properly
    assert fact_sources["players"] == "http://publisher.com"
    assert fact_sources["play_time"] == "http://boardgamegeek.com/1234"
    
    # Ensure conflict warning was generated for players and age
    assert any("Konflikt danych dla 'players'" in w for w in warnings)
    assert any("Konflikt danych dla 'age'" in w for w in warnings)
