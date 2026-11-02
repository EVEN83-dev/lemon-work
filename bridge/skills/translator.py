from .models import SkillResult

METADATA = {
    "name": "translator",
    "version": "1.0.0",
    "category": "communication",
    "description": "Translate text between languages using LLM engine. Fallback to local dictionary.",
    "risk_level": "safe",
    "dependencies": ["engine_manager"],
}

_LOCAL_DICT = {
    "hello": {"zh": "你好", "ja": "こんにちは", "ko": "안녕하세요", "fr": "Bonjour", "de": "Hallo", "es": "Hola"},
    "thank you": {"zh": "谢谢", "ja": "ありがとうございます", "ko": "감사합니다", "fr": "Merci", "de": "Danke", "es": "Gracias"},
    "goodbye": {"zh": "再见", "ja": "さようなら", "ko": "안녕히 가세요", "fr": "Au revoir", "de": "Auf Wiedersehen", "es": "Adiós"},
    "yes": {"zh": "是", "ja": "はい", "ko": "네", "fr": "Oui", "de": "Ja", "es": "Sí"},
    "no": {"zh": "不", "ja": "いいえ", "ko": "아니요", "fr": "Non", "de": "Nein", "es": "No"},
}


def execute(text: str, target_lang: str = "zh", **kwargs) -> SkillResult:
    if not text or not text.strip():
        return SkillResult.fail("No text provided for translation")

    lower_text = text.strip().lower()

    if lower_text in _LOCAL_DICT:
        mapping = _LOCAL_DICT[lower_text]
        translated = mapping.get(target_lang, mapping.get("zh", text))
        return SkillResult.ok(
            output=translated,
            data={"original": text, "translated": translated, "from": "local_dict", "to": target_lang}
        )

    engine_manager = kwargs.get("engine_manager")
    if engine_manager:
        try:
            prompt = f"Translate the following text to {target_lang}. Only output the translation, nothing else:\n\n{text}"
            result = engine_manager.agent_chat(prompt, use_agent=False)
            if result and isinstance(result, dict):
                translated = result.get("content", "")
                if translated:
                    return SkillResult.ok(
                        output=translated,
                        data={"original": text, "translated": translated, "from": "llm", "to": target_lang}
                    )
        except Exception as e:
            pass

    return SkillResult.fail(
        f"Translation service unavailable for '{text}'. LLM engine not connected and no local match found.",
        data={"original": text, "fallback": "Translation requires LLM engine or local dictionary match"}
    )
