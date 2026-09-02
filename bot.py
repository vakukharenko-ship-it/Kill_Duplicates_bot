import asyncio
import os
import re
import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message
import aiohttp
from bs4 import BeautifulSoup

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан")

bot = Bot(token=TOKEN)
dp = Dispatcher()

OZON_COOKIE = os.getenv("OZON_COOKIE", "")

# Прокси (если нужно) – можно задать через переменную PROXY_URL
PROXY_URL = os.getenv("PROXY_URL", None)

# Заголовки для API
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://www.ozon.ru",
    "Referer": "https://www.ozon.ru/",
}

async def fetch_competitors_api(sku: str, retries: int = 2):
    """
    Пытаемся получить данные через API Ozon (JSON).
    """
    url = "https://www.ozon.ru/api/composer-api.bx/_action/getProduct"
    payload = {
        "productId": sku,
        "layout": "default",
        "showAll": False
    }
    headers = API_HEADERS.copy()
    if OZON_COOKIE:
        headers["Cookie"] = OZON_COOKIE

    async with aiohttp.ClientSession() as session:
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"API попытка {attempt} для SKU {sku}")
                async with session.post(url, json=payload, headers=headers, proxy=PROXY_URL, timeout=20) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    data = await resp.json()
                    # Парсим продавцов из JSON
                    sellers = []
                    # Структура может меняться, ищем блок offers
                    offers = data.get("offers", []) or data.get("product", {}).get("offers", [])
                    for offer in offers:
                        seller_name = offer.get("sellerName") or offer.get("seller", {}).get("name")
                        price = offer.get("price") or offer.get("priceValue")
                        if seller_name and price:
                            sellers.append({
                                "name": seller_name,
                                "price": str(price),
                                "sku": offer.get("sku") or offer.get("sellerSku"),
                                "link": f"https://www.ozon.ru/product/{sku}/"
                            })
                    if not sellers:
                        # Попробуем найти в другом месте
                        product = data.get("product", {})
                        for offer in product.get("offers", []):
                            seller_name = offer.get("sellerName")
                            price = offer.get("price")
                            if seller_name and price:
                                sellers.append({
                                    "name": seller_name,
                                    "price": str(price),
                                    "sku": offer.get("sku"),
                                    "link": f"https://www.ozon.ru/product/{sku}/"
                                })
                    return sellers
            except asyncio.TimeoutError:
                logger.warning(f"API таймаут для SKU {sku}, попытка {attempt}")
                if attempt == retries:
                    raise Exception("Таймаут при запросе к API")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"API ошибка для SKU {sku}: {e}")
                if attempt == retries:
                    raise
                await asyncio.sleep(2 ** attempt)
    return []

async def fetch_competitors_fallback(sku: str):
    """
    Запасной вариант – парсинг HTML (если API не сработал).
    """
    url = f"https://www.ozon.ru/product/{sku}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if OZON_COOKIE:
        headers["Cookie"] = OZON_COOKIE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy=PROXY_URL, timeout=20) as resp:
            if resp.status != 200:
                raise Exception(f"HTML HTTP {resp.status}")
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")
    sellers = []
    price_blocks = soup.select('[data-widget="webPrice"] [data-qa="price-block"]')
    if not price_blocks:
        price_blocks = soup.select('.c6a0, .c9a0')

    for block in price_blocks:
        seller_elem = block.find(attrs={"data-qa": "seller-name"}) or block.find(class_="seller-link")
        if not seller_elem:
            continue
        seller_name = seller_elem.get_text(strip=True)
        price_elem = block.find(attrs={"data-qa": "price"}) or block.find(class_="price-block")
        if not price_elem:
            continue
        price_text = price_elem.get_text(strip=True)
        price_digits = re.sub(r"[^\d]", "", price_text)
        if seller_name and price_digits:
            sellers.append({
                "name": seller_name,
                "price": price_digits,
                "sku": None,
                "link": url
            })

    # Убираем дубли
    seen = set()
    unique = []
    for s in sellers:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)
    return unique

async def fetch_competitors(sku: str):
    """
    Основная функция: сначала API, если ошибка – fallback HTML.
    """
    try:
        sellers = await fetch_competitors_api(sku)
        if sellers:
            return sellers
        # Если API вернул пустой список, пробуем HTML
        logger.info(f"API вернул пусто для {sku}, пробуем HTML")
        return await fetch_competitors_fallback(sku)
    except Exception as e:
        logger.warning(f"API не удался для {sku}: {e}, пробуем HTML")
        try:
            return await fetch_competitors_fallback(sku)
        except Exception as e2:
            raise Exception(f"Не удалось получить данные ни через API, ни через HTML: {e2}")

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет! Я помогу найти конкурентов на Ozon.\n"
        "Отправь мне SKU товара (один или несколько через запятую или пробел), и я найду всех продавцов.\n\n"
        "Пример: 1276394240, 3129449681\n\n"
        "⚠️ Если бот выдаёт ошибку 403 – нужно добавить куки сессии Ozon.\n"
        "Инструкция: https://telegra.ph/Kak-poluchit-kuki-Ozon-03-04 (или я пришлю позже)."
    )

@dp.message()
async def handle_text(message: Message):
    text = message.text.strip()
    if not text:
        return

    skus = re.findall(r"\b\d{7,12}\b", text)
    if not skus:
        await message.answer("❌ Не найдено ни одного корректного SKU (нужны цифры, 7-12 знаков).")
        return

    await message.answer(f"🔍 Начинаю поиск для {len(skus)} SKU... Это может занять несколько секунд.")

    results = []
    for sku in skus:
        try:
            comps = await fetch_competitors(sku)
            results.append({"sku": sku, "competitors": comps, "error": None})
        except Exception as e:
            results.append({"sku": sku, "competitors": [], "error": str(e)})

    answer_lines = []
    for item in results:
        if item["error"]:
            answer_lines.append(f"❌ SKU {item['sku']}: ошибка — {item['error']}")
        else:
            count = len(item["competitors"])
            answer_lines.append(f"🛒 SKU {item['sku']}: *{count}* конкурентов")
            if count:
                for i, comp in enumerate(item["competitors"], 1):
                    answer_lines.append(f"   {i}. [{comp['name']}]({comp['link']}) — {comp['price']} ₽, SKU: {comp['sku'] or 'нет'}")
            else:
                answer_lines.append("   ➖ Конкурентов не найдено.")
        answer_lines.append("")

    full_answer = "\n".join(answer_lines)
    if len(full_answer) > 4000:
        chunks = [full_answer[i:i+4000] for i in range(0, len(full_answer), 4000)]
        for chunk in chunks:
            await message.answer(chunk, parse_mode="Markdown")
    else:
        await message.answer(full_answer, parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
