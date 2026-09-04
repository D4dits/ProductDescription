# Generator Opisów Produktów - graszki.pl

Lokalne narzędzie do automatycznego przygotowywania opisów i metadanych gier planszowych dla sklepu internetowego graszki.pl przy użyciu sztucznej inteligencji (DeepSeek / Z.AI / Gemini / OpenAI).

Narzędzie automatycznie przeszukuje internet (BoardGameGeek XML API 2 + wyszukiwarka), zbiera fakty techniczne, usuwa zbędny szum ze stron, weryfikuje rozbieżności, a następnie generuje unikalne opisy i komplety danych gotowych do wklejenia w panel sklepu.

---

## Funkcje narzędzia

1. **Unikalny opis rozszerzony HTML** – gotowa struktura z sekcjami (Krótko o grze, Na czym polega, Dlaczego warto, Pudełko, Dane techniczne).
2. **Opis skrócony** – skondensowane 1-2 zdania (max 300 znaków) na listy produktów.
3. **Optymalizacja SEO** – generowanie zwięzłego tytułu SEO (max 60 znaków) i naturalnego meta opisu (140-160 znaków).
4. **Tagi / Słowa kluczowe** – od 15 do 30 zoptymalizowanych tagów dla wyszukiwarki sklepowej (w tym autor, wydawca, odmiany językowe).
5. **Weryfikacja danych i priorytetyzacja** – rozwiązywanie sprzeczności w parametrach gry (np. wiek, czas rozgrywki) z zachowaniem hierarchii ważności źródeł:
   1. Oficjalna strona wydawcy,
   2. Oficjalna strona polskiego dystrybutora/wydawcy,
   3. Instrukcja PDF,
   4. BoardGameGeek,
   5. Sklepy i recenzje (pomocniczo).
6. **Obsługa przedsprzedaży (Preorder)** – automatyczne wykrywanie na podstawie nazwy, modyfikacja metadanych (dodanie słowa "Przedsprzedaż") oraz wstawianie informacji o orientacyjnej premierze.
7. **Analiza podobieństwa** – automatyczne porównanie nowego opisu z wcześniej wygenerowanymi (z katalogu `output/`). Jeżeli tekst jest zbyt podobny (>70%), następuje automatyczne przeorganizowanie zdań.
8. **Edycja ręczna i regeneracja** – interfejs webowy pozwala modyfikować wyniki na żywo, generować tekst ponownie o określonym tonie (sprzedażowy, neutralny, rodzinny, krótszy) bez konieczności ponownego scrapowania stron.

---

## Instalacja

### Wymagania
* Python 3.8 lub nowszy
* Połączenie z internetem (do scrapowania i API modeli AI)

### Instrukcja krok po kroku

1. **Sklonuj repozytorium i wejdź do katalogu projektu**:
   ```bash
   git clone git@github.com:D4dits/ProductDescription.git
   cd ProductDescription
   ```

2. **Utwórz i aktywuj środowisko wirtualne**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

   Na Windows:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Pobierz zależności**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Skonfiguruj plik środowiskowy `.env`**:
   Skopiuj plik `.env.example` jako `.env`:
   ```bash
   cp .env.example .env
   ```
   Otwórz plik `.env` i uzupełnij klucz API dla wybranego modelu:
   - `DEEPSEEK_API_KEY` (jeśli używasz DeepSeek - obsługiwane przez endpoint OpenAI-compatible) LUB
   - `ZAI_API_KEY` (jeśli używasz Z.AI - obsługiwane przez endpoint OpenAI-compatible) LUB
   - `GEMINI_API_KEY` (jeśli używasz Gemini - zalecane) LUB
   - `OPENAI_API_KEY` (jeśli używasz OpenAI)

   Jeśli masz klucz DeepSeek, ustaw:
   ```env
   LLM_PROVIDER=deepseek
   DEEPSEEK_API_KEY=twoj_klucz_deepseek
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-v4-flash
   ```

   Jeśli masz tylko klucz Z.AI, ustaw:
   ```env
   LLM_PROVIDER=z_ai
   ZAI_API_KEY=twoj_klucz_zai
   ZAI_BASE_URL=https://api.z.ai/api/paas/v4/
   ZAI_MODEL=glm-5.2
   ```

   Możesz również wybrać dostawcę za pomocą `LLM_PROVIDER=gemini`, `LLM_PROVIDER=openai`, `LLM_PROVIDER=z_ai`, `LLM_PROVIDER=deepseek` lub `LLM_PROVIDER=custom`.

---

## Uruchomienie

### 1. Interfejs Webowy (rekomendowany)

Uruchom lokalny serwer FastAPI:
```bash
python -m app.web.main
```
Aplikacja będzie dostępna pod adresem: [http://127.0.0.1:8000](http://127.0.0.1:8000).

W interfejsie znajdziesz:
* Formularz wejściowy parametrów gry.
* Dynamiczne śledzenie etapów pobierania (BGG, scraping, LLM).
* Tryb **Bez API / prompt do Codexa**, który zbiera źródła i przygotowuje prompt do wklejenia w rozmowie z Codexem/ChatGPT.
* Karty z wynikami i przyciskami **kopiowania jednym kliknięciem**.
* Live-preview wyrenderowanego kodu HTML obok edytora kodu.
* Formularz do nanoszenia poprawek i przycisk **"Zapisz poprawioną wersję"** (aktualizuje pliki eksportu).
* Szybkie akcje zmiany tonacji opisu.

### Tryb bez API / prompt do Codexa

1. W sekcji **Konfiguracja API** wybierz `Bez API / prompt do Codexa`.
2. Kliknij **Przygotuj prompt**.
3. Skopiuj wygenerowany prompt i wklej go w rozmowie z Codexem/ChatGPT.
4. Wklej otrzymany JSON w polu **Wynik JSON od Codexa** i kliknij **Wczytaj wynik i zapisz**.

### 2. Tryb CLI (Terminal)

Możesz wygenerować opis bezpośrednio z konsoli za pomocą skryptu `cli.py`:
```bash
python cli.py "Nazwa Gry" [opcje]
```

**Przykłady:**
```bash
# Podstawowe generowanie
python cli.py "Papierowe Morze"

# Oznaczenie jako przedsprzedaż z sugerowanym wydawcą i oryginalnym tytułem
python cli.py "Przedsprzedaż Wiedźmin: Stary Świat" -o "The Witcher: Old World" -p "Rebel" -r "wrzesień 2026"

# Generowanie w określonym tonie (np. sprzedażowym)
python cli.py "Wsiąść do Pociągu: Europa" --tone sales
```

**Pełna lista opcji CLI:**
```text
Pozycyjne:
  product_name           Nazwa gry planszowej

Opcjonalne:
  -o, --original-title   Oryginalny tytuł gry (ułatwia wyszukiwanie BGG)
  -p, --publisher        Sugerowany wydawca gry
  --preorder             Włącza tryb przedsprzedaży
  -r, --release-date     Orientacyjna data premiery
  -c, --category         Kategoria gry (np. rodzinna, strategiczna)
  -a, --target-audience  Grupa docelowa (np. rodziny, pary)
  --official-link        Własny link do oficjalnej strony gry
  --manual-link          Własny link do instrukcji PDF
  -t, --tone             Ton opisu: [standard, sales, neutral, family, short]
  --api-provider         Dostawca LLM: [gemini, openai, z_ai, deepseek, custom]
  --api-key              Klucz API tylko dla tego uruchomienia
  --api-base-url         Base URL dla OpenAI-compatible endpointu
  --api-model            Nazwa modelu, np. deepseek-v4-flash, deepseek-v4-pro, glm-5.2
```

---

## Tryb Przedsprzedaży (Preorder)

1. **Autodetekcja**: Jeśli podasz nazwę zaczynającą się od słowa "Przedsprzedaż" (np. "Przedsprzedaż Sea Salt & Paper"), tryb przedsprzedaży włączy się automatycznie.
2. **Tytuł SEO**: Zostanie automatycznie poprzedzony frazą "Przedsprzedaż ".
3. **Sekcja HTML "Dodatkowe informacje"**: Zostanie wzbogacona o pozycję `Orientacyjna premiera: [Data]`. Jeśli data nie jest znana, wyświetli się: `Orientacyjna premiera: brak potwierdzonej daty` wraz z informacją, że termin może ulec zmianie.

---

## Formaty Plików Wyjściowych

Każde pomyślne wygenerowanie (lub zapisanie edycji ręcznej) zapisuje pliki w katalogu `/output/`:
1. `output/[slug].json` – Pełny, strukturyzowany obiekt zawierający wszystkie metadane, teksty, źródła wraz z faktami oraz ostrzeżenia.
2. `output/[slug].html` – Kod HTML opisu rozszerzonego. Domyślnie `USE_LEGACY_INLINE_STYLES=true`, więc opis dostaje wrapper `.def`, kolor `#444444`, rozmiar `medium` i podkreślone nagłówki `h3` zgodne ze starszym szablonem sklepu.
3. `output/[slug].txt` – Plik tekstowy ułatwiający szybkie skopiowanie najważniejszych parametrów (SEO Title, Meta Description, Short Desc, Tagi).
4. `output/[slug].csv` – Tabela z parametrami technicznymi do importu do arkusza.

*Uwaga: `slug` jest generowany automatycznie na podstawie nazwy gry (np. "Papierowe Morze" -> "papierowe-morze").*

---

## Testy Jednostkowe

Aby sprawdzić poprawność działania algorytmów walidacyjnych, rozstrzygania konfliktów oraz formatowania HTML, uruchom:
```bash
pytest
```

---

## Import hurtowy Rebel do Sky-Shop

Panel ma osobny tryb **Import Rebel** przeznaczony do cyklicznego przygotowywania opisów i SEO dla produktów zaimportowanych z hurtowni.

Ustaw w lokalnym `.env`:

```env
REBEL_FEED_URL=https://hurt.rebel.pl/export/products/...?...
SKYSHOP_API_URL=https://graszki.pl/api
SKYSHOP_API_KEY=twoj_klucz_webapi
BATCH_GENERATION_WORKERS=3
```

Pełny adres feedu i klucze są sekretami. Nie zapisuj ich w repozytorium ani w raportach.

Przebieg pracy:

1. Otwórz `http://127.0.0.1:8000/#batch` i prześlij eksport produktów ze Sky-Shop. Feed Rebel można również przesłać jako plik; bez pliku zostanie pobrany z `REBEL_FEED_URL`.
2. Sprawdź liczbę dopasowań i uruchom **Generuj pilot 10**.
3. Przejrzyj każdy wynik, popraw go w razie potrzeby i zatwierdź komplet pilota.
4. Ustaw wielkość paczki (domyślnie 50) i użyj **Generuj kolejne**. Ta akcja jest zablokowana do czasu zatwierdzenia pilota.
5. Zatwierdź wybrane treści. Samo generowanie i zatwierdzanie nie łączy się ze Sky-Shop.
6. Przed publikacją wpisz widoczne w panelu ID partii i kliknij **Wyślij zatwierdzone**.

Generowanie działa równolegle. `BATCH_GENERATION_WORKERS` określa liczbę jednoczesnych żądań
do modelu (domyślnie 3, zakres 1-8). Panel pokazuje postęp, bieżący produkt, czas pracy i ETA.
Status `Do kontroli` oznacza poprawnie wygenerowaną treść oczekującą na ręczną weryfikację,
a nie błąd walidacji.

Przed generowaniem aplikacja próbuje uzupełnić brakujące dane strukturalne z publicznej karty
produktu Rebel. Potwierdzona lista zawartości pudełka jest zapisywana wraz ze źródłem i
wstawiana do opisu deterministycznie, bez powierzania jej modelowi językowemu.

Publikacja używa `addUpdateProducts`, `importType=update` i `prodIndex=prod_id`. XML zawiera wyłącznie ID produktu, opis rozszerzony, opis skrócony, tytuł SEO, opis SEO i tagi. Cena, stan, VAT, kategorie, widoczność oraz ustawienia hurtowni nie są wysyłane. Przed zmianą zapisywana jest kopia pięciu pól przez `getProductData`, a po zapisie te same pola są ponownie odczytywane i porównywane. Kopię można później przywrócić akcją **Przywróć kopię**.

Stan kolejki znajduje się w ignorowanym przez Git katalogu `batch_data/`. Ponowne zaimportowanie niezmienionych produktów po zweryfikowanej publikacji oznaczy je jako `unchanged` i nie wygeneruje treści ponownie.
