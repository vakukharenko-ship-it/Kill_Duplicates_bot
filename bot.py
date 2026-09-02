import asyncio
import os
import re
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан")

bot = Bot(token=TOKEN)
dp = Dispatcher()

PROXY_RAW = os.getenv("PROXY_URL", "")

def parse_proxy(raw):
    """Разбирает прокси-строку, возвращает (url, auth) или (None, None)."""
    if not raw:
        return None, None
    raw = raw.strip()
    # Если уже http:// или https://
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        # Извлекаем логин/пароль из netloc
        if '@' in parsed.netloc:
            user_pass, host = parsed.netloc.split('@', 1)
            user, passwd = user_pass.split(':', 1) if ':' in user_pass else (user_pass, '')
            proxy_url = f"{parsed.scheme}://{host}"
            auth = aiohttp.BasicAuth(login=user, password=passwd)
            return proxy_url, auth
        else:
            return raw, None
    # Если формат host:port:user:pass
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        proxy_url = f"http://{host}:{port}"
        auth = aiohttp.BasicAuth(login=user, password=passwd)
        return proxy_url, auth
    # Если не распарсили, пробуем как есть
    return raw, None

PROXY_URL, PROXY_AUTH = parse_proxy(PROXY_RAW)
if PROXY_URL:
    logger.info(f"Прокси: включён, хост: {PROXY_URL}")
else:
    logger.info("Прокси: выключен")

start_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🚀 Старт")]],
    resize_keyboard=True
)

HEADERS = {
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
    url = f"https://www.ozon.ru/product/{sku}/"
    async with aiohttp.ClientSession() as session:
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Попытка {attempt} для SKU {sku}")
                # Если есть прокси, используем его с авторизацией
                if PROXY_URL and PROXY_AUTH:
                    async with session.get(url, headers=HEADERS, proxy=PROXY_URL, proxy_auth=PROXY_AUTH, timeout=45) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                        return await resp.text()
                elif PROXY_URL:
                    # без авторизации
                    async with session.get(url, headers=HEADERS, proxy=PROXY_URL, timeout=45) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                        return await resp.text()
                else:
                    # без прокси
                    async with session.get(url, headers=HEADERS, timeout=45) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                        return await resp.text()
            except asyncio.TimeoutError:
                logger.warning(f"Таймаут, попытка {attempt}")
                if attempt == retries:
                    raise
                await asyncio.sleep(3 ** attempt)
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if attempt == retries:
                    raise
                await asyncio.sleep(3 ** attempt)
    return None

def parse_html(html: str, sku: str):
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
    html = await fetch_html(sku)
    if not html:
        raise Exception("Не удалось загрузить страницу")
    sellers = parse_html(html, sku)
    return sellers

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет! Я ищу конкурентов на Ozon.\n"
        "Отправь SKU (число) – найду всех продавцов.\n"
        "Пример: 1276394240, 3129449681",
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
        await message.answer("❌ Нет валидных SKU (цифры, 7-12 знаков).")
        return

    await message.answer(f"🔍 Ищу для {len(skus)} SKU... Подождите.")

    results = []
    for sku in skus:
        try:
            comps = await fetch_competitors(sku)
            results.append({"sku": sku, "competitors": comps, "error": None})
        except Exception as e:
            results.append({"sku": sku, "competitors": [], "error": str(e)})

    lines = []
    for item in results:
        if item["error"]:
            lines.append(f"❌ SKU {item['sku']}: ошибка — {item['error']}")
        else:
            count = len(item["competitors"])
            lines.append(f"🛒 SKU {item['sku']}: <b>{count}</b> конкурентов")
            if count:
                for i, comp in enumerate(item["competitors"], 1):
                    name_safe = comp['name'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    lines.append(
                        f"   {i}. <a href='{comp['link']}'>{name_safe}</a> — {comp['price']} ₽"
                    )
            else:
                lines.append("   ➖ Конкурентов не найдено.")
        lines.append("")

    answer = "\n".join(lines) or "⚠️ Ничего не получено."
    if len(answer) > 4000:
        for chunk in [answer[i:i+4000] for i in range(0, len(answer), 4000)]:
            await message.answer(chunk, parse_mode="HTML", reply_markup=start_keyboard)
    else:
        await message.answer(answer, parse_mode="HTML", reply_markup=start_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
