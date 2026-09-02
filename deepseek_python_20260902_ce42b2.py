import asyncio
import os
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message
import aiohttp
from bs4 import BeautifulSoup

# Токен бота – будет браться из переменной окружения BOT_TOKEN
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Не задан BOT_TOKEN в переменных окружения")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Дополнительные куки (опционально) – берём из переменной OZON_COOKIE
OZON_COOKIE = os.getenv("OZON_COOKIE", "")

async def fetch_competitors(sku: str):
    """
    Парсит страницу товара на Ozon и возвращает список конкурентов (продавцов).
    """
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
                raise Exception(f"Ошибка HTTP {response.status}")
            html = await response.text()

    soup = BeautifulSoup(html, "lxml")
    sellers = []

    # Первый вариант: блок с ценой от других продавцов (селекторы могут меняться)
    price_blocks = soup.select('[data-widget="webPrice"] [data-qa="price-block"]')
    if not price_blocks:
        # Если не нашли – пробуем другие популярные классы
        price_blocks = soup.select('.c6a0, .c9a0')

    for block in price_blocks:
        # Ищем название продавца
        seller_elem = block.find(attrs={"data-qa": "seller-name"}) or block.find(class_="seller-link")
        if not seller_elem:
            continue
        seller_name = seller_elem.get_text(strip=True)
        # Ищем цену
        price_elem = block.find(attrs={"data-qa": "price"}) or block.find(class_="price-block")
        if not price_elem:
            continue
        price_text = price_elem.get_text(strip=True)
        # Извлекаем цифры из цены
        price_digits = re.sub(r"[^\d]", "", price_text)
        if seller_name and price_digits:
            sellers.append({
                "name": seller_name,
                "price": price_digits,
                "sku": None,  # SKU конкурента не всегда доступен
                "link": url
            })

    # Убираем дубликаты по имени продавца
    unique = []
    seen = set()
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
        "Пример: 1276394240, 3129449681\n"
        "Или загрузи файл .xlsx с колонкой 'SKU' (в разработке)."
    )

@dp.message()
async def handle_text(message: Message):
    text = message.text.strip()
    if not text:
        return

    # Разбиваем текст на SKU (числа от 7 до 12 цифр)
    skus = re.findall(r"\b\d{7,12}\b", text)
    if not skus:
        await message.answer("❌ Не найдено ни одного корректного SKU (нужны цифры, 7-12 знаков).")
        return

    await message.answer(f"🔍 Начинаю поиск для {len(skus)} SKU... Это может занять несколько секунд.")

    results = []
    for sku in skus:
        try:
            competitors = await fetch_competitors(sku)
            results.append({"sku": sku, "competitors": competitors, "error": None})
        except Exception as e:
            results.append({"sku": sku, "competitors": [], "error": str(e)})

    # Формируем ответ (с разметкой Markdown)
    answer_parts = []
    for item in results:
        if item["error"]:
            answer_parts.append(f"❌ SKU {item['sku']}: ошибка — {item['error']}")
        else:
            count = len(item["competitors"])
            answer_parts.append(f"🛒 SKU {item['sku']}: *{count}* конкурентов")
            if count:
                for i, comp in enumerate(item["competitors"], 1):
                    answer_parts.append(f"   {i}. [{comp['name']}]({comp['link']}) — {comp['price']} ₽, SKU: {comp['sku'] or 'нет'}")
            else:
                answer_parts.append("   ➖ Конкурентов не найдено.")
        answer_parts.append("")  # пустая строка между товарами

    full_answer = "\n".join(answer_parts)
    # Если ответ слишком длинный (>4000 символов), разбиваем
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