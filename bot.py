import asyncio
import os
import re
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiohttp
from aiohttp_socks import ProxyConnector, ProxyConnectionError
from bs4 import BeautifulSoup

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Прокси (формат: socks5://логин:пароль@хост:порт)
PROXY_URL = os.getenv("PROXY_URL", "")

# Клавиатура с кнопкой "Старт"
start_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🚀 Старт")]],
    resize_keyboard=True
)

# Заголовки для HTML (максимально браузерные)
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.ozon.ru/",
}

# Заголовки для API
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://www.ozon.ru",
    "Referer": "https://www.ozon.ru/",
}

def create_connector():
    """Создаёт SOCKS5 коннектор с логированием."""
    if not PROXY_URL:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(PROXY_URL)
        if parsed.scheme != 'socks5':
            logger.warning(f"Неизвестная схема: {parsed.scheme}, пробуем как socks5")
        connector = ProxyConnector(
            proxy_type='socks5',
            host=parsed.hostname,
            port=parsed.port,
            username=parsed.username,
            password=parsed.password,
            rdns=True
        )
        logger.info(f"Прокси настроен: {parsed.hostname}:{parsed.port}")
        return connector
    except Exception as e:
        logger.error(f"Ошибка создания прокси-коннектора: {e}")
        return None

async def fetch_html(sku: str, retries: int = 3):
    """GET-запрос к странице товара через прокси."""
    url = f"https://www.ozon.ru/product/{sku}/"
    connector = create_connector()
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"HTML попытка {attempt} для SKU {sku}")
                async with session.get(url, headers=HTML_HEADERS, timeout=60) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    return await resp.text()
            except asyncio.TimeoutError:
                logger.warning(f"HTML таймаут, попытка {attempt}")
                if attempt == retries:
                    raise
                await asyncio.sleep(3 ** attempt)
            except Exception as e:
                logger.error(f"HTML ошибка: {e}")
                if attempt == retries:
                    raise
                await asyncio.sleep(3 ** attempt)
    return None

async def fetch_api(sku: str, retries: int = 3):
    """POST-запрос к API через прокси."""
    url = "https://www.ozon.ru/api/composer-api.bx/_action/getProduct"
    payload = {"productId": sku, "layout": "default", "showAll": False}
    connector = create_connector()
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"API попытка {attempt} для SKU {sku}")
                async with session.post(url, json=payload, headers=API_HEADERS, timeout=60) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    return await resp.json()
            except asyncio.TimeoutError:
                logger.warning(f"API таймаут, попытка {attempt}")
                if attempt == retries:
                    raise
                await asyncio.sleep(3 ** attempt)
            except Exception as e:
                logger.error(f"API ошибка: {e}")
                if attempt == retries:
                    raise
                await asyncio.sleep(3 ** attempt)
    return None

def parse_html(html: str, sku: str):
    """Парсит HTML-страницу и извлекает продавцов."""
    soup = BeautifulSoup(html, "lxml")
    sellers = []
    # Пробуем селекторы
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
                "link": f"https://www.ozon.ru/product/{sku}/"
            })
    # Убираем дубли
    seen = set()
    unique = []
    for s in sellers:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)
    return unique

def parse_api(data: dict, sku: str):
    """Парсит JSON-ответ API."""
    sellers = []
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
    return sellers

async def fetch_competitors(sku: str):
    """Сначала пробуем HTML (GET), если нет – API (POST)."""
    # Попытка HTML
    try:
        html = await fetch_html(sku)
        if html:
            sellers = parse_html(html, sku)
            if sellers:
                return sellers
            logger.info(f"HTML не дал продавцов для {sku}")
    except Exception as e:
        logger.warning(f"HTML не удался для {sku}: {e}")

    # Если HTML не помог, пробуем API
    try:
        data = await fetch_api(sku)
        if data:
            sellers = parse_api(data, sku)
            if sellers:
                return sellers
            logger.info(f"API не дал продавцов для {sku}")
    except Exception as e:
        logger.warning(f"API не удался для {sku}: {e}")

    # Если ничего не помогло
    raise Exception("Не удалось получить данные ни через HTML, ни через API")

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет! Я помогу найти конкурентов на Ozon.\n"
        "Отправь мне SKU товара (один или несколько через запятую или пробел), и я найду всех продавцов.\n\n"
        "Пример: 1276394240, 3129449681\n\n"
        "⚠️ Бот работает через прокси, поэтому не требует кук.",
        reply_markup=start_keyboard
    )

@dp.message()
async def handle_text(message: Message):
    text = message.text.strip()
    if not text:
        return

    if text == "🚀 Старт":
        await start_cmd(message)
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
            answer_lines.append(f"🛒 SKU {item['sku']}: <b>{count}</b> конкурентов")
            if count:
                for i, comp in enumerate(item["competitors"], 1):
                    name_safe = comp['name'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    answer_lines.append(
                        f"   {i}. <a href='{comp['link']}'>{name_safe}</a> — {comp['price']} ₽, SKU: {comp['sku'] or 'нет'}"
                    )
            else:
                answer_lines.append("   ➖ Конкурентов не найдено.")
        answer_lines.append("")

    full_answer = "\n".join(answer_lines)
    if not full_answer.strip():
        full_answer = "⚠️ Не удалось найти информацию."

    if len(full_answer) > 4000:
        chunks = [full_answer[i:i+4000] for i in range(0, len(full_answer), 4000)]
        for chunk in chunks:
            await message.answer(chunk, parse_mode="HTML", reply_markup=start_keyboard)
    else:
        await message.answer(full_answer, parse_mode="HTML", reply_markup=start_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
