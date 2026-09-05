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
# Состояния для товарных отчётов
WAITING_PRODUCT_DATE = 20
WAITING_PRODUCT_PERIOD_TYPE = 21
WAITING_PRODUCT_PERIOD_START = 22
WAITING_PRODUCT_PERIOD_END = 23
WAITING_PRODUCT_YEAR = 24
WAITING_PRODUCT_MONTH = 25
WAITING_PRODUCT_QUARTER = 26
WAITING_PRODUCT_YEAR_SELECT = 27
# Новые состояния для динамики по товару
WAITING_PRODUCT_SELECT = 30
WAITING_PRODUCT_METRIC = 31
WAITING_PRODUCT_PERIOD_CHOICE = 32
WAITING_PRODUCT_SINGLE_YEAR = 33
WAITING_PRODUCT_RANGE_START = 34
WAITING_PRODUCT_RANGE_END = 35
WAITING_PRODUCT_SKU_MANUAL = 36
# Состояния для /топ_товары
WAITING_TOP_PERIOD_TYPE = 40
WAITING_TOP_YEAR = 41
WAITING_TOP_MONTH = 42
WAITING_TOP_QUARTER = 43
WAITING_TOP_RANGE_START = 44
WAITING_TOP_RANGE_END = 45
# =====================================================

MOSCOW_TZ = datetime.timezone(datetime.timedelta(hours=3))

# Executor для параллельных задач
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

def create_calendar(year, month, callback_prefix):
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    keyboard = []
    header = f"{month_names[month-1]} {year}"
    keyboard.append([InlineKeyboardButton(header, callback_data="ignore")])
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    row = [InlineKeyboardButton(day, callback_data="ignore") for day in week_days]
    keyboard.append(row)

    first_day, num_days = calendar.monthrange(year, month)
    row = []
    for _ in range(first_day):
        row.append(InlineKeyboardButton(" ", callback_data="ignore"))
    for day in range(1, num_days + 1):
        row.append(InlineKeyboardButton(str(day), callback_data=f"{callback_prefix}{year}-{month:02d}-{day:02d}"))
        if len(row) == 7:
            keyboard.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(" ", callback_data="ignore"))
        keyboard.append(row)

    nav_row = [
        InlineKeyboardButton("◀️", callback_data=f"{callback_prefix}prev_month_{year}_{month}"),
        InlineKeyboardButton(" ", callback_data="ignore"),
        InlineKeyboardButton("▶️", callback_data=f"{callback_prefix}next_month_{year}_{month}")
    ]
    keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"{callback_prefix}cancel")])
    return InlineKeyboardMarkup(keyboard)

# ==================== ВАЛИДАЦИЯ ДАННЫХ ====================
def validate_date(date_str):
    """Проверка корректности даты"""
    try:
        date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        
        # Проверяем, что дата не в будущем
        if date.date() > datetime.datetime.now().date():
            return False, "❌ Дата не может быть в будущем"
        
        # Проверяем, что дата не слишком старая (например, > 2 лет)
        two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
        if date < two_years_ago:
            return False, "❌ Дата слишком старая (более 2 лет назад)"
        
        return True, date.date()
    except ValueError:
        return False, "❌ Неверный формат даты. Используйте YYYY-MM-DD (например, 2024-01-15)"

def validate_period(date_from, date_to):
    """Проверка корректности периода"""
    valid_from, result_from = validate_date(date_from)
    if not valid_from:
        return False, result_from
    
    valid_to, result_to = validate_date(date_to)
    if not valid_to:
        return False, result_to
    
    # Проверяем, что date_from <= date_to
    if result_from > result_to:
        return False, "❌ Начальная дата не может быть позже конечной"
    
    # Проверяем, что период не слишком большой
    delta = (result_to - result_from).days
    if delta > 365:
        return False, "❌ Период не может быть больше года"
    
    return True, (result_from, result_to)

# ==================== API С RETRY И КЭШИРОВАНИЕМ ====================
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

def aggregate_postings(postings, date_from=None, date_to=None):
    """Агрегация отправлений по статусам"""
    aggregation = {}
    for p in postings:
        status = p.get("status", "unknown")
        products = p.get("products", [])
        total = 0.0
        for prod in products:
            price = float(prod.get("price", "0"))
            quantity = int(prod.get("quantity", 0))
            total += price * quantity
        
        if status not in aggregation:
            aggregation[status] = {
                "ordered_units": 0,
                "ordered_sum": 0.0,
                "delivered_units": 0,
                "delivered_sum": 0.0,
                "canceled_units": 0,
                "canceled_sum": 0.0,
            }
        
        units_count = sum(int(prod.get("quantity", 0)) for prod in products)
        
        if status in ["awaiting_packaging", "awaiting_deliver", "arbitration", "client_arbitration"]:
            aggregation[status]["ordered_units"] += units_count
            aggregation[status]["ordered_sum"] += total
        elif status == "delivered":
            aggregation[status]["ordered_units"] += units_count
            aggregation[status]["ordered_sum"] += total
            aggregation[status]["delivered_units"] += units_count
            aggregation[status]["delivered_sum"] += total
        elif status in ["cancelled", "not_accepted"]:
            aggregation[status]["canceled_units"] += units_count
            aggregation[status]["canceled_sum"] += total
        else:
            aggregation[status]["ordered_units"] += units_count
            aggregation[status]["ordered_sum"] += total
    
    return aggregation

def get_performance_token():
    """Получение токена Performance API"""
    url = "https://performance.ozon.ru/api/client/token"
    headers = {"Content-Type": "application/json"}
    payload = {
        "client_id": OZON_PERFORMANCE_CLIENT_ID,
        "client_secret": OZON_PERFORMANCE_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    try:
        response = api_request_with_retry(url, headers, payload)
        data = response.json()
        return data.get("access_token")
    except Exception as e:
        write_log(f"❌ Ошибка получения токена Performance: {e}")
        return None

def fetch_advertising_expense_single(date_from, date_to):
    """Получение расходов на рекламу за период"""
    token = get_performance_token()
    if not token:
        return 0.0
    
    url = "https://performance.ozon.ru/api/client/statistics"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "groupBy": "NO_GROUP_BY"
    }
    try:
        response = api_request_with_retry(url, headers, params, method='GET')
        data = response.json()
        rows = data.get("rows", [])
        total = sum(float(row.get("expense", 0)) for row in rows)
        return total
    except Exception as e:
        write_log(f"❌ Ошибка загрузки расходов на рекламу: {e}")
        return 0.0

def fetch_advertising_expense(date_from, date_to):
    """Получение расходов на рекламу с кэшированием"""
    cache_key = f"ad_expense_{date_from}_{date_to}"
    cached = get_from_cache(cache_key)
    if cached is not None:
        write_log(f"📢 Используем кэш для расходов на рекламу {date_from}–{date_to}")
        return cached
    
    start_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
    delta = (end_dt - start_dt).days
    
    if delta <= API_MAX_DAYS_PER_REQUEST:
        result = fetch_advertising_expense_single(date_from, date_to)
        save_to_cache(cache_key, result)
        return result
    
    total_expense = 0.0
    current = start_dt.replace(day=1)
    
    while current <= end_dt:
        month_start = current.strftime("%Y-%m-%d")
        next_month = current.replace(day=28) + datetime.timedelta(days=4)
        month_end = (next_month - datetime.timedelta(days=next_month.day)).strftime("%Y-%m-%d")
        if month_end > date_to:
            month_end = date_to
        
        write_log(f"📢 Запрос рекламы за {month_start}–{month_end}")
        total_expense += fetch_advertising_expense_single(month_start, month_end)
        
        current = current.replace(day=28) + datetime.timedelta(days=4)
        current = current.replace(day=1)
    
    write_log(f"📢 Всего расходов на рекламу: {total_expense:.2f} ₽ за {date_from}–{date_to}")
    save_to_cache(cache_key, total_expense)
    return total_expense

def fetch_finance_transactions_single(date_from, date_to):
    """Получение финансовых транзакций за период"""
    headers = {
        "Client-Id": OZON_CLIENT_ID,
        "Api-Key": OZON_API_KEY,
        "Content-Type": "application/json"
    }
    all_transactions = []
    page = 1
    page_size = 1000
    
    while True:
        payload = {
            "filter": {
                "date": {
                    "from": f"{date_from}T00:00:00.000Z",
                    "to": f"{date_to}T23:59:59.999Z"
                },
                "transaction_type": "all"
            },
            "page": page,
            "page_size": page_size
        }
        try:
            response = api_request_with_retry(OZON_FINANCE_URL, headers, payload)
            data = response.json()
            operations = data.get("result", {}).get("operations", [])
            all_transactions.extend(operations)
            if len(operations) < page_size:
                break
            page += 1
        except Exception as e:
            write_log(f"❌ Ошибка загрузки финансов: {e}")
            break
    
    return all_transactions

def fetch_finance_transactions(date_from, date_to):
    """Получение финансовых транзакций с кэшированием"""
    cache_key = f"finance_{date_from}_{date_to}"
    cached = get_from_cache(cache_key)
    if cached is not None:
        write_log(f"💰 Используем кэш для финансов {date_from}–{date_to}")
        return cached
    
    start_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
    today = get_moscow_today()
    
    if start_dt.date() > today:
        return []
    if end_dt.date() > today:
        end_dt = datetime.datetime.combine(today, datetime.time(23, 59, 59))

    delta = (end_dt - start_dt).days
    
    if delta <= API_MAX_DAYS_PER_REQUEST:
        result = fetch_finance_transactions_single(date_from, end_dt.strftime("%Y-%m-%d"))
        save_to_cache(cache_key, result)
        return result

    all_transactions = []
    current = start_dt.replace(day=1)
    
    while current <= end_dt:
        month_start = current.strftime("%Y-%m-%d")
        next_month = current.replace(day=28) + datetime.timedelta(days=4)
        month_end = (next_month - datetime.timedelta(days=next_month.day)).strftime("%Y-%m-%d")
        if month_end > end_dt.strftime("%Y-%m-%d"):
            month_end = end_dt.strftime("%Y-%m-%d")
        if current.date() > today:
            break
        
        write_log(f"💰 Запрос финансов за {month_start}–{month_end}")
        all_transactions.extend(fetch_finance_transactions_single(month_start, month_end))
        
        current = current.replace(day=28) + datetime.timedelta(days=4)
        current = current.replace(day=1)

    write_log(f"💰 Всего загружено финансовых транзакций: {len(all_transactions)} за {date_from}–{date_to}")
    save_to_cache(cache_key, all_transactions)
    return all_transactions

def aggregate_finance_expenses(transactions):
    """
    Агрегация финансовых расходов (оптимизированная версия)
    """
    expense_by_type = {}
    unique_types = set()
    unique_services = set()
    sample_transactions = []  # Собираем примеры для логирования
    
    for t in transactions:
        # Только сбор данных, без I/O
        if len(sample_transactions) < DEBUG_SAMPLE_SIZE:
            services = t.get("services", [])
            if services:
                sample_transactions.append(t)

        sale_comm = t.get("sale_commission", 0)
        if sale_comm < 0:
            expense_by_type["Комиссия Ozon"] = expense_by_type.get("Комиссия Ozon", 0) + abs(sale_comm)

        accruals = t.get("accruals_for_sale", 0)
        if accruals < 0:
            expense_by_type["Возврат выручки"] = expense_by_type.get("Возврат выручки", 0) + abs(accruals)

        delivery_charge = t.get("delivery_charge", 0)
        if delivery_charge < 0:
            expense_by_type["Доставка (отдельно)"] = expense_by_type.get("Доставка (отдельно)", 0) + abs(delivery_charge)

        return_delivery = t.get("return_delivery_charge", 0)
        if return_delivery < 0:
            expense_by_type["Возвратная доставка"] = expense_by_type.get("Возвратная доставка", 0) + abs(return_delivery)

        amount = t.get("amount", 0)
        op_type = t.get("operation_type_name", "Неизвестный тип")
        if amount < 0:
            unique_types.add(op_type)

        services = t.get("services", [])
        if services and isinstance(services, list):
            has_negative_service = False
            for service in services:
                service_name = service.get("name", "Неизвестная услуга")
                service_amount = service.get("price", 0)
                if service_amount == 0:
                    service_amount = service.get("amount", 0)
                if service_amount < 0:
                    has_negative_service = True
                    unique_services.add(service_name)
                    expense_by_type[service_name] = expense_by_type.get(service_name, 0) + abs(service_amount)
            
            if not has_negative_service and amount < 0:
                expense_by_type[op_type] = expense_by_type.get(op_type, 0) + abs(amount)
        else:
            if amount < 0:
                expense_by_type[op_type] = expense_by_type.get(op_type, 0) + abs(amount)

    # Логируем ПОСЛЕ цикла одним блоком
    if sample_transactions:
        for t in sample_transactions:
            services = t.get("services", [])
            write_log(f"🔍 Пример транзакции: amount={t.get('amount')}, operation_type={t.get('operation_type_name')}, sale_commission={t.get('sale_commission')}, accruals_for_sale={t.get('accruals_for_sale')}, services={json.dumps(services, ensure_ascii=False)}")

    if transactions:
        write_log(f"🔍 Найдены operation_type: {', '.join(unique_types)}")
        if unique_services:
            write_log(f"🔍 Найдены услуги (services): {', '.join(unique_services)}")
        if expense_by_type:
            write_log(f"🔍 Итоговые категории расходов: {', '.join(expense_by_type.keys())}")

    return expense_by_type

# ==================== ПАРАЛЛЕЛЬНАЯ ЗАГРУЗКА ДАННЫХ ====================
async def get_metrics_for_period_async(date_from, date_to):
    """
    Асинхронная версия get_metrics_for_period с параллельными запросами
    """
    loop = asyncio.get_event_loop()
    
    # Запускаем все запросы параллельно
    postings, ad_expense, transactions = await asyncio.gather(
        loop.run_in_executor(executor, fetch_postings, date_from, date_to),
        loop.run_in_executor(executor, fetch_advertising_expense, date_from, date_to),
        loop.run_in_executor(executor, fetch_finance_transactions, date_from, date_to)
    )
    
    # Обрабатываем результаты
    agg = aggregate_postings(postings, date_from=date_from, date_to=date_to)
    total = {
        "ordered_units": 0,
        "ordered_sum": 0.0,
        "delivered_units": 0,
        "delivered_sum": 0.0,
        "canceled_units": 0,
        "canceled_sum": 0.0,
    }
    
    for vals in agg.values():
        for key in total:
            total[key] += vals.get(key, 0)
    
    total["ad_expense"] = ad_expense if ad_expense is not None else 0.0
    
    revenue = total.get("ordered_sum", 0)
    if revenue > 0 and ad_expense is not None:
        total["drr"] = (ad_expense / revenue) * 100
    else:
        total["drr"] = None
    
    delivered_revenue = total.get("delivered_sum", 0)
    if delivered_revenue > 0 and ad_expense is not None:
        total["effective_drr"] = (ad_expense / delivered_revenue) * 100
    else:
        total["effective_drr"] = None

    expenses = aggregate_finance_expenses(transactions)
    total["expenses"] = expenses
    
    return total

def get_metrics_for_period(date_from, date_to):
    """Синхронная обертка для асинхронной функции"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(get_metrics_for_period_async(date_from, date_to))

# ==================== ТОП ТОВАРОВ ====================
def get_top_products(postings, limit=10):
    """Получить топ товаров по продажам"""
    product_stats = {}
    
    for posting in postings:
        if posting.get('status') != 'delivered':
            continue
            
        for product in posting.get('products', []):
            offer_id = product.get('offer_id')
            price = float(product.get('price', 0))
            quantity = int(product.get('quantity', 0))
            revenue = price * quantity
            
            if offer_id not in product_stats:
                product_stats[offer_id] = {
                    'name': product.get('name', offer_id),
                    'units_sold': 0,
                    'revenue': 0
                }
            
            product_stats[offer_id]['units_sold'] += quantity
            product_stats[offer_id]['revenue'] += revenue
    
    # Сортируем по выручке
    top_by_revenue = sorted(
        product_stats.items(),
        key=lambda x: x[1]['revenue'],
        reverse=True
    )[:limit]
    
    return top_by_revenue

# ==================== ФОРМАТИРОВАНИЕ ====================
def format_expense_block(expenses):
    if not expenses:
        return "  (нет данных о расходах)"
    lines = []
    for category, amount in sorted(expenses.items(), key=lambda x: -x[1]):
        lines.append(f"    • {category}: {amount:,.2f} ₽")
    return "\n".join(lines)

def get_current_time_msk():
    now = datetime.datetime.now(MOSCOW_TZ)
    return now.strftime("%d.%m.%Y %H:%M:%S")

def format_metrics_message(date_str, metrics):
    """Форматирование метрик"""
    lines = []
    lines.append(f"<b>📊 Метрики за {date_str}</b>\n")
    
    lines.append(f"<b>🛒 Продажи:</b>")
    lines.append(f"  Заказано: {metrics.get('ordered_units', 0)} шт / {metrics.get('ordered_sum', 0):,.2f} ₽")
    lines.append(f"  Доставлено: {metrics.get('delivered_units', 0)} шт / {metrics.get('delivered_sum', 0):,.2f} ₽")
    lines.append(f"  Отменено: {metrics.get('canceled_units', 0)} шт / {metrics.get('canceled_sum', 0):,.2f} ₽\n")
    
    ad_expense = metrics.get('ad_expense', 0)
    drr = metrics.get('drr')
    eff_drr = metrics.get('effective_drr')
    drr_text = f"{drr:.2f}%" if drr is not None else "∞"
    eff_drr_text = f"{eff_drr:.2f}%" if eff_drr is not None else "∞"
    
    lines.append(f"<b>📢 Реклама:</b>")
    lines.append(f"  Расходы: {ad_expense:,.2f} ₽")
    lines.append(f"  ДРР (общий): {drr_text}")
    lines.append(f"  ДРР (по доставленным): {eff_drr_text}\n")
    
    expenses = metrics.get('expenses', {})
    if expenses:
        lines.append(f"<b>💸 Расходы (детализация):</b>")
        lines.append(format_expense_block(expenses))
    
    return "\n".join(lines)

# ==================== КЛАВИАТУРЫ ====================
def main_admin_keyboard():
    keyboard = [
        [KeyboardButton("📊 Метрики за день"), KeyboardButton("📈 Метрики за период")],
        [KeyboardButton("📅 Месяц"), KeyboardButton("🗓️ Квартал")],
        [KeyboardButton("📆 Год"), KeyboardButton("📉 Динамика продаж")],
        [KeyboardButton("🏆 Топ товары"), KeyboardButton("👥 Управление менеджерами")],
        [KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def main_user_keyboard():
    keyboard = [
        [KeyboardButton("📊 Метрики за день"), KeyboardButton("📈 Метрики за период")],
        [KeyboardButton("📅 Месяц"), KeyboardButton("🗓️ Квартал")],
        [KeyboardButton("📆 Год"), KeyboardButton("📉 Динамика продаж")],
        [KeyboardButton("🏆 Топ товары"), KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
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
    
    keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
    
    await update.message.reply_text(
        f"{greeting}\n\n"
        "Выберите действие из меню:",
        reply_markup=keyboard
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>📖 Справка по командам бота</b>\n\n"
        "<b>Основные функции:</b>\n"
        "• <b>📊 Метрики за день</b> – показывает метрики продаж за выбранную дату\n"
        "• <b>📈 Метрики за период</b> – метрики за произвольный период\n"
        "• <b>📅 Месяц</b> – метрики за выбранный месяц\n"
        "• <b>🗓️ Квартал</b> – метрики за квартал\n"
        "• <b>📆 Год</b> – метрики за год\n"
        "• <b>📉 Динамика продаж</b> – график продаж по месяцам\n"
        "• <b>🏆 Топ товары</b> – топ-10 самых продаваемых товаров\n\n"
        "<b>Что показывает бот:</b>\n"
        "• Заказано и доставлено товаров (штуки и сумма)\n"
        "• Расходы на рекламу\n"
        "• ДРР (общий) и ДРР (по доставленным)\n"
        "• Детализация расходов (комиссии, логистика и др.)\n\n"
        "<i>Все данные берутся из Ozon API в реальном времени.</i>"
    )
    
    if is_admin(update.effective_chat.id):
        help_text += "\n\n<b>Команды администратора:</b>\n"
        help_text += "• <b>👥 Управление менеджерами</b> – добавление/удаление менеджеров\n"
    
    await update.message.reply_text(help_text, parse_mode='HTML')

# ==================== ОБРАБОТЧИК ТОП ТОВАРОВ ====================
async def top_products_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога для топ товаров"""
    keyboard = [
        [KeyboardButton("📅 Месяц"), KeyboardButton("🗓️ Квартал")],
        [KeyboardButton("📆 Год"), KeyboardButton("📈 Период")],
        [KeyboardButton("❌ Отмена")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "🏆 <b>Топ товары</b>\n\n"
        "Выберите период для анализа:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    return WAITING_TOP_PERIOD_TYPE

async def top_products_period_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа периода для топ товаров"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    if text == "❌ Отмена":
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено.", reply_markup=keyboard)
        return ConversationHandler.END
    
    if text == "📅 Месяц":
        today = get_moscow_today()
        keyboard = []
        for i in range(12):
            month_date = today.replace(day=1) - datetime.timedelta(days=i*30)
            month_name = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                         "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][month_date.month - 1]
            keyboard.append([KeyboardButton(f"{month_name} {month_date.year}")])
        keyboard.append([KeyboardButton("❌ Отмена")])
        
        await update.message.reply_text(
            "Выберите месяц:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return WAITING_TOP_MONTH
    
    elif text == "🗓️ Квартал":
        today = get_moscow_today()
        keyboard = []
        for i in range(8):
            year = today.year - i // 4
            quarter = ((today.month - 1) // 3 + 1 - i % 4) % 4
            if quarter == 0:
                quarter = 4
                year -= 1
            keyboard.append([KeyboardButton(f"Q{quarter} {year}")])
        keyboard.append([KeyboardButton("❌ Отмена")])
        
        await update.message.reply_text(
            "Выберите квартал:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return WAITING_TOP_QUARTER
    
    elif text == "📆 Год":
        today = get_moscow_today()
        keyboard = [[KeyboardButton(str(today.year - i))] for i in range(5)]
        keyboard.append([KeyboardButton("❌ Отмена")])
        
        await update.message.reply_text(
            "Выберите год:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return WAITING_TOP_YEAR
    
    elif text == "📈 Период":
        await update.message.reply_text(
            "Введите начальную дату периода в формате ГГГГ-ММ-ДД\n"
            "Например: 2024-01-01\n\n"
            "Или отправьте /cancel для отмены",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_TOP_RANGE_START

async def top_products_process(update: Update, context: ContextTypes.DEFAULT_TYPE, date_from, date_to, period_name):
    """Обработка и вывод топ товаров"""
    chat_id = update.effective_chat.id
    
    await update.message.reply_text(
        "⏳ Загружаю данные...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    try:
        # Валидация периода
        valid, result = validate_period(date_from, date_to)
        if not valid:
            keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
            await update.message.reply_text(result, reply_markup=keyboard)
            return ConversationHandler.END
        
        # Получаем данные
        postings = fetch_postings(date_from, date_to)
        top_products = get_top_products(postings, limit=10)
        
        if not top_products:
            keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
            await update.message.reply_text(
                "📭 За выбранный период нет данных о доставленных товарах.",
                reply_markup=keyboard
            )
            return ConversationHandler.END
        
        # Форматируем сообщение
        message = f"🏆 <b>ТОП-10 ТОВАРОВ</b>\n"
        message += f"<b>Период:</b> {period_name}\n\n"
        
        for i, (offer_id, stats) in enumerate(top_products, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            message += (
                f"{medal} <b>{stats['name'][:50]}</b>\n"
                f"   Продано: {stats['units_sold']} шт\n"
                f"   Выручка: {stats['revenue']:,.0f} ₽\n\n"
            )
        
        # Разбиваем на части если слишком длинное
        if len(message) > 4000:
            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='HTML')
        else:
            await update.message.reply_text(message, parse_mode='HTML')
        
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text(
            "✅ Готово!",
            reply_markup=keyboard
        )
        
    except Exception as e:
        write_log(f"❌ Ошибка в top_products_process: {e}")
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text(
            "❌ Произошла ошибка при загрузке данных. Попробуйте позже.",
            reply_markup=keyboard
        )
    
    return ConversationHandler.END

async def top_products_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора года для топ товаров"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    if text == "❌ Отмена" or text == "/cancel":
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено.", reply_markup=keyboard)
        return ConversationHandler.END
    
    try:
        year = int(text)
        date_from = f"{year}-01-01"
        date_to = f"{year}-12-31"
        period_name = f"Год {year}"
        
        return await top_products_process(update, context, date_from, date_to, period_name)
    except:
        await update.message.reply_text("❌ Неверный формат. Введите год (например: 2024)")
        return WAITING_TOP_YEAR

async def top_products_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора месяца для топ товаров"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    if text == "❌ Отмена" or text == "/cancel":
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено.", reply_markup=keyboard)
        return ConversationHandler.END
    
    # Парсим "Месяц Год"
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    
    for i, month_name in enumerate(month_names, 1):
        if month_name in text:
            try:
                year = int(text.split()[-1])
                date_from = f"{year}-{i:02d}-01"
                # Последний день месяца
                if i == 12:
                    date_to = f"{year}-12-31"
                else:
                    next_month = datetime.date(year, i + 1, 1)
                    date_to = (next_month - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                
                period_name = f"{month_name} {year}"
                return await top_products_process(update, context, date_from, date_to, period_name)
            except:
                pass
    
    await update.message.reply_text("❌ Неверный формат. Выберите месяц из списка.")
    return WAITING_TOP_MONTH

async def top_products_quarter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора квартала для топ товаров"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    if text == "❌ Отмена" or text == "/cancel":
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено.", reply_markup=keyboard)
        return ConversationHandler.END
    
    # Парсим "Q1 2024"
    match = re.match(r'Q(\d) (\d{4})', text)
    if match:
        quarter = int(match.group(1))
        year = int(match.group(2))
        
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        
        date_from = f"{year}-{start_month:02d}-01"
        date_to = f"{year}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]}"
        
        period_name = f"Q{quarter} {year}"
        return await top_products_process(update, context, date_from, date_to, period_name)
    
    await update.message.reply_text("❌ Неверный формат. Выберите квартал из списка.")
    return WAITING_TOP_QUARTER

async def top_products_range_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка начальной даты периода"""
    text = update.message.text
    
    if text == "/cancel":
        chat_id = update.effective_chat.id
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено.", reply_markup=keyboard)
        return ConversationHandler.END
    
    valid, result = validate_date(text)
    if not valid:
        await update.message.reply_text(result)
        return WAITING_TOP_RANGE_START
    
    context.user_data['top_date_from'] = text
    await update.message.reply_text(
        "Введите конечную дату периода в формате ГГГГ-ММ-ДД\n"
        "Например: 2024-12-31\n\n"
        "Или отправьте /cancel для отмены"
    )
    return WAITING_TOP_RANGE_END

async def top_products_range_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка конечной даты периода"""
    text = update.message.text
    
    if text == "/cancel":
        chat_id = update.effective_chat.id
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено.", reply_markup=keyboard)
        return ConversationHandler.END
    
    valid, result = validate_date(text)
    if not valid:
        await update.message.reply_text(result)
        return WAITING_TOP_RANGE_END
    
    date_from = context.user_data.get('top_date_from')
    date_to = text
    
    period_name = f"{date_from} — {date_to}"
    return await top_products_process(update, context, date_from, date_to, period_name)

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Обработчик /start
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Regex("^ℹ️ Помощь$"), help_command))
    
    # Обработчик топ товаров
    top_products_handler = ConversationHandler(
        entry_points=[
            CommandHandler("top_products", top_products_command),
            MessageHandler(filters.Regex("^🏆 Топ товары$"), top_products_command)
        ],
        states={
            WAITING_TOP_PERIOD_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, top_products_period_type)],
            WAITING_TOP_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, top_products_year)],
            WAITING_TOP_MONTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, top_products_month)],
            WAITING_TOP_QUARTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, top_products_quarter)],
            WAITING_TOP_RANGE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, top_products_range_start)],
            WAITING_TOP_RANGE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, top_products_range_end)],
        },
        fallbacks=[CommandHandler("cancel", start)],
        name="top_products_conversation",
        persistent=False
    )
    
    application.add_handler(top_products_handler)
    
    write_log("🚀 Бот запущен с оптимизациями!")
    write_log(f"✅ Кэширование: активно (TTL {CACHE_TTL_SECONDS}s)")
    write_log(f"✅ Retry логика: активна ({API_RETRY_ATTEMPTS} попыток)")
    write_log(f"✅ Параллельные запросы: активны")
    write_log(f"✅ Валидация данных: активна")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
