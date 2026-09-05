import datetime
import json
import os
import time
import re
import calendar
import requests
import warnings
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, ConversationHandler, CallbackQueryHandler
)
from telegram.warnings import PTBUserWarning
warnings.filterwarnings("ignore", category=PTBUserWarning)

# Графики
import matplotlib.pyplot as plt
import io
from matplotlib.dates import MonthLocator, DateFormatter
import matplotlib.dates as mdates

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

# API Configuration
API_TIMEOUT = 15
API_MAX_DAYS_PER_REQUEST = 90
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2

# Logging Configuration  
DEBUG_SAMPLE_SIZE = 10

# Cache Configuration
CACHE_TTL_SECONDS = 300  # 5 минут

# Простой кэш для API результатов
_api_cache = {}
_cache_timestamps = {}

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
# =====================================================

MOSCOW_TZ = datetime.timezone(datetime.timedelta(hours=3))

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

def get_from_cache(key):
    if key in _api_cache:
        timestamp = _cache_timestamps.get(key)
        if timestamp and (time.time() - timestamp) < CACHE_TTL_SECONDS:
            return _api_cache[key]
    return None

def save_to_cache(key, value):
    _api_cache[key] = value
    _cache_timestamps[key] = time.time()

def api_request_with_retry(url, headers, payload=None, method='POST', timeout=API_TIMEOUT):
    for attempt in range(API_RETRY_ATTEMPTS):
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            else:
                response = requests.get(url, headers=headers, params=payload, timeout=timeout)
            
            if response.status_code == 429:  # Rate limit
                wait_time = API_RETRY_DELAY * (2 ** attempt)  # Exponential backoff
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
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone
    })
    save_managers(managers)
    return True

def remove_manager(chat_id):
    managers = load_managers()
    managers = [m for m in managers if m.get("id") != chat_id]
    save_managers(managers)

def is_admin(chat_id):
    return chat_id == ADMIN_CHAT_ID

def has_access(chat_id):
    return is_admin(chat_id) or is_manager(chat_id)

def get_greeting():
    hour = datetime.datetime.now(MOSCOW_TZ).hour
    if 5 <= hour < 12:
        return "Доброе утро"
    elif 12 <= hour < 17:
        return "Добрый день"
    elif 17 <= hour < 23:
        return "Добрый вечер"
    else:
        return "Доброй ночи"

def get_moscow_today():
    return datetime.datetime.now(MOSCOW_TZ).date()

def create_calendar(year, month):
    keyboard = []
    cal = calendar.monthcalendar(year, month)
    keyboard.append([InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="ignore")])
    weekdays_row = [InlineKeyboardButton(day, callback_data="ignore") for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]]
    keyboard.append(weekdays_row)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"cal_day_{year}_{month}_{day}"))
        keyboard.append(row)
    nav_buttons = []
    if month == 1:
        nav_buttons.append(InlineKeyboardButton("◀ Пред", callback_data=f"cal_month_{year-1}_12"))
    else:
        nav_buttons.append(InlineKeyboardButton("◀ Пред", callback_data=f"cal_month_{year}_{month-1}"))
    if month == 12:
        nav_buttons.append(InlineKeyboardButton("След ▶", callback_data=f"cal_month_{year+1}_1"))
    else:
        nav_buttons.append(InlineKeyboardButton("След ▶", callback_data=f"cal_month_{year}_{month+1}"))
    keyboard.append(nav_buttons)
    return InlineKeyboardMarkup(keyboard)

# ---------- ПОЛУЧЕНИЕ ДАННЫХ ИЗ OZON API ----------

def fetch_postings(date_from, date_to):
    cache_key = f"postings_{date_from}_{date_to}"
    cached = get_from_cache(cache_key)
    if cached is not None:
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
    cache_key = f"ad_expense_{date_from}_{date_to}"
    cached = get_from_cache(cache_key)
    if cached is not None:
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
    cache_key = f"finance_{date_from}_{date_to}"
    cached = get_from_cache(cache_key)
    if cached is not None:
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

# ---------- АГРЕГАЦИЯ ФИНАНСОВЫХ РАСХОДОВ (без доходов) ----------

def aggregate_finance_expenses(transactions):
    """
    Возвращает словарь {категория: сумма_расхода} для всех отрицательных значений.
    """
    expense_by_type = {}
    unique_types = set()
    unique_services = set()
    sample_transactions = []
    
    for t in transactions:
        # Собираем примеры для отладки
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

    # Логируем примеры один раз после цикла
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

# ---------- ФОРМАТИРОВАНИЕ БЛОКОВ ----------

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

def format_combined_metrics_with_deltas(date_str, metrics):
    """
    Форматирует метрики за месяц с дельтами по сравнению с предыдущим месяцем.
    """
    lines = []
    lines.append(f"<b>📊 Метрики за месяц {date_str}</b>\n")
    
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

def get_monthly_delivered_sum(date_obj):
    """
    Возвращает сумму доставленных товаров за месяц date_obj (datetime.date).
    """
    year = date_obj.year
    month = date_obj.month
    first_day = datetime.date(year, month, 1)
    if month == 12:
        last_day = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    
    postings = fetch_postings(first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d"))
    agg = aggregate_postings(postings, date_from=first_day.strftime("%Y-%m-%d"), date_to=last_day.strftime("%Y-%m-%d"))
    
    delivered_sum = 0.0
    for vals in agg.values():
        delivered_sum += vals.get("delivered_sum", 0.0)
    return delivered_sum

def generate_sales_chart(start_date, end_date):
    """
    Генерирует график продаж по месяцам за период start_date - end_date.
    Возвращает BytesIO с PNG.
    """
    months_data = []
    current = start_date.replace(day=1)
    while current <= end_date:
        month_delivered = get_monthly_delivered_sum(current)
        months_data.append((current, month_delivered))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    dates = [m[0] for m in months_data]
    sums = [m[1] for m in months_data]
    
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dates, sums, marker='o', linestyle='-', linewidth=2, markersize=8)
    ax.set_title("Доставленная выручка по месяцам", fontsize=14, fontweight='bold')
    ax.set_xlabel("Месяц", fontsize=12)
    ax.set_ylabel("Выручка (₽)", fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(MonthLocator())
    ax.xaxis.set_major_formatter(DateFormatter("%b %Y"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150)
    buf.seek(0)
    plt.close(fig)
    return buf

def format_single_metrics(date_str, metrics):
    """
    Форматирует метрики за один день.
    """
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

def get_metrics_for_date(date_str):
    postings = fetch_postings(date_str, date_str)
    agg = aggregate_postings(postings, date_from=date_str, date_to=date_str)
    metrics = {
        "ordered_units": 0,
        "ordered_sum": 0.0,
        "delivered_units": 0,
        "delivered_sum": 0.0,
        "canceled_units": 0,
        "canceled_sum": 0.0,
    }
    for vals in agg.values():
        for key in metrics:
            metrics[key] += vals.get(key, 0)
    
    ad_expense = fetch_advertising_expense(date_str, date_str)
    metrics["ad_expense"] = ad_expense if ad_expense is not None else 0.0
    
    revenue = metrics.get("ordered_sum", 0)
    if revenue > 0 and ad_expense is not None:
        metrics["drr"] = (ad_expense / revenue) * 100
    else:
        metrics["drr"] = None
    
    delivered_revenue = metrics.get("delivered_sum", 0)
    if delivered_revenue > 0 and ad_expense is not None:
        metrics["effective_drr"] = (ad_expense / delivered_revenue) * 100
    else:
        metrics["effective_drr"] = None
    
    expenses = aggregate_finance_expenses(fetch_finance_transactions(date_str, date_str))
    metrics["expenses"] = expenses
    return metrics

def get_metrics_for_period(date_from, date_to):
    postings = fetch_postings(date_from, date_to)
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
    ad_expense = fetch_advertising_expense(date_from, date_to)
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

    expenses = aggregate_finance_expenses(fetch_finance_transactions(date_from, date_to))
    total["expenses"] = expenses
    return total

# ---------- КЛАВИАТУРЫ ----------

def main_admin_keyboard():
    keyboard = [
        [KeyboardButton("📊 Метрики за день"), KeyboardButton("📈 Метрики за период")],
        [KeyboardButton("📅 Месяц"), KeyboardButton("🗓️ Квартал")],
        [KeyboardButton("📆 Год"), KeyboardButton("📉 Динамика продаж")],
        [KeyboardButton("👥 Управление менеджерами"), KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def main_user_keyboard():
    keyboard = [
        [KeyboardButton("📊 Метрики за день"), KeyboardButton("📈 Метрики за период")],
        [KeyboardButton("📅 Месяц"), KeyboardButton("🗓️ Квартал")],
        [KeyboardButton("📆 Год"), KeyboardButton("📉 Динамика продаж")],
        [KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
