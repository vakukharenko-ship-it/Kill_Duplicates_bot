import asyncio
import os
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message
import aiohttp
from bs4 import BeautifulSoup

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан")

bot = Bot(token=TOKEN)
dp = Dispatcher()

OZON_COOKIE = os.getenv("OZON_COOKIE", "")

async def fetch_competitors(sku: str):
    url = f"https://www.ozon.ru/product/{sku}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if OZON_COOKIE:
        headers["Cookie"] = OZON_COOKIE

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            html = await response.text()

    soup = BeautifulSoup(html, "lxml")
    sellers = []

    # Пробуем разные селекторы (может меняться со временем)
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

    # Убираем дубли по имени
    seen = set()
    unique = []
    for s in sellers:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)
    return unique

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет! Я помогу найти конкурентов на Ozon.\n"
        "Отправь мне SKU товара (один или несколько через запятую или пробел), и я найду всех продавцов.\n\n"
        "Пример: 1276394240, 3129449681"
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
