import csv
import json
import re
from app.config import OUTPUT_DIR
from app.logger import logger

def slugify(text: str) -> str:
    """
    Convert text to a clean slug: lowercase, replace Polish characters, 
    replace non-alphanumeric with hyphens, remove duplicate hyphens.
    """
    if not text:
        return "product"
        
    text = text.lower().strip()
    
    # Replace Polish characters
    replacements = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z"
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
        
    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    # Replace whitespace with hyphens
    text = re.sub(r"[\s-]+", "-", text)
    # Remove leading/trailing hyphens
    text = text.strip("-")
    
    return text

def export_results(product_data: dict) -> str:
    """
    Exports product description data into JSON, HTML, TXT, and CSV files in the output directory.
    
    Returns:
        The generated slug (filename prefix).
    """
    name = product_data.get("product_name", "product")
    slug = slugify(name)
    
    # Paths
    json_path = OUTPUT_DIR / f"{slug}.json"
    html_path = OUTPUT_DIR / f"{slug}.html"
    txt_path = OUTPUT_DIR / f"{slug}.txt"
    csv_path = OUTPUT_DIR / f"{slug}.csv"
    
    try:
        # 1. Export JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(product_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Exported JSON to: {json_path}")
        
        # 2. Export HTML
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(product_data.get("extended_description_html", ""))
        logger.info(f"Exported HTML to: {html_path}")
        
        # 3. Export TXT (Human-readable summary)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"NAZWA PRODUKTU: {product_data.get('product_name')}\n")
            f.write(f"ORYGINALNY TYTUŁ: {product_data.get('original_title')}\n")
            f.write(f"TRYB: {'Przedsprzedaż' if product_data.get('is_preorder') else 'Standard'}\n")
            f.write(f"ORIENTACYJNA PREMIERA: {product_data.get('release_date_note')}\n\n")
            f.write(f"OPIS SKRÓCONY:\n{product_data.get('short_description')}\n\n")
            f.write(f"TYTUŁ SEO:\n{product_data.get('seo_title')}\n\n")
            f.write(f"META OPIS:\n{product_data.get('meta_description')}\n\n")
            tags_str = ", ".join(product_data.get("tags", []))
            f.write(f"TAGI:\n{tags_str}\n\n")
            
            # Additional info
            f.write("DANE TECHNICZNE:\n")
            info = product_data.get("additional_info", {})
            for k, v in info.items():
                f.write(f"- {k}: {v}\n")
                
            f.write("\nZAWARTOŚĆ PUDEŁKA:\n")
            for item in product_data.get("box_contents", []):
                f.write(f"- {item}\n")
                
            f.write("\nŹRÓDŁA:\n")
            for src in product_data.get("sources", []):
                f.write(f"- [{src.get('source_type')}] {src.get('url')} (Znalezione fakty: {', '.join(src.get('facts_found', []))})\n")
                
            f.write("\nOSTRZEŻENIA:\n")
            for warn in product_data.get("warnings", []):
                f.write(f"- {warn}\n")
        logger.info(f"Exported TXT to: {txt_path}")
        
        # 4. Export CSV (Key-value pairs for technical info)
        info = product_data.get("additional_info", {})
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Parametr", "Wartość"])
            writer.writerow(["product_name", product_data.get("product_name")])
            writer.writerow(["original_title", product_data.get("original_title")])
            writer.writerow(["is_preorder", str(product_data.get("is_preorder"))])
            writer.writerow(["release_date_note", product_data.get("release_date_note")])
            
            # Write additional info fields
            for k, v in info.items():
                writer.writerow([k, v])
        logger.info(f"Exported CSV to: {csv_path}")
        
        return slug
        
    except Exception as e:
        logger.error(f"Error exporting results for {name}: {e}")
        raise e
