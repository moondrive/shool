"""
Модуль автономной AI-редакции.
Агентная цепочка: Planner -> Searcher -> Scraper -> Editor.
Нейросеть сама ищет информацию в интернете и пишет на её основе пост.
"""

import re
import time
import logging

from google import genai
from duckduckgo_search import DDGS
from newspaper import Article

from cfg import GEMINI_API_KEY

# ─── Настройка логирования ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Инициализация Gemini ────────────────────────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

# Список моделей: если первая вернёт 429, попробуем следующую
MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]


def _call_gemini(prompt: str, max_retries: int = 3) -> str:
    """
    Вызывает Gemini с автоматическим retry и fallback на другие модели.
    При ошибке 429 ждёт 30 секунд и пробует снова / другую модель.
    """
    for model_name in MODELS:
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("📡 Запрос к %s (попытка %d)...", model_name, attempt)
                response = client.models.generate_content(
                    model=model_name, contents=prompt
                )
                return response.text.strip()
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 30 * attempt
                    logger.warning(
                        "⏳ Квота исчерпана для %s. Жду %dс...", model_name, wait
                    )
                    time.sleep(wait)
                else:
                    raise
        logger.warning("⚠️ Все попытки для %s исчерпаны, пробую следующую модель...", model_name)

    raise RuntimeError("Все модели Gemini вернули ошибку квоты. Попробуйте позже.")

# ─── Системные промпты (роли нейросети) ──────────────────────────────────────

PLANNER_PROMPT = (
    "Ты — шеф-редактор новостного канала. "
    "Твоя задача — придумать 1 актуальный поисковый запрос на тему, "
    "которую тебе дадут. Верни ТОЛЬКО текст запроса, "
    "без кавычек и лишних слов."
)

EDITOR_PROMPT = (
    "Ты — профессиональный Telegram-копирайтер. "
    "На основе предоставленного сырого текста напиши увлекательный пост. "
    "Используй эмодзи, абзацы и сделай цепляющий заголовок. "
    "Опирайся ТОЛЬКО на предоставленный текст, не выдумывай факты. "
    "Пост должен быть на русском языке."
)

# ─── Домены, которые нужно отфильтровать ─────────────────────────────────────
BLOCKED_DOMAINS = (
    "youtube.com", "youtu.be",
    "facebook.com", "instagram.com",
    "twitter.com", "x.com",
    "tiktok.com", "vk.com",
    "t.me", "reddit.com",
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PLANNER — генерация поискового запроса
# ═══════════════════════════════════════════════════════════════════════════════

def get_search_query(topic: str) -> str:
    """
    Отправляет тему в Gemini 1.5 Flash и получает узкий поисковый запрос.

    Args:
        topic: Общая тема (например, «Нейросети» или «Космос»).

    Returns:
        Строка с поисковым запросом для поисковика.
    """
    logger.info("🔍 Planner: генерирую поисковый запрос для темы «%s»...", topic)

    prompt = f"{PLANNER_PROMPT}\n\nТема: {topic}"
    raw = _call_gemini(prompt)
    query = raw.strip('"').strip("'")

    logger.info("✅ Planner вернул запрос: «%s»", query)
    return query


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SEARCHER — поиск ссылок через DuckDuckGo
# ═══════════════════════════════════════════════════════════════════════════════

def search_google(query: str) -> list:
    """
    Ищет в DuckDuckGo по запросу и возвращает 3-5 ссылок на текстовые сайты.
    Фильтрует YouTube, соцсети и прочие нетекстовые ресурсы.

    Args:
        query: Поисковый запрос.

    Returns:
        Список URL-адресов (до 5 штук).
    """
    logger.info("🌐 Searcher: ищу по запросу «%s»...", query)

    urls = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
            for r in results:
                url = r.get("href", "")
                # Фильтруем заблокированные домены
                if any(domain in url.lower() for domain in BLOCKED_DOMAINS):
                    continue
                urls.append(url)
                if len(urls) >= 5:
                    break
    except Exception as e:
        logger.error("❌ Ошибка поиска: %s", e)

    logger.info("✅ Searcher нашёл %d ссылок: %s", len(urls), urls)
    return urls


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SCRAPER — извлечение текста из статей
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_articles(urls: list) -> str:
    """
    Скачивает страницы и извлекает чистый текст статей через newspaper3k.
    Склеивает тексты в одну строку. Если сайт блокирует — пропускает.

    Args:
        urls: Список URL-адресов статей.

    Returns:
        Длинная строка со склеенным текстом (сырой текст для базы фактов).
    """
    logger.info("📰 Scraper: начинаю парсинг %d статей...", len(urls))

    all_texts = []

    for url in urls:
        try:
            article = Article(url, language="ru")
            article.download()
            article.parse()

            text = article.text.strip()
            if len(text) < 100:
                logger.warning("⚠️ Слишком мало текста с %s, пропускаю", url)
                continue

            # Ограничиваем текст одной статьи (макс. 3000 символов)
            all_texts.append(text[:3000])
            logger.info("✅ Получил текст с %s (%d символов)", url, len(text))

        except Exception as e:
            logger.warning("⚠️ Не удалось скачать %s: %s", url, e)
            continue

    combined = "\n\n---\n\n".join(all_texts)
    logger.info("📦 Scraper собрал %d текстов, итого %d символов",
                len(all_texts), len(combined))
    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# 4. EDITOR — написание итогового поста
# ═══════════════════════════════════════════════════════════════════════════════

def generate_final_post(raw_text: str) -> str:
    """
    Отправляет сырой текст в Gemini вместе с EDITOR_PROMPT.
    Получает готовый, отформатированный Telegram-пост.

    Args:
        raw_text: Склеенный текст из нескольких статей.

    Returns:
        Готовый пост для Telegram.
    """
    logger.info("✍️ Editor: генерирую финальный пост...")

    # Ограничиваем входной текст (лимит контекста Gemini)
    trimmed = raw_text[:8000]

    prompt = f"{EDITOR_PROMPT}\n\nСырой текст:\n\n{trimmed}"
    post = _call_gemini(prompt)

    logger.info("✅ Editor сгенерировал пост (%d символов)", len(post))
    return post


# ═══════════════════════════════════════════════════════════════════════════════
# ТОЧКА СБОРКИ — главная функция модуля
# ═══════════════════════════════════════════════════════════════════════════════

def create_autonomous_post(topic: str) -> str:
    """
    Запускает полную цепочку: Planner -> Searcher -> Scraper -> Editor.

    Args:
        topic: Общая тема для поста (например, «Нейросети»).

    Returns:
        Готовый отформатированный пост или сообщение об ошибке.
    """
    logger.info("🚀 Запуск автономной генерации поста на тему «%s»", topic)

    try:
        # 1. Planner: тема → поисковый запрос
        query = get_search_query(topic)

        # 2. Searcher: запрос → ссылки
        urls = search_google(query)
        if not urls:
            return "❌ Ошибка: не удалось найти статьи по запросу."

        # 3. Scraper: ссылки → сырой текст
        raw_materials = scrape_articles(urls)
        if not raw_materials:
            return "❌ Ошибка: не удалось собрать информацию со статей."

        # 4. Editor: сырой текст → готовый пост
        final_post = generate_final_post(raw_materials)
        logger.info("🎉 Пост успешно сгенерирован!")
        return final_post

    except Exception as e:
        logger.error("💥 Критическая ошибка в цепочке: %s", e)
        return f"❌ Произошла ошибка при генерации поста: {e}"


# ─── Тестовый запуск ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_topic = "Нейросети"
    result = create_autonomous_post(test_topic)
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТ:")
    print("=" * 60)
    print(result)
