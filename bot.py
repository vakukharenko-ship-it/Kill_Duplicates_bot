import asyncio
import os
import re
import logging
from urllib.parse import urlparse
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
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

# Прокси – может быть в формате:
# http://user:pass@host:port
# или host:port:user:pass (наш случай)
PROXY_RAW = os.getenv("PROXY_URL", "")

# Преобразуем прокси в формат http://user:pass@host:port
def normalize_proxy(raw):
    if not raw:
        return None
    raw = raw.strip()
    # Если уже начинается с http:// или https://, оставляем как есть
    if raw.startswith(("http://", "https://")):
        return raw
    # Убираем "HTTP://" или "HTTPS://" если есть
    if raw.upper().startswith("HTTP://"):
        raw = raw[7:]
    elif raw.upper().startswith("HTTPS://"):
        raw = raw[8:]
    # Пытаемся распарсить host:port:user:pass
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return f"http://{user}:{passwd}@{host}:{port}"
    # Если не получилось, возвращаем как есть (может, уже правильный)
    return raw

PROXY_URL = normalize_proxy(PROXY_RAW)

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

async def fetch_html(sku: str, retries: int = 3):
    """GET-запрос к странице товара через прокси."""
    url = f"https://www.ozon.ru/product/{sku}/"
    async with aiohttp.ClientSession() as session:
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"HTML попытка {attempt} для SKU {sku}")
                async with session.get(url, headers=HTML_HEADERS, proxy=PROXY_URL, timeout=30) as resp:
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

async def fetch_competitors(sku: str):
    """Получает данные через HTML."""
    html = await fetch_html(sku)
    if not html:
        raise Exception("Не удалось загрузить страницу")
    sellers = parse_html(html, sku)
    if not sellers:
        logger.info(f"Для SKU {sku} не найдено продавцов")
    return sellers

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет! Я помогу найти конкурентов на Ozon.\n"
        "Отправь мне SKU товара (один или несколько через запятую или пробел), и я найду всех продавцов.\n\n"
        "Пример: 1276394240, 3129449681\n\n"
        f"🔧 Прокси: {'включён' if PROXY_URL else 'выключен'}",
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
