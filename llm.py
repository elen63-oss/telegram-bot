import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

# Бесплатные OpenAI-совместимые API (см. github.com/cheahjs/free-llm-api-resources).
# Провайдер используется, только если задан его ключ в переменной окружения.
# Модель можно переопределить переменной <ПРОВАЙДЕР>_MODEL.
PROVIDERS = [
    {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
    },
    {
        "name": "Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
    },
    {
        "name": "Cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key_env": "CEREBRAS_API_KEY",
        "model": "llama3.1-8b",
    },
    {
        "name": "Mistral",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key_env": "MISTRAL_API_KEY",
        "model": "mistral-small-latest",
    },
]

SYSTEM_PROMPT = os.getenv(
    "LLM_SYSTEM_PROMPT",
    "Ты дружелюбный помощник Telegram-канала. Отвечай кратко и по-русски."
)


def available_providers() -> list:
    """Провайдеры, для которых задан API-ключ"""
    result = []
    for p in PROVIDERS:
        key = os.getenv(p["key_env"])
        if key:
            prefix = p["key_env"].removesuffix("_API_KEY")
            result.append({**p, "key": key, "model": os.getenv(f"{prefix}_MODEL", p["model"])})
    return result


async def ask_llm(prompt: str) -> str:
    """Запрос к LLM с переключением на следующего провайдера при ошибке"""
    providers = available_providers()
    if not providers:
        raise RuntimeError("Не задан ни один API-ключ LLM")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for p in providers:
            try:
                async with session.post(
                    p["url"],
                    headers={"Authorization": f"Bearer {p['key']}"},
                    json={"model": p["model"], "messages": messages},
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"{p['name']}: HTTP {resp.status} {await resp.text()}")
                        continue
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"{p['name']}: {str(e)}")
    raise RuntimeError("Все LLM-провайдеры недоступны")
