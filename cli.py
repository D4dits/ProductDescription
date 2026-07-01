#!/usr/bin/env python
import argparse
import sys
from app.pipeline import run_generation_pipeline
from app.logger import logger

def main():
    parser = argparse.ArgumentParser(
        description="Generator opisów gier planszowych dla sklepu graszki.pl (Tryb CLI)"
    )
    
    # Input fields
    parser.add_argument("product_name", type=str, help="Nazwa produktu (gry planszowej)")
    parser.add_argument("-o", "--original-title", type=str, default="", help="Oryginalny tytuł gry")
    parser.add_argument("-p", "--publisher", type=str, default="", help="Wydawca gry")
    parser.add_argument("--preorder", action="store_true", help="Oznacz produkt jako przedsprzedaż")
    parser.add_argument("-r", "--release-date", type=str, default="", help="Orientacyjna data premiery")
    parser.add_argument("-c", "--category", type=str, default="", help="Kategoria gry (np. rodzinna, strategiczna)")
    parser.add_argument("-a", "--target-audience", type=str, default="", help="Grupa docelowa (np. rodziny, pary, zaawansowani)")
    parser.add_argument("--official-link", type=str, default="", help="Link do oficjalnej strony produktu")
    parser.add_argument("--manual-link", type=str, default="", help="Link do instrukcji PDF")
    parser.add_argument("--api-provider", choices=["gemini", "openai", "z_ai", "deepseek", "custom"], default="", help="Dostawca LLM, np. deepseek albo z_ai")
    parser.add_argument("--api-key", type=str, default="", help="Klucz API podany tylko dla tego uruchomienia")
    parser.add_argument("--api-base-url", type=str, default="", help="Base URL dla endpointu OpenAI-compatible")
    parser.add_argument("--api-model", type=str, default="", help="Nazwa modelu, np. glm-5.2")
    
    # Options
    parser.add_argument(
        "-t", "--tone", 
        choices=["standard", "sales", "neutral", "family", "short"], 
        default="standard", 
        help="Ton generowania tekstu (sales = sprzedażowy, neutral = neutralny, family = rodzinny, short = krótki)"
    )

    args = parser.parse_args()
    
    user_inputs = {
        "product_name": args.product_name,
        "original_title": args.original_title,
        "publisher": args.publisher,
        "is_preorder": args.preorder,
        "release_date_note": args.release_date,
        "category": args.category,
        "target_audience": args.target_audience,
        "official_link": args.official_link,
        "manual_link": args.manual_link,
        "tone_preference": args.tone,
        "api_provider": args.api_provider,
        "api_key": args.api_key,
        "api_base_url": args.api_base_url,
        "api_model": args.api_model
    }
    
    print("=" * 60)
    print(f"Uruchamianie generowania dla: {args.product_name}")
    print("=" * 60)
    
    try:
        result = run_generation_pipeline(user_inputs)
        
        print("\nSUCCESS! Wygenerowano opis i metadane.")
        print("-" * 60)
        print(f"Nazwa produktu:  {result['product_name']}")
        print(f"Oryginalny tyt.: {result['original_title']}")
        print(f"Tryb:            {'Przedsprzedaż' if result['is_preorder'] else 'Standard'}")
        if result['is_preorder']:
            print(f"Premiera:        {result['release_date_note']}")
            
        print("\nTytuł SEO:")
        print(f"  {result['seo_title']}")
        
        print("\nMeta opis:")
        print(f"  {result['meta_description']}")
        
        print("\nOpis skrócony:")
        print(f"  {result['short_description']}")
        
        print("\nTagi:")
        print(f"  {', '.join(result['tags'])}")
        
        print("\nDane techniczne:")
        for k, v in result['additional_info'].items():
            print(f"  - {k}: {v}")
            
        print("\nZawartość pudełka:")
        for item in result['box_contents']:
            print(f"  - {item}")
            
        print("\nŹródła:")
        for src in result['sources']:
            print(f"  - [{src['source_type']}] {src['url']}")
            
        if result['warnings']:
            print("\nOSTRZEŻENIA / UWAGI:")
            for warn in result['warnings']:
                print(f"  [!] {warn}")
        else:
            print("\nBrak ostrzeżeń.")
            
        print("-" * 60)
        print("Wszystkie pliki zostały zapisane w katalogu 'output/'.")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Error running CLI pipeline: {e}")
        print(f"\nBłąd podczas uruchamiania: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
