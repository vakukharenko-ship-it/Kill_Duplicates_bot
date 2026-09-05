import datetime
import json
import os
import time
import re
import calendar
import requests
import warnings
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, ConversationHandler, CallbackQueryHandler
)
from telegram.warnings import PTBUserWarning
from telegram.helpers import escape_markdown

warnings.filterwarnings("ignore", category=PTBUserWarning)

# Графики
import matplotlib.pyplot as plt
import io
from matplotlib.dates import MonthLocator, DateFormatter
import matplotlib.dates as mdates

# ==================== КОНСТАНТЫ ====================
API_TIMEOUT = 15
API_MAX_DAYS_PER_REQUEST = 90
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2
DEBUG_SAMPLE_SIZE = 10
CACHE_TTL_SECONDS = 300  # 5 минут

# ==================== КЭШ ====================
_api_cache = {}
_cache_timestamps = {}

def get_from_cache(key):
    if key in _api_cache:
        timestamp = _cache_timestamps.get(key)
        if timestamp and (time.time() - timestamp) < CACHE_TTL_SECONDS:
            return _api_cache[key]
    return None

def save_to_cache(key, value):
    _api_cache[key] = value
    _cache_timestamps[key] = time.time()

# ==================== FIFO СИСТЕМА ====================

@dataclass
class Purchase:
    """Модель закупки товара"""
    id: str
    date: str
    offer_id: str
    product_name: str
    quantity: int
    purchase_price: float
    total_cost: float
    remaining: int

@dataclass
class FIFOBreakdown:
    """Детализация FIFO расчета"""
    purchase_id: str
    quantity: int
    unit_cost: float
    total_cost: float

@dataclass
class Sale:
    """Модель продажи товара"""
    date: str
    offer_id: str
    product_name: str
    quantity_sold: int
    sale_price: float
    total_revenue: float
    fifo_breakdown: List[FIFOBreakdown]
    total_cost_of_goods_sold: float
    gross_profit: float
    gross_margin_percent: float

# ===================== РАБОТА С ФАЙЛАМИ =====================

PURCHASES_FILE = "purchases.json"
SALES_LOG_FILE = "sales_log.json"
PRODUCT_NAMES_FILE = "product_names.json"

def load_purchases() -> List[Purchase]:
    """Загрузить все закупки"""
    if not os.path.exists(PURCHASES_FILE):
        return []
    try:
        with open(PURCHASES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [Purchase(**item) for item in data.get('purchases', [])]
    except:
        return []

def save_purchases(purchases: List[Purchase]):
    """Сохранить закупки"""
    data = {'purchases': [asdict(p) for p in purchases]}
    with open(PURCHASES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_sales_log() -> List[Sale]:
    """Загрузить историю продаж"""
    if not os.path.exists(SALES_LOG_FILE):
        return []
    try:
        with open(SALES_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            sales = []
            for item in data.get('sales', []):
                breakdowns = [FIFOBreakdown(**b) for b in item.get('fifo_breakdown', [])]
                item['fifo_breakdown'] = breakdowns
                sales.append(Sale(**item))
            return sales
    except:
        return []

def save_sales_log(sales: List[Sale]):
    """Сохранить историю продаж"""
    data = {
        'sales': [
            {
                **asdict(s),
                'fifo_breakdown': [asdict(b) for b in s.fifo_breakdown]
            }
            for s in sales
        ]
    }
    with open(SALES_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_product_names() -> Dict[str, str]:
    """Загрузить названия товаров"""
    if not os.path.exists(PRODUCT_NAMES_FILE):
        return {}
    try:
        with open(PRODUCT_NAMES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_product_names(names: Dict[str, str]):
    """Сохранить названия товаров"""
    with open(PRODUCT_NAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(names, f, ensure_ascii=False, indent=2)

# ===================== FIFO ЛОГИКА =====================

def calculate_fifo_cost(offer_id: str, quantity_sold: int) -> Tuple[float, List[FIFOBreakdown], List[Purchase]]:
    """Расчет себестоимости по методу FIFO"""
    purchases = load_purchases()
    relevant_purchases = [p for p in purchases if p.offer_id == offer_id]
    relevant_purchases.sort(key=lambda x: x.date)
    
    total_cost = 0.0
    breakdown = []
    remaining = quantity_sold
    
    for purchase in relevant_purchases:
        if remaining == 0:
            break
        available = purchase.remaining
        take = min(remaining, available)
        if take == 0:
            continue
        
        cost = take * purchase.purchase_price
        total_cost += cost
        
        breakdown.append(FIFOBreakdown(
            purchase_id=purchase.id,
            quantity=take,
            unit_cost=purchase.purchase_price,
            total_cost=cost
        ))
        
        purchase.remaining -= take
        remaining -= take
    
    save_purchases(purchases)
    return total_cost, breakdown, purchases

def add_purchase(offer_id: str, product_name: str, quantity: int, purchase_price: float, date: Optional[str] = None) -> Purchase:
    """Добавить новую закупку"""
    if date is None:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    purchases = load_purchases()
    purchase_id = f"PURCHASE_{date.replace('-', '')}_{len(purchases) + 1:03d}"
    
    new_purchase = Purchase(
        id=purchase_id,
        date=date,
        offer_id=offer_id,
        product_name=product_name,
        quantity=quantity,
        purchase_price=purchase_price,
        total_cost=quantity * purchase_price,
        remaining=quantity
    )
    
    purchases.append(new_purchase)
    save_purchases(purchases)
    
    names = load_product_names()
    names[offer_id] = product_name
    save_product_names(names)
    
    return new_purchase

def log_sale(offer_id: str, quantity_sold: int, sale_price: float, date: Optional[str] = None) -> Sale:
    """Зафиксировать продажу товара"""
    if date is None:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    total_cost_of_goods_sold, fifo_breakdown, _ = calculate_fifo_cost(offer_id, quantity_sold)
    total_revenue = quantity_sold * sale_price
    gross_profit = total_revenue - total_cost_of_goods_sold
    gross_margin_percent = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    names = load_product_names()
    product_name = names.get(offer_id, offer_id)
    
    sale = Sale(
        date=date,
        offer_id=offer_id,
        product_name=product_name,
        quantity_sold=quantity_sold,
        sale_price=sale_price,
        total_revenue=total_revenue,
        fifo_breakdown=fifo_breakdown,
        total_cost_of_goods_sold=total_cost_of_goods_sold,
        gross_profit=gross_profit,
        gross_margin_percent=gross_margin_percent
    )
    
    sales = load_sales_log()
    sales.append(sale)
    save_sales_log(sales)
    
    return sale

def get_inventory() -> Dict[str, Dict]:
    """Получить текущие остатки товаров"""
    purchases = load_purchases()
    inventory = {}
    
    for purchase in purchases:
        offer_id = purchase.offer_id
        if offer_id not in inventory:
            inventory[offer_id] = {
                'product_name': purchase.product_name,
                'total_quantity': 0,
                'total_cost': 0.0,
                'purchases': []
            }
        
        if purchase.remaining > 0:
            inventory[offer_id]['total_quantity'] += purchase.remaining
            cost_remaining = purchase.remaining * purchase.purchase_price
            inventory[offer_id]['total_cost'] += cost_remaining
            inventory[offer_id]['purchases'].append({
                'purchase_id': purchase.id,
                'date': purchase.date,
                'quantity': purchase.remaining,
                'unit_cost': purchase.purchase_price,
                'total_cost': cost_remaining
            })
    
    return inventory

def get_product_profitability(offer_id: str) -> Dict:
    """Получить рентабельность конкретного товара"""
    sales = load_sales_log()
    product_sales = [s for s in sales if s.offer_id == offer_id]
    
    if not product_sales:
        return {
            'product_name': offer_id,
            'total_sold': 0,
            'total_revenue': 0.0,
            'total_cogs': 0.0,
            'gross_profit': 0.0,
            'gross_margin_percent': 0.0,
            'roi': 0.0,
            'sales_count': 0
        }
    
    product_name = product_sales[0].product_name if product_sales else offer_id
    total_sold = sum(s.quantity_sold for s in product_sales)
    total_revenue = sum(s.total_revenue for s in product_sales)
    total_cogs = sum(s.total_cost_of_goods_sold for s in product_sales)
    gross_profit = total_revenue - total_cogs
    gross_margin_percent = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    roi = (gross_profit / total_cogs * 100) if total_cogs > 0 else 0
    
    return {
        'product_name': product_name,
        'total_sold': total_sold,
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'gross_profit': gross_profit,
        'gross_margin_percent': gross_margin_percent,
        'roi': roi,
        'sales_count': len(product_sales)
    }

def get_period_profitability(date_from: str, date_to: str) -> Dict:
    """Получить рентабельность за период"""
    sales = load_sales_log()
    period_sales = [s for s in sales if date_from <= s.date <= date_to]
    
    if not period_sales:
        return {
            'period': f"{date_from} — {date_to}",
            'total_revenue': 0.0,
            'total_cogs': 0.0,
            'gross_profit': 0.0,
            'gross_margin_percent': 0.0,
            'roi': 0.0,
            'sales_count': 0,
            'units_sold': 0
        }
    
    total_revenue = sum(s.total_revenue for s in period_sales)
    total_cogs = sum(s.total_cost_of_goods_sold for s in period_sales)
    gross_profit = total_revenue - total_cogs
    gross_margin_percent = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    roi = (gross_profit / total_cogs * 100) if total_cogs > 0 else 0
    units_sold = sum(s.quantity_sold for s in period_sales)
    
    return {
        'period': f"{date_from} — {date_to}",
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'gross_profit': gross_profit,
        'gross_margin_percent': gross_margin_percent,
        'roi': roi,
        'sales_count': len(period_sales),
        'units_sold': units_sold
    }

def format_inventory_message(inventory: Dict) -> str:
    """Форматировать сообщение с остатками"""
    if not inventory:
        return "📭 Нет товаров на складе"
    
    lines = ["📊 <b>ОСТАТКИ ТОВАРОВ</b>\n"]
    total_inventory_cost = 0.0
    
    for offer_id, data in sorted(inventory.items()):
        qty = data['total_quantity']
        cost = data['total_cost']
        avg_cost = cost / qty if qty > 0 else 0
        total_inventory_cost += cost
        
        lines.append(
            f"🔸 <b>{data['product_name']}</b>\n"
            f"   На складе: {qty:,} шт\n"
            f"   Средняя себестоимость: {avg_cost:,.0f} ₽/шт\n"
            f"   Общая стоимость: {cost:,.0f} ₽\n"
        )
    
    lines.append("─" * 30)
    lines.append(f"\n💰 <b>ВСЕГО НА СКЛАДЕ: {total_inventory_cost:,.0f} ₽</b>")
    
    return "".join(lines)

def format_profitability_message(prof: Dict) -> str:
    """Форматировать сообщение с рентабельностью"""
    lines = [f"💰 <b>РЕНТАБЕЛЬНОСТЬ</b> ({prof['period']})\n"]
    
    lines.append(f"📊 <b>ПРОДАЖИ:</b>")
    lines.append(f"  Товаров продано: {prof['units_sold']:,} шт")
    lines.append(f"  Количество сделок: {prof['sales_count']}\n")
    
    lines.append(f"💸 <b>ВЫРУЧКА И СЕБЕСТОИМОСТЬ:</b>")
    lines.append(f"  Выручка: {prof['total_revenue']:,.0f} ₽")
    lines.append(f"  Себестоимость (FIFO): {prof['total_cogs']:,.0f} ₽\n")
    
    lines.append(f"📈 <b>ПРИБЫЛЬ:</b>")
    lines.append(f"  Валовая прибыль: {prof['gross_profit']:,.0f} ₽")
    lines.append(f"  Валовая маржа: {prof['gross_margin_percent']:.1f}%")
    lines.append(f"  ROI: {prof['roi']:.1f}%\n")
    
    if prof['roi'] > 0:
        lines.append("✅ <b>Прибыльный период!</b>")
    else:
        lines.append("❌ <b>Убыточный период!</b>")
    
    return "".join(lines)

def format_product_analysis_message(prof: Dict) -> str:
    """Форматировать сообщение с анализом товара"""
    lines = [f"📈 <b>АНАЛИЗ: {prof['product_name']}</b>\n"]
    
    lines.append(f"📊 <b>ПРОДАЖИ:</b>")
    lines.append(f"  Всего продано: {prof['total_sold']:,} шт")
    lines.append(f"  Количество сделок: {prof['sales_count']}\n")
    
    lines.append(f"💸 <b>ФИНАНСЫ:</b>")
    lines.append(f"  Выручка: {prof['total_revenue']:,.0f} ₽")
    lines.append(f"  Себестоимость (FIFO): {prof['total_cogs']:,.0f} ₽")
    lines.append(f"  Валовая прибыль: {prof['gross_profit']:,.0f} ₽\n")
    
    lines.append(f"📈 <b>РЕНТАБЕЛЬНОСТЬ:</b>")
    lines.append(f"  Валовая маржа: {prof['gross_margin_percent']:.1f}%")
    lines.append(f"  ROI: {prof['roi']:.1f}%\n")
    
    if prof['roi'] > 50:
        lines.append("✅ <b>Очень прибыльный товар!</b>")
    elif prof['roi'] > 0:
        lines.append("✅ <b>Прибыльный товар</b>")
    else:
        lines.append("❌ <b>Убыточный товар - рассмотрите прекращение продажи</b>")
    
    return "".join(lines)

# ==================== КОНФИГУРАЦИЯ ====================
OZON_CLIENT_ID = os.getenv("OZON_CLIENT_ID")
OZON_API_KEY = os.getenv("OZON_API_KEY")
OZON_PERFORMANCE_CLIENT_ID = os.getenv("OZON_PERFORMANCE_CLIENT_ID")
OZON_PERFORMANCE_CLIENT_SECRET = os.getenv("OZON_PERFORMANCE_CLIENT_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

OZON_POSTING_FBO_URL = "https://api-seller.ozon.ru/v2/posting/fbo/list"
OZON_FINANCE_URL = "https://api-seller.ozon.ru/v3/finance/transaction/list"
MANAGERS_FILE = "managers.json"
LOG_FILE = "/app/data/ozon_log.txt"

# Состояния для диалогов
WAITING_DATE_SINGLE = 1
WAITING_PERIOD_TYPE = 2
WAITING_PERIOD_START = 3
WAITING_PERIOD_END = 4
WAITING_ADD_MANAGER = 5
WAITING_REMOVE_MANAGER = 6
WAITING_MANAGER_PHONE = 7
WAITING_PERIOD_YEAR = 8
WAITING_PERIOD_MONTH = 9
WAITING_PERIOD_QUARTER = 10
WAITING_YEAR_SELECT = 11
WAITING_DYNAMICS_SELECT = 12
WAITING_DYNAMICS_RANGE_START = 13
WAITING_DYNAMICS_RANGE_END = 14
WAITING_PRODUCT_DATE = 20
WAITING_PRODUCT_PERIOD_TYPE = 21
WAITING_PRODUCT_PERIOD_START = 22
WAITING_PRODUCT_PERIOD_END = 23
WAITING_PRODUCT_YEAR = 24
WAITING_PRODUCT_MONTH = 25
WAITING_PRODUCT_QUARTER = 26
WAITING_PRODUCT_YEAR_SELECT = 27
WAITING_PRODUCT_SELECT = 30
WAITING_PRODUCT_METRIC = 31
WAITING_PRODUCT_PERIOD_CHOICE = 32
WAITING_PRODUCT_SINGLE_YEAR = 33
WAITING_PRODUCT_RANGE_START = 34
WAITING_PRODUCT_RANGE_END = 35
WAITING_PRODUCT_SKU_MANUAL = 36
WAITING_TOP_PERIOD_TYPE = 40
WAITING_TOP_YEAR = 41
WAITING_TOP_MONTH = 42
WAITING_TOP_QUARTER = 43
WAITING_TOP_RANGE_START = 44
WAITING_TOP_RANGE_END = 45

# FIFO состояния
WAITING_PURCHASE_OFFER_ID = 50
WAITING_PURCHASE_PRODUCT_NAME = 51
WAITING_PURCHASE_QUANTITY = 52
WAITING_PURCHASE_PRICE = 53
WAITING_PURCHASE_DATE = 54
WAITING_PROFITABILITY_PERIOD = 55
WAITING_PRODUCT_ANALYSIS_SELECT = 56

MOSCOW_TZ = datetime.timezone(datetime.timedelta(hours=3))
executor = ThreadPoolExecutor(max_workers=3)

def write_log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    print(full_msg, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_msg + "\n")
    except:
        pass

def load_managers():
    if os.path.exists(MANAGERS_FILE):
        with open(MANAGERS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_managers(managers):
    with open(MANAGERS_FILE, "w", encoding="utf-8") as f:
        json.dump(managers, f, ensure_ascii=False, indent=2)

def is_manager(chat_id):
    managers = load_managers()
    return any(m.get("id") == chat_id for m in managers)

def get_manager_info(chat_id):
    managers = load_managers()
    for m in managers:
        if m.get("id") == chat_id:
            return m
    return None

def add_manager(chat_id, username=None, first_name=None, last_name=None, phone=None):
    managers = load_managers()
    for m in managers:
        if m.get("id") == chat_id:
            return False
    managers.append({
        "id": chat_id,
        "username": username or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
        "phone": phone or ""
    })
    save_managers(managers)
    return True

def remove_manager(chat_id):
    managers = load_managers()
    new_managers = [m for m in managers if m.get("id") != chat_id]
    if len(new_managers) == len(managers):
        return False
    save_managers(new_managers)
    return True

def is_admin(chat_id):
    return chat_id == ADMIN_CHAT_ID

def has_access(chat_id):
    return is_admin(chat_id) or is_manager(chat_id)

def get_greeting(name):
    moscow_tz = MOSCOW_TZ
    now = datetime.datetime.now(moscow_tz)
    hour = now.hour
    if 5 <= hour < 12:
        part = "Доброе утро"
    elif 12 <= hour < 18:
        part = "Добрый день"
    elif 18 <= hour < 24:
        part = "Добрый вечер"
    else:
        part = "Доброй ночи"
    if name:
        return f"{part}, {name}!"
    else:
        return f"{part}, уважаемый пользователь!"

def get_moscow_today():
    return datetime.datetime.now(MOSCOW_TZ).date()

def validate_date(date_str):
    """Проверка корректности даты"""
    try:
        date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        if date.date() > datetime.datetime.now().date():
            return False, "❌ Дата не может быть в будущем"
        two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
        if date < two_years_ago:
            return False, "❌ Дата слишком старая (более 2 лет назад)"
        return True, date.date()
    except ValueError:
        return False, "❌ Неверный формат даты. Используйте YYYY-MM-DD (например, 2024-01-15)"

def api_request_with_retry(url, headers, payload=None, method='POST', timeout=API_TIMEOUT):
    """Универсальная функция для API запросов с retry логикой"""
    for attempt in range(API_RETRY_ATTEMPTS):
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            else:
                response = requests.get(url, headers=headers, params=payload, timeout=timeout)

            if response.status_code == 429:
                wait_time = API_RETRY_DELAY * (2 ** attempt)
                write_log(f"⚠️ Rate limit hit, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            return response

        except requests.exceptions.RequestException as e:
            if attempt == API_RETRY_ATTEMPTS - 1:
                raise
            write_log(f"⚠️ Request failed (attempt {attempt+1}/{API_RETRY_ATTEMPTS}): {e}")
            time.sleep(API_RETRY_DELAY)

def fetch_postings(date_from, date_to):
    """Получение отправлений с кэшированием"""
    cache_key = f"postings_{date_from}_{date_to}"
    cached = get_from_cache(cache_key)
    if cached is not None:
        write_log(f"📦 Используем кэш для postings {date_from}–{date_to}")
        return cached
    
    headers = {
        "Client-Id": OZON_CLIENT_ID,
        "Api-Key": OZON_API_KEY,
        "Content-Type": "application/json"
    }
    all_postings = []
    offset = 0
    limit = 1000
    
    while True:
        payload = {
            "dir": "ASC",
            "filter": {
                "since": f"{date_from}T00:00:00.000Z",
                "to": f"{date_to}T23:59:59.999Z",
                "status": ""
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        try:
            response = api_request_with_retry(OZON_POSTING_FBO_URL, headers, payload)
            data = response.json()
            postings = data.get("result", {}).get("postings", [])
            all_postings.extend(postings)
            if len(postings) < limit:
                break
            offset += limit
        except Exception as e:
            write_log(f"❌ Ошибка загрузки отправлений: {e}")
            break
    
    write_log(f"📦 Загружено {len(all_postings)} отправлений за {date_from}–{date_to}")
    save_to_cache(cache_key, all_postings)
    return all_postings

# ==================== TELEGRAM ОБРАБОТЧИКИ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if not has_access(chat_id):
        await update.message.reply_text(
            "⛔ У вас нет доступа к этому боту.\n"
            "Пожалуйста, свяжитесь с администратором для получения доступа."
        )
        return ConversationHandler.END
    
    name = user.first_name if user.first_name else "пользователь"
    greeting = get_greeting(name)
    
    keyboard = [
        [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
        [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
        [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
        [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
    ]
    
    await update.message.reply_text(
        f"{greeting}\n\n"
        "Выберите действие из меню:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>📖 Справка по командам бота</b>\n\n"
        "<b>Основные отчеты:</b>\n"
        "• <b>📊 Отчет по продажам</b> – метрики продаж за выбранный период\n"
        "• <b>📦 Отчет по товарам</b> – анализ товаров\n\n"
        
        "<b>Управление системой:</b>\n"
        "• <b>⚙️ Администрирование</b> – управление менеджерами\n\n"
        
        "<b>📦 FIFO система (Управление товарами):</b>\n"
        "• <b>➕ Добавить поставку</b> – зафиксировать новую закупку товара\n"
        "• <b>📦 Остатки</b> – показать текущие остатки с себестоимостью\n"
        "• <b>💰 Рентабельность</b> – анализ прибыли за период\n"
        "• <b>📈 Анализ товара</b> – детальный анализ конкретного товара\n\n"
        
        "<b>Что показывает бот:</b>\n"
        "• Заказано и доставлено товаров\n"
        "• Расходы на рекламу и комиссии\n"
        "• <b>Себестоимость товаров по методу FIFO</b>\n"
        "• <b>Валовую прибыль и рентабельность</b>\n"
        "• <b>ROI (Return On Investment)</b>\n\n"
        "<i>Все данные берутся из Ozon API и вашей локальной базы.</i>"
    )
    
    await update.message.reply_text(help_text, parse_mode='HTML')

# ==================== FIFO ОБРАБОТЧИКИ ====================

async def add_purchase_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления поставки"""
    chat_id = update.effective_chat.id
    if not has_access(chat_id):
        await update.message.reply_text("❌ У вас нет доступа")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📦 <b>ДОБАВИТЬ ПОСТАВКУ</b>\n\n"
        "Введите артикул товара (offer_id)\n"
        "Например: ТОВАР-001\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_PURCHASE_OFFER_ID

async def purchase_offer_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем артикул товара"""
    offer_id = update.message.text.strip()
    
    if not offer_id:
        await update.message.reply_text("❌ Артикул не может быть пустым")
        return WAITING_PURCHASE_OFFER_ID
    
    context.user_data['purchase_offer_id'] = offer_id
    
    await update.message.reply_text(
        "Введите название товара\n"
        "Например: Кружка красная"
    )
    return WAITING_PURCHASE_PRODUCT_NAME

async def purchase_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем название товара"""
    product_name = update.message.text.strip()
    context.user_data['product_name'] = product_name
    
    await update.message.reply_text(
        "Введите количество единиц\n"
        "Например: 100"
    )
    return WAITING_PURCHASE_QUANTITY

async def purchase_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем количество"""
    try:
        quantity = int(update.message.text.strip())
        if quantity <= 0:
            raise ValueError()
        context.user_data['purchase_quantity'] = quantity
    except:
        await update.message.reply_text("❌ Введите положительное число")
        return WAITING_PURCHASE_QUANTITY
    
    await update.message.reply_text(
        "Введите цену закупки за единицу (₽)\n"
        "Например: 500"
    )
    return WAITING_PURCHASE_PRICE

async def purchase_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем цену закупки"""
    try:
        price = float(update.message.text.strip().replace(',', '.'))
        if price <= 0:
            raise ValueError()
        context.user_data['purchase_price'] = price
    except:
        await update.message.reply_text("❌ Введите положительное число")
        return WAITING_PURCHASE_PRICE
    
    await update.message.reply_text(
        "Введите дату поставки (ГГГГ-ММ-ДД)\n"
        "Пример: 2024-01-15\n\n"
        "Или отправьте 'сегодня' для текущей даты"
    )
    return WAITING_PURCHASE_DATE

async def purchase_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем дату поставки"""
    date_str = update.message.text.strip()
    
    if date_str.lower() == 'сегодня':
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except:
        await update.message.reply_text(
            "❌ Неверный формат даты\n"
            "Используйте ГГГГ-ММ-ДД (например: 2024-01-15)"
        )
        return WAITING_PURCHASE_DATE
    
    try:
        purchase = add_purchase(
            offer_id=context.user_data['purchase_offer_id'],
            product_name=context.user_data['product_name'],
            quantity=context.user_data['purchase_quantity'],
            purchase_price=context.user_data['purchase_price'],
            date=date_str
        )
        
        await update.message.reply_text(
            f"✅ <b>Поставка добавлена успешно!</b>\n\n"
            f"📦 Артикул: {purchase.offer_id}\n"
            f"📝 Товар: {purchase.product_name}\n"
            f"📊 Количество: {purchase.quantity} шт\n"
            f"💰 Цена за единицу: {purchase.purchase_price:,.0f} ₽\n"
            f"📅 Дата: {purchase.date}\n"
            f"💵 Общая стоимость: {purchase.total_cost:,.0f} ₽",
            parse_mode='HTML'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    chat_id = update.effective_chat.id
    keyboard = [
        [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
        [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
        [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
        [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
    ]
    await update.message.reply_text("Готово!", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    
    return ConversationHandler.END

async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие остатки"""
    chat_id = update.effective_chat.id
    
    if not has_access(chat_id):
        await update.message.reply_text("❌ У вас нет доступа")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Загружаю остатки...", reply_markup=ReplyKeyboardRemove())
    
    try:
        inventory = get_inventory()
        message = format_inventory_message(inventory)
        
        if len(message) > 4000:
            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='HTML')
        else:
            await update.message.reply_text(message, parse_mode='HTML')
        
        keyboard = [
            [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
            [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
            [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
            [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
        ]
        await update.message.reply_text("✅ Готово!", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    except Exception as e:
        write_log(f"❌ Ошибка в inventory_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

async def profitability_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога анализа рентабельности"""
    chat_id = update.effective_chat.id
    
    if not has_access(chat_id):
        await update.message.reply_text("❌ У вас нет доступа")
        return ConversationHandler.END
    
    keyboard = [
        [KeyboardButton("📅 Месяц"), KeyboardButton("🗓️ Квартал")],
        [KeyboardButton("📆 Год"), KeyboardButton("📈 Произвольный период")],
        [KeyboardButton("❌ Отмена")]
    ]
    
    await update.message.reply_text(
        "💰 <b>АНАЛИЗ РЕНТАБЕЛЬНОСТИ</b>\n\n"
        "Выберите период:",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    
    return WAITING_PROFITABILITY_PERIOD

async def profitability_period_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора периода"""
    text = update.message.text
    chat_id = update.effective_chat.id
    today = datetime.datetime.now().date()
    
    if text == "❌ Отмена":
        keyboard = [
            [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
            [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
            [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
            [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
        ]
        await update.message.reply_text("Отменено", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return ConversationHandler.END
    
    if text == "📅 Месяц":
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        date_to = today.strftime("%Y-%m-%d")
        period_name = f"{today.strftime('%B %Y')}"
    elif text == "🗓️ Квартал":
        quarter = (today.month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        date_from = today.replace(month=start_month, day=1).strftime("%Y-%m-%d")
        if quarter == 4:
            date_to = today.replace(month=12, day=31).strftime("%Y-%m-%d")
        else:
            date_to = today.replace(month=start_month + 2, day=1).replace(day=1)
            date_to = (date_to - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        period_name = f"Q{quarter} {today.year}"
    elif text == "📆 Год":
        date_from = today.replace(month=1, day=1).strftime("%Y-%m-%d")
        date_to = today.strftime("%Y-%m-%d")
        period_name = f"{today.year}"
    else:
        await update.message.reply_text("❌ Неверный выбор")
        return WAITING_PROFITABILITY_PERIOD
    
    await update.message.reply_text("⏳ Анализирую данные...", reply_markup=ReplyKeyboardRemove())
    
    try:
        prof = get_period_profitability(date_from, date_to)
        prof['period'] = period_name
        
        message = format_profitability_message(prof)
        
        if len(message) > 4000:
            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='HTML')
        else:
            await update.message.reply_text(message, parse_mode='HTML')
        
        keyboard = [
            [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
            [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
            [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
            [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
        ]
        await update.message.reply_text("✅ Готово!", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    except Exception as e:
        write_log(f"❌ Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

async def product_analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало анализа товара"""
    chat_id = update.effective_chat.id
    
    if not has_access(chat_id):
        await update.message.reply_text("❌ У вас нет доступа")
        return ConversationHandler.END
    
    purchases = load_purchases()
    offer_ids = sorted(set(p.offer_id for p in purchases))
    
    if not offer_ids:
        await update.message.reply_text("❌ В системе нет товаров")
        return ConversationHandler.END
    
    keyboard = [[KeyboardButton(offer_id)] for offer_id in offer_ids]
    keyboard.append([KeyboardButton("❌ Отмена")])
    
    await update.message.reply_text(
        "📈 <b>АНАЛИЗ ТОВАРА</b>\n\n"
        "Выберите товар:",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    
    return WAITING_PRODUCT_ANALYSIS_SELECT

async def product_analysis_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора товара"""
    offer_id = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if offer_id == "❌ Отмена":
        keyboard = [
            [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
            [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
            [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
            [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
        ]
        await update.message.reply_text("Отменено", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Анализирую товар...", reply_markup=ReplyKeyboardRemove())
    
    try:
        prof = get_product_profitability(offer_id)
        message = format_product_analysis_message(prof)
        
        if len(message) > 4000:
            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='HTML')
        else:
            await update.message.reply_text(message, parse_mode='HTML')
        
        keyboard = [
            [KeyboardButton("📊 Отчет по продажам"), KeyboardButton("📦 Отчет по товарам")],
            [KeyboardButton("⚙️ Администрирование"), KeyboardButton("ℹ️ Справка")],
            [KeyboardButton("➕ Добавить поставку"), KeyboardButton("📦 Остатки")],
            [KeyboardButton("💰 Рентабельность"), KeyboardButton("📈 Анализ товара")]
        ]
        await update.message.reply_text("✅ Готово!", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    except Exception as e:
        write_log(f"❌ Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Regex("^ℹ️ Справка$"), help_command))
    
    # FIFO обработчики
    add_purchase_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add_purchase", add_purchase_command),
            MessageHandler(filters.Regex("^➕ Добавить поставку$"), add_purchase_command)
        ],
        states={
            WAITING_PURCHASE_OFFER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_offer_id)],
            WAITING_PURCHASE_PRODUCT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_product_name)],
            WAITING_PURCHASE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_quantity)],
            WAITING_PURCHASE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_price)],
            WAITING_PURCHASE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_date)],
        },
        fallbacks=[CommandHandler("cancel", start)],
        name="add_purchase_conversation",
        persistent=False
    )
    
    inventory_handler = MessageHandler(filters.Regex("^📦 Остатки$"), inventory_command)
    
    profitability_handler = ConversationHandler(
        entry_points=[
            CommandHandler("profitability", profitability_command),
            MessageHandler(filters.Regex("^💰 Рентабельность$"), profitability_command)
        ],
        states={
            WAITING_PROFITABILITY_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, profitability_period_select)],
        },
        fallbacks=[CommandHandler("cancel", start)],
        name="profitability_conversation",
        persistent=False
    )
    
    product_analysis_handler = ConversationHandler(
        entry_points=[
            CommandHandler("analyze_product", product_analysis_command),
            MessageHandler(filters.Regex("^📈 Анализ товара$"), product_analysis_command)
        ],
        states={
            WAITING_PRODUCT_ANALYSIS_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_analysis_select)],
        },
        fallbacks=[CommandHandler("cancel", start)],
        name="product_analysis_conversation",
        persistent=False
    )
    
    application.add_handler(add_purchase_handler)
    application.add_handler(inventory_handler)
    application.add_handler(profitability_handler)
    application.add_handler(product_analysis_handler)
    
    write_log("🚀 Бот запущен!")
    write_log("✅ Кэширование: активно")
    write_log("✅ FIFO система: активна")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
