from app.config import (
    LLM_PROVIDER,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    LLM_MODEL,
    ZAI_API_KEY,
    ZAI_BASE_URL,
    ZAI_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
)
from app.logger import logger

class LLMError(Exception):
    pass

ZAI_PROVIDER_ALIASES = {"z_ai", "zai", "z.ai", "z-ai"}
DEEPSEEK_PROVIDER_ALIASES = {"deepseek", "deep_seek", "deep-seek"}

def _normalize_provider(provider: str) -> str:
    selected = (provider or LLM_PROVIDER or "gemini").strip().lower()
    if selected in ZAI_PROVIDER_ALIASES:
        return "z_ai"
    if selected in DEEPSEEK_PROVIDER_ALIASES:
        return "deepseek"
    if selected == "custom":
        return "openai"
    return selected

def _format_provider_error(provider_label: str, error: Exception) -> str:
    detail = str(error)

    response = getattr(error, "response", None)
    if response is not None:
        try:
            payload = response.json()
            provider_error = payload.get("error", {})
            code = str(provider_error.get("code", ""))
            message = provider_error.get("message", "")
            if provider_label == "Z.AI" and code == "1113":
                return (
                    "Z.AI odrzuciło żądanie: brak środków albo aktywnego pakietu zasobów "
                    "dla tego klucza API. Doładuj konto w Z.AI/Billing lub aktywuj odpowiedni pakiet. "
                    f"Szczegóły API: {message or detail}"
                )
        except Exception:
            pass

    if provider_label == "Z.AI" and "Insufficient balance or no resource package" in detail:
        return (
            "Z.AI odrzuciło żądanie: brak środków albo aktywnego pakietu zasobów "
            "dla tego klucza API. Doładuj konto w Z.AI/Billing lub aktywuj odpowiedni pakiet."
        )

    if provider_label == "DeepSeek" and ("Insufficient Balance" in detail or "insufficient balance" in detail.lower()):
        return "DeepSeek odrzucił żądanie: brak środków na koncie API. Doładuj konto w DeepSeek Platform."

    return f"Błąd podczas generowania przez {provider_label} API: {detail}"

def generate_text(
    prompt: str, 
    system_instruction: str = None, 
    json_mode: bool = False,
    api_key: str = None,
    provider: str = None,
    base_url: str = None,
    model_name: str = None
) -> str:
    """
    Generates text using the configured LLM provider.
    Supports Gemini, OpenAI, and OpenAI-compatible endpoints such as Z.AI.
    """
    selected_provider = _normalize_provider(provider)
    selected_key = api_key
    
    # Resolve API Key
    if not selected_key:
        if selected_provider == "gemini":
            selected_key = GEMINI_API_KEY
        elif selected_provider == "z_ai":
            selected_key = ZAI_API_KEY
        elif selected_provider == "deepseek":
            selected_key = DEEPSEEK_API_KEY
        else:
            selected_key = OPENAI_API_KEY
            
    # Resolve fallback if key is missing and config supports it
    if selected_provider == "gemini" and not selected_key:
        fallback_key = api_key or DEEPSEEK_API_KEY or ZAI_API_KEY or OPENAI_API_KEY
        if fallback_key:
            selected_provider = "deepseek" if DEEPSEEK_API_KEY else "z_ai" if ZAI_API_KEY else "openai"
            selected_key = fallback_key
            logger.info("GEMINI_API_KEY is missing. Switching to OpenAI-compatible provider.")
        else:
            raise LLMError("Brak klucza API. Ustaw GEMINI_API_KEY, DEEPSEEK_API_KEY, ZAI_API_KEY lub OPENAI_API_KEY w pliku .env")
            
    elif selected_provider == "openai" and not selected_key:
        fallback_key = api_key or DEEPSEEK_API_KEY or ZAI_API_KEY or GEMINI_API_KEY
        if fallback_key:
            selected_key = fallback_key
            selected_provider = "deepseek" if DEEPSEEK_API_KEY else "z_ai" if ZAI_API_KEY else "gemini"
            logger.info("OPENAI_API_KEY is missing. Switching to another configured provider.")
        else:
            raise LLMError("Brak klucza API. Ustaw OPENAI_API_KEY, DEEPSEEK_API_KEY, ZAI_API_KEY lub GEMINI_API_KEY w pliku .env")

    elif selected_provider == "z_ai" and not selected_key:
        raise LLMError("Brak klucza API. Ustaw ZAI_API_KEY w pliku .env albo wpisz klucz w formularzu.")

    elif selected_provider == "deepseek" and not selected_key:
        raise LLMError("Brak klucza API. Ustaw DEEPSEEK_API_KEY w pliku .env albo wpisz klucz w formularzu.")

    # Call specific provider generator
    if selected_provider == "gemini":
        return _generate_gemini(
            prompt, system_instruction, json_mode, 
            api_key=selected_key, model=model_name
        )
    elif selected_provider == "openai":
        return _generate_openai(
            prompt, system_instruction, json_mode, 
            api_key=selected_key, base_url=base_url, model=model_name
        )
    elif selected_provider == "z_ai":
        return _generate_openai(
            prompt, system_instruction, json_mode,
            api_key=selected_key,
            base_url=base_url or ZAI_BASE_URL,
            model=model_name or ZAI_MODEL,
            provider_label="Z.AI"
        )
    elif selected_provider == "deepseek":
        return _generate_openai(
            prompt, system_instruction, json_mode,
            api_key=selected_key,
            base_url=base_url or DEEPSEEK_BASE_URL,
            model=model_name or DEEPSEEK_MODEL,
            provider_label="DeepSeek"
        )
    else:
        raise LLMError(f"Nieznany dostawca LLM: {selected_provider}. Wybierz 'gemini', 'openai', 'z_ai' lub 'deepseek'.")

def _generate_gemini(
    prompt: str, 
    system_instruction: str = None, 
    json_mode: bool = False,
    api_key: str = None,
    model: str = None
) -> str:
    try:
        import google.generativeai as genai
    except ImportError:
        raise LLMError("Biblioteka 'google-generativeai' nie jest zainstalowana. Zainstaluj requirements.txt")

    key = api_key or GEMINI_API_KEY
    if not key:
        raise LLMError("Klucz GEMINI_API_KEY nie został podany.")

    try:
        genai.configure(api_key=key)
        
        # Use provided model or default to gemini-1.5-flash
        selected_model = model or LLM_MODEL or "gemini-1.5-flash"
        
        generation_config = {}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"
            
        model_obj = genai.GenerativeModel(
            model_name=selected_model,
            generation_config=generation_config,
            system_instruction=system_instruction
        )
        
        logger.info(f"Sending prompt to Gemini ({selected_model})...")
        response = model_obj.generate_content(prompt)
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini generation error: {e}")
        raise LLMError(f"Błąd podczas generowania przez Gemini: {str(e)}")

def _generate_openai(
    prompt: str, 
    system_instruction: str = None, 
    json_mode: bool = False,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    provider_label: str = "OpenAI-compatible"
) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise LLMError("Biblioteka 'openai' nie jest zainstalowana. Zainstaluj requirements.txt")

    key = api_key or OPENAI_API_KEY
    if not key:
        raise LLMError("Klucz API nie został podany dla dostawcy OpenAI-compatible.")

    try:
        # Resolve base URL: override parameter -> config env -> default None (OpenAI standard)
        selected_base_url = base_url or OPENAI_BASE_URL
        
        client_kwargs = {"api_key": key}
        if selected_base_url:
            client_kwargs["base_url"] = selected_base_url
            
        client = OpenAI(**client_kwargs)
        messages = []
        
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
            
        messages.append({"role": "user", "content": prompt})
        
        # Resolve model name: override parameter -> config env -> default gpt-4o-mini
        selected_model = model or LLM_MODEL or "gpt-4o-mini"
        
        kwargs = {
            "model": selected_model,
            "messages": messages,
            "temperature": 0.7
        }
        
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            
        logger.info(f"Sending prompt to {provider_label} endpoint ({selected_model}) Base URL: {selected_base_url or 'standard OpenAI'}...")
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"{provider_label} generation error: {e}")
        raise LLMError(_format_provider_error(provider_label, e))
