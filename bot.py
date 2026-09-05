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
ADMIN_CHAT_ID = 6134182006

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
# новые состояния для отчёта по товарам
WAITING_PRODUCT_DATE = 15
WAITING_PRODUCT_PERIOD_TYPE = 16
WAITING_PRODUCT_PERIOD_START = 17
WAITING_PRODUCT_PERIOD_END = 18
WAITING_PRODUCT_PERIOD_YEAR = 19
WAITING_PRODUCT_PERIOD_MONTH = 20
WAITING_PRODUCT_PERIOD_QUARTER = 21
WAITING_PRODUCT_YEAR_SELECT = 22
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

# ---------- Функции для получения данных Ozon (отгрузки) ----------
def fetch_postings(date_from, date_to):
    headers = {
        "Client-Id": OZON_CLIENT_ID,
        "Api-Key": OZON_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "date_from": date_from,
        "date_to": date_to,
        "status": "",
        "limit": 1000,
        "offset": 0,
    }
    all_postings = []
    while True:
        try:
            response = requests.post(OZON_POSTING_FBO_URL, headers=headers, json=payload, timeout=15)
            if response.status_code == 429:
                time.sleep(10)
                continue
            response.raise_for_status()
            data = response.json()
            postings = data.get("result", [])
            if not postings:
                break
            all_postings.extend(postings)
            if len(postings) < payload["limit"]:
                break
            payload["offset"] += payload["limit"]
        except Exception as e:
            write_log(f"❌ Ошибка получения отгрузок: {e}")
            break
    write_log(f"📦 Загружено отгрузок: {len(all_postings)} за {date_from}–{date_to}")
    return all_postings

def aggregate_postings(postings, date_from=None, date_to=None, time_limit=None, apply_limit_on_day=None):
    aggregated = {}
    for posting in postings:
        created_at = posting.get("created_at", "")
        if not created_at:
            continue
        try:
            dt = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            dt_msk = dt.astimezone(MOSCOW_TZ)
        except:
            continue
        date_str = dt_msk.date().isoformat()
        if date_from and date_str < date_from:
            continue
        if date_to and date_str > date_to:
            continue

        if time_limit is not None and apply_limit_on_day is not None and date_str == apply_limit_on_day:
            if dt_msk.time() > time_limit:
                continue

        products = posting.get("products", [])
        total_units = 0
        total_sum = 0.0
        for product in products:
            qty = int(product.get("quantity", 0))
            price_str = product.get("price", "0")
            try:
                price = float(price_str)
            except:
                price = 0.0
            total_units += qty
            total_sum += price * qty

        status = posting.get("status", "")
        if date_str not in aggregated:
            aggregated[date_str] = {
                "ordered_units": 0,
                "ordered_sum": 0.0,
                "delivered_units": 0,
                "delivered_sum": 0.0,
                "canceled_units": 0,
                "canceled_sum": 0.0,
            }

        aggregated[date_str]["ordered_units"] += total_units
        aggregated[date_str]["ordered_sum"] += total_sum

        if status in ("cancelled", "canceled"):
            aggregated[date_str]["canceled_units"] += total_units
            aggregated[date_str]["canceled_sum"] += total_sum
        elif status in ("delivered", "completed"):
            aggregated[date_str]["delivered_units"] += total_units
            aggregated[date_str]["delivered_sum"] += total_sum

    return aggregated

# ---------- АГРЕГАЦИЯ ПО ТОВАРАМ ----------
def aggregate_by_products(postings, date_from=None, date_to=None, time_limit=None, apply_limit_on_day=None):
    product_stats = {}
    for posting in postings:
        created_at = posting.get("created_at", "")
        if not created_at:
            continue
        try:
            dt = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            dt_msk = dt.astimezone(MOSCOW_TZ)
        except:
            continue
        date_str = dt_msk.date().isoformat()
        if date_from and date_str < date_from:
            continue
        if date_to and date_str > date_to:
            continue
        if time_limit is not None and apply_limit_on_day is not None and date_str == apply_limit_on_day:
            if dt_msk.time() > time_limit:
                continue

        status = posting.get("status", "")
        for product in posting.get("products", []):
            sku = product.get("sku")
            if not sku:
                continue
            name = product.get("name", "Без названия")
            qty = int(product.get("quantity", 0))
            price_str = product.get("price", "0")
            try:
                price = float(price_str)
            except:
                price = 0.0
            if sku not in product_stats:
                product_stats[sku] = {
                    "name": name,
                    "ordered_units": 0,
                    "ordered_sum": 0.0,
                    "delivered_units": 0,
                    "delivered_sum": 0.0,
                    "canceled_units": 0,
                    "canceled_sum": 0.0,
                    "order_count": 0,
                }
            stats = product_stats[sku]
            stats["ordered_units"] += qty
            stats["ordered_sum"] += price * qty
            stats["order_count"] += 1
            if status in ("delivered", "completed"):
                stats["delivered_units"] += qty
                stats["delivered_sum"] += price * qty
            elif status in ("cancelled", "canceled"):
                stats["canceled_units"] += qty
                stats["canceled_sum"] += price * qty
    return product_stats

# ---------- Функции для получения рекламных расходов (Performance) с разбивкой по месяцам ----------
def get_performance_token():
    if not OZON_PERFORMANCE_CLIENT_ID or not OZON_PERFORMANCE_CLIENT_SECRET:
        write_log("⚠️ OZON_PERFORMANCE_CLIENT_ID или CLIENT_SECRET не заданы!")
        return None

    url = "https://api-performance.ozon.ru/api/client/token"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "client_id": OZON_PERFORMANCE_CLIENT_ID,
        "client_secret": OZON_PERFORMANCE_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        token_data = response.json()
        token = token_data.get("access_token")
        if token:
            write_log("✅ Токен Performance API успешно получен.")
            return token
        else:
            write_log(f"❌ Ошибка получения токена: {token_data}")
            return None
    except Exception as e:
        write_log(f"❌ Ошибка при запросе токена: {e}")
        return None

def fetch_advertising_expense_single(date_from, date_to):
    token = get_performance_token()
    if not token:
        return 0.0

    url = "https://api-performance.ozon.ru/api/client/statistics/expense/json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 429:
            write_log("⚠️ 429 Too Many Requests, ждём 10 сек")
            time.sleep(10)
            response = requests.get(url, headers=headers, params=params, timeout=15)

        if response.status_code == 400:
            error_text = response.text
            if "interval of report is in the future" in error_text:
                write_log(f"⏭️ Пропускаем будущий период: {date_from}–{date_to}")
            else:
                write_log(f"⚠️ Performance API вернул 400 для {date_from}–{date_to}: {error_text[:200]}")
            return 0.0

        response.raise_for_status()
        data = response.json()
        total_expense = 0.0
        if isinstance(data, dict) and "rows" in data:
            rows = data["rows"]
            if isinstance(rows, list):
                for item in rows:
                    item_date = item.get("date")
                    if item_date and len(item_date) >= 10:
                        item_date_str = item_date[:10]
                        if date_from <= item_date_str <= date_to:
                            money_spent_str = item.get("moneySpent")
                            if money_spent_str is not None:
                                try:
                                    money_spent = float(money_spent_str.replace(",", "."))
                                    total_expense += money_spent
                                except:
                                    pass
        return total_expense
    except Exception as e:
        write_log(f"❌ Ошибка получения рекламных расходов: {e}")
        return 0.0

def fetch_advertising_expense(date_from, date_to):
    start_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
    today = get_moscow_today()
    if start_dt.date() > today:
        return 0.0
    if end_dt.date() > today:
        end_dt = datetime.datetime.combine(today, datetime.time(23, 59, 59))

    delta = (end_dt - start_dt).days
    if delta <= 90:
        return fetch_advertising_expense_single(date_from, end_dt.strftime("%Y-%m-%d"))

    total = 0.0
    current = start_dt.replace(day=1)
    while current <= end_dt:
        month_start = current.strftime("%Y-%m-%d")
        next_month = current.replace(day=28) + datetime.timedelta(days=4)
        month_end = (next_month - datetime.timedelta(days=next_month.day)).strftime("%Y-%m-%d")
        if month_end > end_dt.strftime("%Y-%m-%d"):
            month_end = end_dt.strftime("%Y-%m-%d")
        if current.date() > today:
            break
        write_log(f"📊 Запрос рекламы за {month_start}–{month_end}")
        total += fetch_advertising_expense_single(month_start, month_end)
        current = current.replace(day=28) + datetime.timedelta(days=4)
        current = current.replace(day=1)
    return total

# ---------- Функции для финансовых транзакций с разбивкой по месяцам ----------
def fetch_finance_transactions_single(date_from, date_to):
    today_str = get_moscow_today().isoformat()
    if date_from > today_str:
        return []
    if date_to > today_str:
        date_to = today_str

    headers = {
        "Client-Id": OZON_CLIENT_ID,
        "Api-Key": OZON_API_KEY,
        "Content-Type": "application/json",
    }

    from_iso = date_from + "T00:00:00.000Z"
    to_iso = date_to + "T23:59:59.999Z"

    all_transactions = []
    page = 1
    page_size = 1000

    while True:
        payload = {
            "filter": {
                "date": {
                    "from": from_iso,
                    "to": to_iso
                }
            },
            "page": page,
            "page_size": page_size,
        }

        try:
            response = requests.post(OZON_FINANCE_URL, headers=headers, json=payload, timeout=15)

            if response.status_code == 429:
                time.sleep(10)
                continue

            if response.status_code == 400:
                write_log(f"⚠️ Finance API вернул 400 для {date_from}–{date_to}: {response.text[:200]}")
                break

            response.raise_for_status()
            data = response.json()
            items = data.get("result", {}).get("operations", [])
            if not items:
                break

            all_transactions.extend(items)
            if len(items) < page_size:
                break
            page += 1

        except requests.exceptions.HTTPError as e:
            error_text = e.response.text if e.response else str(e)
            write_log(f"❌ Ошибка получения финансовых транзакций: {e}, ответ: {error_text[:500]}")
            break
        except Exception as e:
            write_log(f"❌ Ошибка получения финансовых транзакций: {e}")
            break

    return all_transactions

def fetch_finance_transactions(date_from, date_to):
    start_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
    today = get_moscow_today()
    if start_dt.date() > today:
        return []
    if end_dt.date() > today:
        end_dt = datetime.datetime.combine(today, datetime.time(23, 59, 59))

    delta = (end_dt - start_dt).days
    if delta <= 90:
        return fetch_finance_transactions_single(date_from, end_dt.strftime("%Y-%m-%d"))

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
    return all_transactions

# ---------- АГРЕГАЦИЯ ФИНАНСОВЫХ РАСХОДОВ (без доходов) ----------
def aggregate_finance_expenses(transactions):
    expense_by_type = {}
    unique_types = set()
    unique_services = set()
    sample_count = 0
    for t in transactions:
        if sample_count < 10:
            services = t.get("services", [])
            if services:
                write_log(f"🔍 Пример транзакции: amount={t.get('amount')}, operation_type={t.get('operation_type_name')}, sale_commission={t.get('sale_commission')}, accruals_for_sale={t.get('accruals_for_sale')}, services={json.dumps(services, ensure_ascii=False)}")
                sample_count += 1

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

    if transactions:
        write_log(f"🔍 Найдены operation_type: {', '.join(unique_types)}")
        if unique_services:
            write_log(f"🔍 Найдены услуги (services): {', '.join(unique_services)}")
        if expense_by_type:
            write_log(f"🔍 Итоговые категории расходов: {', '.join(expense_by_type.keys())}")

    return expense_by_type

# ---------- ФОРМАТИРОВАНИЕ БЛОКОВ ----------
def format_expense_block(expenses_by_type, title):
    if not expenses_by_type:
        return f"🔹 *{title}*\nНет данных о расходах.\n"

    total = sum(expenses_by_type.values())
    lines = [f"🔹 *{title}*", f"  *Итого расходов:* {total:,.2f} ₽"]

    name_map = {
        "Комиссия Ozon": "Комиссия",
        "Оплата эквайринга": "Эквайринг",
        "Доставка покупателю": "Доставка покупателю",
        "Доставка и обработка возврата, отмены, невыкупа": "Доставка/возвраты",
        "Кросс-докинг": "Кросс-докинг",
        "Страхование товара от массовых повреждений": "Страхование",
        "Обеспечение материалами для упаковки товара": "Обеспечение упаковкой",
        "Упаковка товара партнёрами": "Упаковка",
        "Подписка Управление отзывами": "Подписка",
        "Оплата за клик": "Оплата за клик",
        "Получение возврата, отмены, невыкупа от покупателя": "Получение возвратов",
        "MarketplaceServiceItemDirectFlowLogistic": "Логистика прямая",
        "MarketplaceServiceItemRedistributionLastMileCourier": "Логистика последняя миля",
        "MarketplaceServiceItemReturnFlowLogistic": "Логистика возврат",
        "MarketplaceServiceItemDeliveryToHandoverPlaceOzon": "Доставка до ПВЗ",
        "MarketplaceRedistributionOfAcquiringOperation": "Эквайринг",
        "MarketplaceServiceItemRedistributionReturnsPVZ": "Обработка возвратов (ПВЗ)",
        "MarketplaceServiceItemPackageRedistribution": "Переупаковка",
        "MarketplaceServiceItemPackageMaterialsProvision": "Обеспечение упаковкой",
        "MarketplaceServiceItemProductReviewsManagementSubscription": "Подписка",
        "MarketplaceServiceItemRedistributionLastMilePVZ": "Логистика последняя миля (ПВЗ)",
        "MarketplaceServiceItemDirectFlowLogisticFBS": "Логистика прямая (FBS)",
        "MarketplaceServiceItemReturnFlowLogisticFBS": "Логистика возврат (FBS)",
        "ItemAgentServiceStarsMembership": "Звёздные товары",
        "MarketplaceServiceSellerReturnsCargoAssortment": "Обработка возвратов партнёрами",
        "MarketplaceServiceItemTemporaryStorageRedistribution": "Временное размещение",
        "MarketplaceServiceProductMovementFromWarehouse": "Вывоз до ПВЗ",
        "MarketplaceServiceItemDisposalDetailed": "Утилизация",
        "Звёздные товары": "Звёздные товары",
        "Временное размещение товара партнерами": "Временное размещение",
        "Обработка товара в составе грузоместа: Поштучная приёмка": "Поштучная приёмка",
        "Обработка товара в составе грузоместа на FBO": "Поштучная приёмка",
        "Подготовка товара к вывозу: Брак": "Подготовка к вывозу (брак)",
        "Вывоз товара со склада силами Ozon: Доставка до ПВЗ": "Вывоз до ПВЗ",
        "Вывоз товара со Склада силами Ozon: Доставка до ПВЗ": "Вывоз до ПВЗ",
        "Бронирование места и персонала для поставки с неполным составом в составе грузоместа": "Бронирование места",
        "Услуга по бронированию места и персонала для поставки с неполным составом в составе ГМ": "Бронирование места",
        "Обработка опознанных излишков в составе грузоместа": "Обработка излишков",
        "Услуга по обработке опознанных излишков в составе ГМ": "Обработка излишков",
        "Утилизация товара: Пролились/просыпались из-за упаковки": "Утилизация",
        "Потеря по вине Ozon на складе": "Потеря (склад)",
        "Потеря по вине Ozon в логистике": "Потеря (логистика)",
        "Вознаграждение за продажу": "Вознаграждение",
        "Возврат вознаграждения": "Возврат вознаграждения",
        "Программы партнёров": "Программы партнёров",
        "Баллы за скидки": "Баллы за скидки",
        "Выручка": "Выручка",
        "Возврат выручки": "Возврат выручки",
        "Реклама": "Реклама",
    }

    sorted_items = sorted(expenses_by_type.items(), key=lambda x: x[1], reverse=True)

    for category, amount in sorted_items:
        if category in name_map:
            short_name = name_map[category]
        else:
            found = False
            for key, value in name_map.items():
                if key in category or category in key:
                    short_name = value
                    found = True
                    break
            if not found:
                short_name = category[:40]
                write_log(f"⚠️ Не найдено соответствие для категории: {category}")
        lines.append(f"    {short_name}: {amount:,.2f} ₽")

    return "\n".join(lines)

# ---------- ФОРМАТИРОВАНИЕ ДЛЯ ТОВАРОВ ----------
def format_product_block(product_stats, title, top_n=10):
    if not product_stats:
        return f"🔹 *{title}*\nНет данных по товарам за указанный период.\n"
    # сортировка по выручке
    sorted_products = sorted(product_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
    top = sorted_products[:top_n]
    lines = [f"🔹 *{title}*"]
    total_revenue = sum(p[1]["ordered_sum"] for p in top)
    total_units = sum(p[1]["ordered_units"] for p in top)
    lines.append(f"  *Топ-{len(top)} товаров по выручке*")
    for idx, (sku, stats) in enumerate(top, 1):
        name = stats.get("name", "Без названия")[:40]
        ordered_sum = stats["ordered_sum"]
        ordered_units = stats["ordered_units"]
        delivered_sum = stats["delivered_sum"]
        canceled_sum = stats["canceled_sum"]
        avg_check = ordered_sum / stats["order_count"] if stats["order_count"] else 0
        lines.append(
            f"  {idx}. *{name}*\n"
            f"    🛒 Заказано: {ordered_sum:,.2f} ₽ / {ordered_units} шт.\n"
            f"    📦 Доставлено: {delivered_sum:,.2f} ₽\n"
            f"    ❌ Отменено: {canceled_sum:,.2f} ₽\n"
            f"    💰 Средний чек: {avg_check:,.2f} ₽"
        )
    return "\n".join(lines)

def format_product_summary(stats, title):
    # краткая сводка: общая выручка, кол-во товаров, кол-во заказов, средний чек
    total_revenue = sum(p["ordered_sum"] for p in stats.values())
    total_units = sum(p["ordered_units"] for p in stats.values())
    total_orders = sum(p["order_count"] for p in stats.values())
    avg_check = total_revenue / total_orders if total_orders else 0
    return (
        f"📊 *{title}*\n"
        f"  Товаров: {len(stats)}\n"
        f"  Выручка: {total_revenue:,.2f} ₽\n"
        f"  Штук: {total_units}\n"
        f"  Заказов: {total_orders}\n"
        f"  Средний чек: {avg_check:,.2f} ₽"
    )

# ---------- Остальные вспомогательные функции ----------
def get_current_time_msk():
    return datetime.datetime.now(MOSCOW_TZ)

def format_combined_metrics_with_deltas(include_yesterday=False):
    now = get_current_time_msk()
    today_date = now.date()
    current_time = now.time()
    today_str = today_date.isoformat()
    yesterday_date = today_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()

    current_month_start = today_date.replace(day=1)
    current_month_start_str = current_month_start.isoformat()
    current_month_end_str = today_str

    previous_month_start = (current_month_start - datetime.timedelta(days=1)).replace(day=1)
    previous_month_start_str = previous_month_start.isoformat()
    previous_month_end = current_month_start - datetime.timedelta(days=1)
    previous_month_end_str = previous_month_end.isoformat()

    days_passed = (today_date - current_month_start).days + 1

    postings_current = fetch_postings(current_month_start_str, current_month_end_str)
    postings_prev = fetch_postings(previous_month_start_str, previous_month_end_str)

    agg_yesterday_full = aggregate_postings(
        postings_current,
        date_from=yesterday_str,
        date_to=yesterday_str
    )
    yesterday_full_metrics = agg_yesterday_full.get(yesterday_str, {}) if yesterday_str in agg_yesterday_full else {}

    agg_today = aggregate_postings(
        postings_current,
        date_from=today_str,
        date_to=today_str,
        time_limit=current_time,
        apply_limit_on_day=today_str
    )
    today_metrics = agg_today.get(today_str, {}) if today_str in agg_today else {}

    agg_yesterday = aggregate_postings(
        postings_current,
        date_from=yesterday_str,
        date_to=yesterday_str,
        time_limit=current_time,
        apply_limit_on_day=yesterday_str
    )
    yesterday_metrics = agg_yesterday.get(yesterday_str, {}) if yesterday_str in agg_yesterday else {}

    agg_current_month = aggregate_postings(
        postings_current,
        date_from=current_month_start_str,
        date_to=current_month_end_str,
        time_limit=current_time,
        apply_limit_on_day=today_str
    )
    month_metrics = {
        "ordered_units": 0,
        "ordered_sum": 0.0,
        "delivered_units": 0,
        "delivered_sum": 0.0,
        "canceled_units": 0,
        "canceled_sum": 0.0,
    }
    for vals in agg_current_month.values():
        for key in month_metrics:
            month_metrics[key] += vals.get(key, 0)

    prev_period_end = previous_month_start + datetime.timedelta(days=days_passed - 1)
    prev_period_end_str = prev_period_end.isoformat()
    agg_prev_month = aggregate_postings(
        postings_prev,
        date_from=previous_month_start_str,
        date_to=prev_period_end_str,
        time_limit=current_time,
        apply_limit_on_day=prev_period_end_str
    )
    prev_month_metrics = {
        "ordered_units": 0,
        "ordered_sum": 0.0,
        "delivered_units": 0,
        "delivered_sum": 0.0,
        "canceled_units": 0,
        "canceled_sum": 0.0,
    }
    for vals in agg_prev_month.values():
        for key in prev_month_metrics:
            prev_month_metrics[key] += vals.get(key, 0)

    ad_today = fetch_advertising_expense(today_str, today_str)
    ad_yesterday = fetch_advertising_expense(yesterday_str, yesterday_str)

    ad_month = fetch_advertising_expense(current_month_start_str, today_str)
    ad_prev_period = fetch_advertising_expense(previous_month_start_str, prev_period_end_str)

    expenses_today = aggregate_finance_expenses(fetch_finance_transactions(today_str, today_str))
    expenses_month = aggregate_finance_expenses(fetch_finance_transactions(current_month_start_str, today_str))

    if ad_today > 0:
        expenses_today["Реклама"] = ad_today
    if ad_month > 0:
        expenses_month["Реклама"] = ad_month

    def fmt_num(val):
        return f"{val:,.2f}".replace(",", " ") if val else "0.00"

    def fmt_int(val):
        return str(val) if val else "0"

    def fmt_pct(val):
        if val is None:
            return "∞"
        if val > 0:
            return f"+{val:.1f}%"
        elif val < 0:
            return f"{val:.1f}%"
        else:
            return f"{val:.1f}%"

    def calc_delta(current, previous):
        if previous == 0:
            return None
        try:
            return ((current - previous) / abs(previous)) * 100
        except:
            return None

    d_ord_sum = calc_delta(today_metrics.get("ordered_sum", 0), yesterday_metrics.get("ordered_sum", 0))
    d_ord_units = calc_delta(today_metrics.get("ordered_units", 0), yesterday_metrics.get("ordered_units", 0))
    d_ad = calc_delta(ad_today, ad_yesterday)

    d_ord_sum_m = calc_delta(month_metrics.get("ordered_sum", 0), prev_month_metrics.get("ordered_sum", 0))
    d_ord_units_m = calc_delta(month_metrics.get("ordered_units", 0), prev_month_metrics.get("ordered_units", 0))
    d_del_sum_m = calc_delta(month_metrics.get("delivered_sum", 0), prev_month_metrics.get("delivered_sum", 0))
    d_del_units_m = calc_delta(month_metrics.get("delivered_units", 0), prev_month_metrics.get("delivered_units", 0))
    d_can_sum_m = calc_delta(month_metrics.get("canceled_sum", 0), prev_month_metrics.get("canceled_sum", 0))
    d_can_units_m = calc_delta(month_metrics.get("canceled_units", 0), prev_month_metrics.get("canceled_units", 0))
    d_ad_m = calc_delta(ad_month, ad_prev_period)

    def format_today_block():
        ordered_sum = fmt_num(today_metrics.get("ordered_sum", 0))
        ordered_units = fmt_int(today_metrics.get("ordered_units", 0))
        canceled_sum = fmt_num(today_metrics.get("canceled_sum", 0))
        canceled_units = fmt_int(today_metrics.get("canceled_units", 0))

        delta_ord_sum = fmt_pct(d_ord_sum)
        delta_ord_units = fmt_pct(d_ord_units)
        delta_can_sum = fmt_pct(calc_delta(today_metrics.get("canceled_sum", 0), yesterday_metrics.get("canceled_sum", 0)))
        delta_can_units = fmt_pct(calc_delta(today_metrics.get("canceled_units", 0), yesterday_metrics.get("canceled_units", 0)))

        return (
            f"🔹 *Сегодня (на {now.strftime('%H:%M')} МСК)*\n"
            f"  🛒 Заказано: \n  {ordered_sum} ₽ / {ordered_units} шт.\n"
            f"    vs Вчера: \n  {delta_ord_sum} ₽ / {delta_ord_units} шт.\n\n"
            f"  ❌ Отменено: \n  {canceled_sum} ₽ / {canceled_units} шт.\n"
            f"    vs Вчера: \n  {delta_can_sum} ₽ / {delta_can_units} шт."
        )

    def format_month_block():
        ordered_sum = fmt_num(month_metrics.get("ordered_sum", 0))
        ordered_units = fmt_int(month_metrics.get("ordered_units", 0))
        delivered_sum = fmt_num(month_metrics.get("delivered_sum", 0))
        delivered_units = fmt_int(month_metrics.get("delivered_units", 0))
        canceled_sum = fmt_num(month_metrics.get("canceled_sum", 0))
        canceled_units = fmt_int(month_metrics.get("canceled_units", 0))
        ad_expense = fmt_num(ad_month)
        ad_prev = fmt_num(ad_prev_period)

        revenue = month_metrics.get("ordered_sum", 0)
        drr = (ad_month / revenue * 100) if revenue > 0 else None
        delivered_revenue = month_metrics.get("delivered_sum", 0)
        eff_drr = (ad_month / delivered_revenue * 100) if delivered_revenue > 0 else None

        prev_rev = prev_month_metrics.get("ordered_sum", 0)
        prev_del_rev = prev_month_metrics.get("delivered_sum", 0)
        prev_drr_val = (ad_prev_period / prev_rev * 100) if prev_rev > 0 else None
        prev_eff_drr_val = (ad_prev_period / prev_del_rev * 100) if prev_del_rev > 0 else None

        drr_str = f"{drr:.2f}%" if drr is not None else "∞"
        eff_drr_str = f"{eff_drr:.2f}%" if eff_drr is not None else "∞"
        prev_drr_str = f"{prev_drr_val:.2f}%" if prev_drr_val is not None else "∞"
        prev_eff_drr_str = f"{prev_eff_drr_val:.2f}%" if prev_eff_drr_val is not None else "∞"

        delta_ord_sum_m = fmt_pct(d_ord_sum_m)
        delta_ord_units_m = fmt_pct(d_ord_units_m)
        delta_del_sum_m = fmt_pct(d_del_sum_m)
        delta_del_units_m = fmt_pct(d_del_units_m)
        delta_can_sum_m = fmt_pct(d_can_sum_m)
        delta_can_units_m = fmt_pct(d_can_units_m)

        return (
            f"🔹 *Текущий месяц*\n"
            f"  🛒 Заказано: \n  {ordered_sum} ₽ / {ordered_units} шт.\n"
            f"    vs предыдущий месяц: \n  {delta_ord_sum_m} ₽ / {delta_ord_units_m} шт.\n\n"
            f"  📦 Доставлено: \n  {delivered_sum} ₽ / {delivered_units} шт.\n"
            f"    vs предыдущий месяц: \n  {delta_del_sum_m} ₽ / {delta_del_units_m} шт.\n\n"
            f"  ❌ Отменено: \n  {canceled_sum} ₽ / {canceled_units} шт.\n"
            f"    vs предыдущий месяц: \n  {delta_can_sum_m} ₽ / {delta_can_units_m} шт.\n\n"
            f"  📢 Реклама: \n  {ad_expense} ₽ | vs предыдущий месяц: {ad_prev} ₽\n"
            f"  ДРР общ: {drr_str} | vs предыдущий месяц: {prev_drr_str}\n"
            f"  ДРР дост: {eff_drr_str} | vs предыдущий месяц: {prev_eff_drr_str}"
        )

    parts = []
    parts.append(format_today_block())
    parts.append(format_month_block())

    parts.append(format_expense_block(expenses_today, "Расходы сегодня"))
    parts.append(format_expense_block(expenses_month, "Расходы за текущий месяц"))

    return "📊 *Продажи за сегодня*\n\n\n" + "\n\n".join(parts)

# ---------- ФУНКЦИИ ДЛЯ ТОВАРНЫХ ОТЧЁТОВ ----------
def get_product_report_today():
    now = get_current_time_msk()
    today_str = now.date().isoformat()
    current_time = now.time()
    # за сегодня с учётом времени
    postings = fetch_postings(today_str, today_str)
    # фильтр по времени выполняется в агрегации
    prod_stats = aggregate_by_products(postings, date_from=today_str, date_to=today_str, time_limit=current_time, apply_limit_on_day=today_str)
    # сортировка по выручке
    sorted_prod = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
    top10 = sorted_prod[:10]
    return top10

def get_product_report_month():
    now = get_current_time_msk()
    today_date = now.date()
    current_time = now.time()
    month_start = today_date.replace(day=1)
    month_start_str = month_start.isoformat()
    today_str = today_date.isoformat()
    postings = fetch_postings(month_start_str, today_str)
    prod_stats = aggregate_by_products(postings, date_from=month_start_str, date_to=today_str, time_limit=current_time, apply_limit_on_day=today_str)
    sorted_prod = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
    top10 = sorted_prod[:10]
    return top10

def format_product_top_block(top_list, title, total_stats=None):
    if not top_list:
        return f"🔹 *{title}*\nНет данных по товарам за указанный период.\n"
    lines = [f"🔹 *{title}*"]
    if total_stats:
        lines.append(f"  *Всего товаров: {len(total_stats)}*")
    for idx, (sku, stats) in enumerate(top_list, 1):
        name = stats.get("name", "Без названия")[:40]
        ordered_sum = stats["ordered_sum"]
        ordered_units = stats["ordered_units"]
        delivered_sum = stats["delivered_sum"]
        canceled_sum = stats["canceled_sum"]
        avg_check = ordered_sum / stats["order_count"] if stats["order_count"] else 0
        lines.append(
            f"  {idx}. *{name}*\n"
            f"    🛒 Заказано: {ordered_sum:,.2f} ₽ / {ordered_units} шт.\n"
            f"    📦 Доставлено: {delivered_sum:,.2f} ₽\n"
            f"    ❌ Отменено: {canceled_sum:,.2f} ₽\n"
            f"    💰 Средний чек: {avg_check:,.2f} ₽"
        )
    return "\n".join(lines)

def format_product_period_summary(prod_stats, title):
    if not prod_stats:
        return f"📊 *{title}*\nНет данных по товарам за указанный период.\n"
    total_revenue = sum(p["ordered_sum"] for p in prod_stats.values())
    total_units = sum(p["ordered_units"] for p in prod_stats.values())
    total_orders = sum(p["order_count"] for p in prod_stats.values())
    avg_check = total_revenue / total_orders if total_orders else 0
    return (
        f"📊 *{title}*\n"
        f"  Товаров: {len(prod_stats)}\n"
        f"  Выручка: {total_revenue:,.2f} ₽\n"
        f"  Штук: {total_units}\n"
        f"  Заказов: {total_orders}\n"
        f"  Средний чек: {avg_check:,.2f} ₽"
    )

# ---------- ОСНОВНЫЕ ФУНКЦИИ ДЛЯ ОТЧЁТОВ (продажи) ----------
def format_single_metrics(metrics, title):
    if not metrics:
        return f"📊 *{title}*\n\n❌ Нет данных за указанный период."
    has_data = False
    for key, val in metrics.items():
        if key in ["drr", "effective_drr", "ad_expense", "expenses"]:
            continue
        if isinstance(val, (int, float)) and val != 0:
            has_data = True
            break
    if not has_data:
        return f"📊 *{title}*\n\n❌ Нет данных за указанный период."

    ad_expense = metrics.get("ad_expense", 0)
    drr = metrics.get("drr")
    eff_drr = metrics.get("effective_drr")
    drr_text = f"{drr:.2f}%" if drr is not None else "∞"
    eff_drr_text = f"{eff_drr:.2f}%" if eff_drr is not None else "∞"

    main_text = (
        f"📊 *{title}*\n\n"
        f"🛒 *Заказано*\n  На сумму: {metrics.get('ordered_sum', 0):,.2f} ₽\n"
        f"  Штук: {metrics.get('ordered_units', 0)}\n\n"
        f"📦 *Доставлено*\n  На сумму: {metrics.get('delivered_sum', 0):,.2f} ₽\n"
        f"  Штук: {metrics.get('delivered_units', 0)}\n\n"
        f"❌ *Отменено*\n  На сумму: {metrics.get('canceled_sum', 0):,.2f} ₽\n"
        f"  Штук: {metrics.get('canceled_units', 0)}\n\n"
        f"📢 *Реклама*\n"
        f"  Расходы: {ad_expense:,.2f} ₽\n"
        f"  ДРР (общий): {drr_text}\n"
        f"  ДРР (по доставленным): {eff_drr_text}"
    )

    expenses = metrics.get("expenses", {})
    if expenses:
        expense_block = format_expense_block(expenses, "Расходы за период")
        main_text += "\n\n" + expense_block

    return main_text

def get_metrics_for_date(date_str):
    today = get_moscow_today()
    start = (today - datetime.timedelta(days=183)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    postings = fetch_postings(start, end)
    agg = aggregate_postings(postings, date_from=date_str, date_to=date_str)
    metrics = agg.get(date_str, {})
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

# ---------- ФУНКЦИИ ДЛЯ ТОВАРНЫХ ОТЧЁТОВ (периоды) ----------
def get_product_stats_for_date(date_str):
    postings = fetch_postings(date_str, date_str)
    return aggregate_by_products(postings, date_from=date_str, date_to=date_str)

def get_product_stats_for_period(date_from, date_to):
    postings = fetch_postings(date_from, date_to)
    return aggregate_by_products(postings, date_from=date_from, date_to=date_to)

# ---------- КЛАВИАТУРЫ ----------
def main_admin_keyboard():
    buttons = [
        [KeyboardButton("📊 Отчёт по продажам")],
        [KeyboardButton("📦 Отчёт по товарам")],
        [KeyboardButton("⚙️ Администрирование")],
        [KeyboardButton("📖 Справка")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def main_user_keyboard():
    buttons = [
        [KeyboardButton("📊 Отчёт по продажам")],
        [KeyboardButton("📦 Отчёт по товарам")],
        [KeyboardButton("📖 Справка")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def reports_keyboard():
    buttons = [
        [KeyboardButton("📅 Продажи за сегодня")],
        [KeyboardButton("📆 Выбрать дату")],
        [KeyboardButton("📊 Выбрать период")],
        [KeyboardButton("📈 Динамика продаж")],
        [KeyboardButton("🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def product_reports_keyboard():
    buttons = [
        [KeyboardButton("📅 Топ товаров за сегодня")],
        [KeyboardButton("📆 Выбрать дату")],
        [KeyboardButton("📊 Выбрать период")],
        [KeyboardButton("📈 Динамика продаж по товару")],
        [KeyboardButton("🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def admin_keyboard():
    buttons = [
        [KeyboardButton("➕ Добавить менеджера"), KeyboardButton("➖ Удалить менеджера")],
        [KeyboardButton("📋 Список менеджеров")],
        [KeyboardButton("🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if is_admin(chat_id):
        name = user.first_name if user.first_name else ""
        greeting = get_greeting(name)
        await update.message.reply_text(greeting, reply_markup=main_admin_keyboard())
    elif is_manager(chat_id):
        manager = get_manager_info(chat_id)
        name = manager.get("first_name") if manager and manager.get("first_name") else user.first_name or ""
        greeting = get_greeting(name)
        await update.message.reply_text(greeting, reply_markup=main_user_keyboard())
    else:
        await update.message.reply_text("❌ Нет доступа! Обратитесь к администратору.", reply_markup=ReplyKeyboardRemove())

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "📊 Отчёт по продажам":
        if not has_access(chat_id):
            await update.message.reply_text("❌ Нет доступа! Обратитесь к администратору.")
            return
        await update.message.reply_text("Выберите тип отчёта по продажам:", reply_markup=reports_keyboard())
        return

    if text == "📦 Отчёт по товарам":
        if not has_access(chat_id):
            await update.message.reply_text("❌ Нет доступа! Обратитесь к администратору.")
            return
        await update.message.reply_text("Выберите тип товарного отчёта:", reply_markup=product_reports_keyboard())
        return

    if text == "⚙️ Администрирование":
        if not is_admin(chat_id):
            await update.message.reply_text("⛔ Только для администратора.")
            return
        await update.message.reply_text("Управление менеджерами:", reply_markup=admin_keyboard())
        return

    if text == "📖 Справка":
        if is_admin(chat_id):
            help_text = (
                "📖 *Справка для администратора*\n\n"
                "🔹 *Основные функции*\n"
                "• 📊 Отчёт по продажам – сводка по продажам за сегодня и текущий месяц.\n"
                "• 📦 Отчёт по товарам – аналитика по товарам (топ, динамика).\n"
                "• ⚙️ Администрирование – управление доступом менеджеров.\n\n"
                "🔹 *Отчёт по продажам*\n"
                "• 📅 Продажи за сегодня – быстрый доступ к сводке.\n"
                "• 📆 Выбрать дату – просмотр за конкретный день.\n"
                "• 📊 Выбрать период – месяц, квартал, год, произвольный.\n"
                "• 📈 Динамика продаж – график по доставленным заказам.\n\n"
                "🔹 *Отчёт по товарам*\n"
                "• 📅 Топ товаров за сегодня – топ‑10 по выручке за сегодня и месяц.\n"
                "• 📆 Выбрать дату – топ‑15 товаров за выбранную дату.\n"
                "• 📊 Выбрать период – топ‑20 товаров за период + сводка.\n"
                "• 📈 Динамика продаж по товару – пока в разработке.\n\n"
                "🔹 *Метрики*\n"
                "• 🛒 Заказано – сумма и количество.\n"
                "• 📦 Доставлено – сумма и количество.\n"
                "• ❌ Отменено – сумма и количество.\n"
                "• 📢 Реклама – расходы, ДРР общий и по доставленным.\n"
                "• 💰 Расходы (финансовые) – комиссии, логистика, эквайринг, кросс-докинг, страхование, упаковка и др.\n\n"
                "🔹 *Сравнение динамики*\n"
                "• Для «Сегодня» – сравнение с аналогичным временем вчера.\n"
                "• Для «Текущий месяц» – сравнение с аналогичным периодом предыдущего месяца (с учётом времени).\n\n"
                "🔹 *Часовой пояс*\n"
                "• Все расчёты ведутся по московскому времени (МСК, UTC+3).\n"
            )
        else:
            help_text = (
                "📖 *Справка для менеджера*\n\n"
                "🔹 *Основные функции*\n"
                "• 📊 Отчёт по продажам – сводка по продажам за сегодня и текущий месяц.\n"
                "• 📦 Отчёт по товарам – аналитика по товарам (топ, динамика).\n\n"
                "🔹 *Отчёт по продажам*\n"
                "• 📅 Продажи за сегодня – быстрый доступ к сводке.\n"
                "• 📆 Выбрать дату – просмотр за конкретный день.\n"
                "• 📊 Выбрать период – месяц, квартал, год, произвольный.\n"
                "• 📈 Динамика продаж – график по доставленным заказам.\n\n"
                "🔹 *Отчёт по товарам*\n"
                "• 📅 Топ товаров за сегодня – топ‑10 по выручке за сегодня и месяц.\n"
                "• 📆 Выбрать дату – топ‑15 товаров за выбранную дату.\n"
                "• 📊 Выбрать период – топ‑20 товаров за период + сводка.\n"
                "• 📈 Динамика продаж по товару – пока в разработке.\n\n"
                "🔹 *Метрики*\n"
                "• 🛒 Заказано – сумма и количество.\n"
                "• 📦 Доставлено – сумма и количество.\n"
                "• ❌ Отменено – сумма и количество.\n"
                "• 📢 Реклама – расходы, ДРР общий и по доставленным.\n"
                "• 💰 Расходы (финансовые) – комиссии, логистика, эквайринг, кросс-докинг, страхование, упаковка и др.\n\n"
                "🔹 *Сравнение динамики*\n"
                "• Для «Сегодня» – сравнение с аналогичным временем вчера.\n"
                "• Для «Текущий месяц» – сравнение с аналогичным периодом предыдущего месяца (с учётом времени).\n\n"
                "🔹 *Часовой пояс*\n"
                "• Все расчёты ведутся по московскому времени (МСК, UTC+3).\n"
            )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    await update.message.reply_text("Используйте кнопки меню.")

async def handle_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "🔙 Назад":
        if is_admin(chat_id):
            await update.message.reply_text("Главное меню", reply_markup=main_admin_keyboard())
        else:
            await update.message.reply_text("Главное меню", reply_markup=main_user_keyboard())
        return

    if not has_access(chat_id):
        await update.message.reply_text("❌ Нет доступа! Обратитесь к администратору.")
        return

    if text == "📅 Продажи за сегодня":
        report = format_combined_metrics_with_deltas(include_yesterday=False)
        await update.message.reply_text(report, parse_mode="Markdown")
    elif text == "📆 Выбрать дату":
        now = get_moscow_today()
        keyboard = create_calendar(now.year, now.month, "date_")
        await update.message.reply_text("Выберите дату:", reply_markup=keyboard)
        return WAITING_DATE_SINGLE
    elif text == "📊 Выбрать период":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗓️ По месяцам", callback_data="period_month")],
            [InlineKeyboardButton("📅 По кварталам", callback_data="period_quarter")],
            [InlineKeyboardButton("📆 По годам", callback_data="period_year")],
            [InlineKeyboardButton("📊 Произвольный период", callback_data="period_custom")],
            [InlineKeyboardButton("❌ Отмена", callback_data="period_cancel")]
        ])
        await update.message.reply_text("Выберите тип периода:", reply_markup=keyboard)
        return WAITING_PERIOD_TYPE
    elif text == "📈 Динамика продаж":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [
            [InlineKeyboardButton("📅 Текущий год", callback_data="dynamics_current")],
            [InlineKeyboardButton("📆 Выбрать год", callback_data="dynamics_select")],
            [InlineKeyboardButton("📊 Диапазон лет", callback_data="dynamics_range")],
            [InlineKeyboardButton("❌ Отмена", callback_data="dynamics_cancel")]
        ]
        await update.message.reply_text(
            "Выберите вариант для построения графика:\n"
            "• Текущий год – сразу покажет динамику за текущий год.\n"
            "• Выбрать год – покажет список годов (последние 10).\n"
            "• Диапазон лет – введите начальный и конечный год.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return WAITING_DYNAMICS_SELECT
    else:
        await update.message.reply_text("Неизвестная команда.")

# ---------- ОБРАБОТЧИКИ ДЛЯ ТОВАРНЫХ ОТЧЁТОВ ----------
async def handle_product_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "🔙 Назад":
        if is_admin(chat_id):
            await update.message.reply_text("Главное меню", reply_markup=main_admin_keyboard())
        else:
            await update.message.reply_text("Главное меню", reply_markup=main_user_keyboard())
        return

    if not has_access(chat_id):
        await update.message.reply_text("❌ Нет доступа! Обратитесь к администратору.")
        return

    if text == "📅 Топ товаров за сегодня":
        # сегодня и текущий месяц
        today_top = get_product_report_today()
        month_top = get_product_report_month()
        # для месяца также можно добавить сводку по всем товарам
        # получим полные данные для месяца (без ограничения топа)
        now = get_current_time_msk()
        month_start_str = now.date().replace(day=1).isoformat()
        today_str = now.date().isoformat()
        postings_month = fetch_postings(month_start_str, today_str)
        full_month_stats = aggregate_by_products(postings_month, date_from=month_start_str, date_to=today_str, time_limit=now.time(), apply_limit_on_day=today_str)
        msg = "📊 *Топ товаров за сегодня*\n\n"
        msg += format_product_top_block(today_top, "Сегодня") + "\n\n"
        msg += format_product_top_block(month_top, "Текущий месяц", total_stats=full_month_stats)
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    if text == "📆 Выбрать дату":
        now = get_moscow_today()
        keyboard = create_calendar(now.year, now.month, "product_date_")
        await update.message.reply_text("Выберите дату для товарного отчёта:", reply_markup=keyboard)
        return WAITING_PRODUCT_DATE

    if text == "📊 Выбрать период":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗓️ По месяцам", callback_data="product_period_month")],
            [InlineKeyboardButton("📅 По кварталам", callback_data="product_period_quarter")],
            [InlineKeyboardButton("📆 По годам", callback_data="product_period_year")],
            [InlineKeyboardButton("📊 Произвольный период", callback_data="product_period_custom")],
            [InlineKeyboardButton("❌ Отмена", callback_data="product_period_cancel")]
        ])
        await update.message.reply_text("Выберите тип периода для товарного отчёта:", reply_markup=keyboard)
        return WAITING_PRODUCT_PERIOD_TYPE

    if text == "📈 Динамика продаж по товару":
        # пока заглушка
        await update.message.reply_text(
            "Функция «Динамика продаж по товару» в разработке.\n"
            "Для реализации требуется механизм выбора SKU через интерфейс Telegram."
        )
        return

    await update.message.reply_text("Неизвестная команда.")

async def handle_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ Только для администратора.")
        return
    text = update.message.text

    if text == "📋 Список менеджеров":
        managers = load_managers()
        if not managers:
            await update.message.reply_text("Список менеджеров пуст.")
        else:
            lines = ["📋 Список менеджеров:"]
            for m in managers:
                info = f"ID: {m.get('id')}"
                if m.get('username'):
                    info += f", @{m.get('username')}"
                if m.get('first_name'):
                    info += f", {m.get('first_name')}"
                if m.get('phone'):
                    info += f", 📞 {m.get('phone')}"
                lines.append(info)
            await update.message.reply_text("\n".join(lines))
    elif text == "🔙 Назад":
        await update.message.reply_text("Главное меню", reply_markup=main_admin_keyboard())
    else:
        await update.message.reply_text("Неизвестная команда.")

# ---------- ДИАЛОГИ АДМИНИСТРИРОВАНИЯ ----------
async def add_manager_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите ID (число) или username (без @):")
    return WAITING_ADD_MANAGER

async def add_manager_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ Только для администратора.")
        return ConversationHandler.END
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Введите ID или username.")
        return WAITING_ADD_MANAGER
    if text.isdigit():
        user_id = int(text)
        try:
            user = await context.bot.get_chat(user_id)
            username = user.username or ""
            first_name = user.first_name or ""
            last_name = user.last_name or ""
        except Exception:
            await update.message.reply_text(f"❌ Не удалось найти пользователя с ID {user_id}. Убедитесь, что он уже написал боту.")
            return WAITING_ADD_MANAGER
    else:
        username = text.lstrip('@')
        try:
            user = await context.bot.get_chat(username)
            user_id = user.id
            first_name = user.first_name or ""
            last_name = user.last_name or ""
        except Exception:
            await update.message.reply_text(f"❌ Не удалось найти пользователя @{username}. Убедитесь, что он уже написал боту.")
            return WAITING_ADD_MANAGER
    if user_id == ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Администратор уже имеет доступ.")
        return WAITING_ADD_MANAGER
    context.user_data['new_manager'] = {
        'id': user_id,
        'username': username,
        'first_name': first_name,
        'last_name': last_name
    }
    await update.message.reply_text("Введите номер телефона менеджера (или '-' чтобы пропустить):")
    return WAITING_MANAGER_PHONE

async def add_manager_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ Только для администратора.")
        return ConversationHandler.END
    phone = update.message.text.strip()
    if phone == "-":
        phone = ""
    data = context.user_data.get('new_manager')
    if not data:
        await update.message.reply_text("❌ Ошибка: данные менеджера потеряны. Начните заново.")
        return ConversationHandler.END
    user_id = data['id']; username = data['username']; first_name = data['first_name']; last_name = data['last_name']
    if add_manager(user_id, username, first_name, last_name, phone):
        await update.message.reply_text(f"✅ Менеджер с ID {user_id} (username: @{username}) добавлен.")
    else:
        await update.message.reply_text(f"⚠️ Менеджер с ID {user_id} уже существует.")
    context.user_data.pop('new_manager', None)
    await update.message.reply_text("Управление менеджерами:", reply_markup=admin_keyboard())
    return ConversationHandler.END

async def remove_manager_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите ID менеджера (цифры):")
    return WAITING_REMOVE_MANAGER

async def remove_manager_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ Только для администратора.")
        return ConversationHandler.END
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите число.")
        return WAITING_REMOVE_MANAGER
    if user_id == ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Администратора нельзя удалить.")
        return WAITING_REMOVE_MANAGER
    if remove_manager(user_id):
        await update.message.reply_text(f"✅ Менеджер с ID {user_id} удалён.")
    else:
        await update.message.reply_text(f"❌ Менеджер с ID {user_id} не найден.")
    await update.message.reply_text("Управление менеджерами:", reply_markup=admin_keyboard())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
    await update.message.reply_text("Действие отменено.", reply_markup=keyboard)
    return ConversationHandler.END

# ---------- INLINE CALLBACK ----------
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    if not has_access(chat_id):
        await query.edit_message_text("❌ Нет доступа! Обратитесь к администратору.")
        return ConversationHandler.END

    # ---------- Обработка выбора даты (продажи) ----------
    if data.startswith("date_"):
        if data == "date_cancel":
            await query.edit_message_text("Выбор даты отменён.")
            await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
            return ConversationHandler.END
        if "prev_month" in data or "next_month" in data:
            match = re.search(r'prev_month_(\d+)_(\d+)|next_month_(\d+)_(\d+)', data)
            if match:
                if match.group(1) and match.group(2):
                    year = int(match.group(1)); month = int(match.group(2)); action = "prev_month"
                else:
                    year = int(match.group(3)); month = int(match.group(4)); action = "next_month"
            else:
                await query.edit_message_text("❌ Ошибка формата навигации.")
                return WAITING_DATE_SINGLE
            if action == "prev_month":
                month -= 1
                if month == 0: month = 12; year -= 1
            else:
                month += 1
                if month == 13: month = 1; year += 1
            keyboard = create_calendar(year, month, "date_")
            await query.edit_message_reply_markup(reply_markup=keyboard)
            return WAITING_DATE_SINGLE
        date_str = data[5:]
        if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            metrics = get_metrics_for_date(date_str)
            msg = format_single_metrics(metrics, f"Отчёт за {date_str}")
            await query.edit_message_text(msg, parse_mode="Markdown")
            await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
            return ConversationHandler.END
        else:
            await query.edit_message_text("❌ Ошибка формата даты.")
            return WAITING_DATE_SINGLE

    # ---------- Обработка выбора периода (продажи) ----------
    if data == "period_month":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"period_year_month_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="period_cancel")])
        await query.edit_message_text("Выберите год:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PERIOD_YEAR
    if data == "period_quarter":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"period_year_quarter_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="period_cancel")])
        await query.edit_message_text("Выберите год:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PERIOD_YEAR
    if data == "period_year":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"period_year_only_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="period_cancel")])
        await query.edit_message_text("Выберите год:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_YEAR_SELECT
    if data == "period_custom":
        now = get_moscow_today()
        keyboard = create_calendar(now.year, now.month, "start_")
        await query.edit_message_text("Выберите начальную дату:", reply_markup=keyboard)
        return WAITING_PERIOD_START
    if data == "period_cancel":
        await query.edit_message_text("Выбор периода отменён.")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    if data.startswith("period_year_month_"):
        year = int(data.split("_")[-1])
        context.user_data['period_year'] = year
        months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        buttons = [[InlineKeyboardButton(name, callback_data=f"period_month_{i}_{year}")] for i, name in enumerate(months, 1)]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="period_cancel")])
        await query.edit_message_text(f"Выберите месяц {year}:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PERIOD_MONTH
    if data.startswith("period_year_quarter_"):
        year = int(data.split("_")[-1])
        context.user_data['period_year'] = year
        quarters = ["1 квартал (янв-мар)", "2 квартал (апр-июн)", "3 квартал (июл-сен)", "4 квартал (окт-дек)"]
        buttons = [[InlineKeyboardButton(name, callback_data=f"period_quarter_{i}_{year}")] for i, name in enumerate(quarters, 1)]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="period_cancel")])
        await query.edit_message_text(f"Выберите квартал {year}:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PERIOD_QUARTER

    if data.startswith("period_year_only_"):
        year = int(data.split("_")[-1])
        first_day = datetime.date(year, 1, 1)
        last_day = datetime.date(year, 12, 31)
        metrics = get_metrics_for_period(first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d"))
        msg = format_single_metrics(metrics, f"Год {year}")
        await query.edit_message_text(msg, parse_mode="Markdown")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    if data.startswith("period_month_"):
        parts = data.split("_")
        month_num, year = int(parts[2]), int(parts[3])
        first_day = datetime.date(year, month_num, 1)
        if month_num == 12:
            last_day = datetime.date(year, 12, 31)
        else:
            last_day = datetime.date(year, month_num+1, 1) - datetime.timedelta(days=1)
        date_from, date_to = first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")
        metrics = get_metrics_for_period(date_from, date_to)
        msg = format_single_metrics(metrics, f"Месяц {first_day.strftime('%B %Y')}")
        await query.edit_message_text(msg, parse_mode="Markdown")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    if data.startswith("period_quarter_"):
        parts = data.split("_")
        q, year = int(parts[2]), int(parts[3])
        start_month = (q-1)*3 + 1
        end_month = q*3
        first_day = datetime.date(year, start_month, 1)
        if end_month == 12:
            last_day = datetime.date(year, 12, 31)
        else:
            last_day = datetime.date(year, end_month+1, 1) - datetime.timedelta(days=1)
        date_from, date_to = first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")
        metrics = get_metrics_for_period(date_from, date_to)
        msg = format_single_metrics(metrics, f"{q} квартал {year}")
        await query.edit_message_text(msg, parse_mode="Markdown")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    if data.startswith("start_"):
        if data == "start_cancel":
            await query.edit_message_text("Выбор периода отменён.")
            await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
            return ConversationHandler.END
        if "prev_month" in data or "next_month" in data:
            match = re.search(r'prev_month_(\d+)_(\d+)|next_month_(\d+)_(\d+)', data)
            if match:
                if match.group(1) and match.group(2):
                    year = int(match.group(1)); month = int(match.group(2)); action = "prev_month"
                else:
                    year = int(match.group(3)); month = int(match.group(4)); action = "next_month"
            else:
                await query.edit_message_text("❌ Ошибка формата навигации.")
                return WAITING_PERIOD_START
            if action == "prev_month":
                month -= 1
                if month == 0: month = 12; year -= 1
            else:
                month += 1
                if month == 13: month = 1; year += 1
            keyboard = create_calendar(year, month, "start_")
            await query.edit_message_reply_markup(reply_markup=keyboard)
            return WAITING_PERIOD_START
        date_str = data[6:]
        if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            context.user_data['period_start_date'] = date_str
            now = get_moscow_today()
            keyboard = create_calendar(now.year, now.month, "end_")
            await query.edit_message_text(f"Начало: {date_str}\nТеперь выберите конечную дату:", reply_markup=keyboard)
            return WAITING_PERIOD_END
        else:
            await query.edit_message_text("❌ Ошибка формата даты.")
            return WAITING_PERIOD_START

    if data.startswith("end_"):
        if data == "end_cancel":
            await query.edit_message_text("Выбор периода отменён.")
            await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
            return ConversationHandler.END
        if "prev_month" in data or "next_month" in data:
            match = re.search(r'prev_month_(\d+)_(\d+)|next_month_(\d+)_(\d+)', data)
            if match:
                if match.group(1) and match.group(2):
                    year = int(match.group(1)); month = int(match.group(2)); action = "prev_month"
                else:
                    year = int(match.group(3)); month = int(match.group(4)); action = "next_month"
            else:
                await query.edit_message_text("❌ Ошибка формата навигации.")
                return WAITING_PERIOD_END
            if action == "prev_month":
                month -= 1
                if month == 0: month = 12; year -= 1
            else:
                month += 1
                if month == 13: month = 1; year += 1
            keyboard = create_calendar(year, month, "end_")
            await query.edit_message_reply_markup(reply_markup=keyboard)
            return WAITING_PERIOD_END
        end_date_str = data[4:]
        if re.match(r"\d{4}-\d{2}-\d{2}", end_date_str):
            start_date = context.user_data.get('period_start_date')
            if not start_date:
                await query.edit_message_text("❌ Ошибка: начальная дата не найдена. Попробуйте снова.")
                return ConversationHandler.END
            if start_date > end_date_str:
                await query.edit_message_text("❌ Начальная дата позже конечной. Попробуйте сначала.")
                now = get_moscow_today()
                keyboard = create_calendar(now.year, now.month, "start_")
                await query.message.reply_text("Выберите начальную дату заново:", reply_markup=keyboard)
                return WAITING_PERIOD_START
            metrics = get_metrics_for_period(start_date, end_date_str)
            msg = format_single_metrics(metrics, f"Период {start_date} – {end_date_str}")
            await query.edit_message_text(msg, parse_mode="Markdown")
            await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
            context.user_data.pop('period_start_date', None)
            return ConversationHandler.END
        else:
            await query.edit_message_text("❌ Ошибка формата даты.")
            return WAITING_PERIOD_END

    # ---------- Обработка динамики продаж (график) ----------
    if data == "dynamics_current":
        await query.edit_message_text("⏳ Загружаю данные для текущего года...")
        current_year = get_moscow_today().year
        chart_buf = generate_sales_chart([current_year])
        if chart_buf:
            await query.message.reply_photo(photo=chart_buf, caption=f"Динамика доставленных заказов за {current_year} год")
        else:
            await query.message.reply_text("❌ Не удалось построить график.")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    if data == "dynamics_select":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"dynamics_year_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="dynamics_cancel")])
        await query.edit_message_text("Выберите год для отображения графика:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_DYNAMICS_SELECT

    if data == "dynamics_range":
        await query.edit_message_text("Введите начальный год (например, 2020):")
        return WAITING_DYNAMICS_RANGE_START

    if data == "dynamics_cancel":
        await query.edit_message_text("Построение графика отменено.")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    if data.startswith("dynamics_year_"):
        year = int(data.split("_")[-1])
        await query.edit_message_text(f"⏳ Загружаю данные за {year} год...")
        chart_buf = generate_sales_chart([year])
        if chart_buf:
            await query.message.reply_photo(photo=chart_buf, caption=f"Динамика доставленных заказов за {year} год")
        else:
            await query.message.reply_text("❌ Не удалось построить график.")
        await query.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
        return ConversationHandler.END

    # ---------- ТОВАРНЫЕ ОТЧЁТЫ (дата) ----------
    if data.startswith("product_date_"):
        if data == "product_date_cancel":
            await query.edit_message_text("Выбор даты отменён.")
            await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
            return ConversationHandler.END
        if "prev_month" in data or "next_month" in data:
            match = re.search(r'prev_month_(\d+)_(\d+)|next_month_(\d+)_(\d+)', data)
            if match:
                if match.group(1) and match.group(2):
                    year = int(match.group(1)); month = int(match.group(2)); action = "prev_month"
                else:
                    year = int(match.group(3)); month = int(match.group(4)); action = "next_month"
            else:
                await query.edit_message_text("❌ Ошибка формата навигации.")
                return WAITING_PRODUCT_DATE
            if action == "prev_month":
                month -= 1
                if month == 0: month = 12; year -= 1
            else:
                month += 1
                if month == 13: month = 1; year += 1
            keyboard = create_calendar(year, month, "product_date_")
            await query.edit_message_reply_markup(reply_markup=keyboard)
            return WAITING_PRODUCT_DATE
        date_str = data[13:]  # "product_date_" length = 13
        if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            prod_stats = get_product_stats_for_date(date_str)
            sorted_items = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
            top = sorted_items[:15]
            msg = format_product_top_block(top, f"Товары за {date_str} (топ-15)")
            if len(prod_stats) > 15:
                msg += f"\n\n*Всего товаров: {len(prod_stats)}*"
            await query.edit_message_text(msg, parse_mode="Markdown")
            await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
            return ConversationHandler.END
        else:
            await query.edit_message_text("❌ Ошибка формата даты.")
            return WAITING_PRODUCT_DATE

    # ---------- ТОВАРНЫЕ ОТЧЁТЫ (период) ----------
    if data == "product_period_month":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"product_period_year_month_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="product_period_cancel")])
        await query.edit_message_text("Выберите год для товарного отчёта по месяцам:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PRODUCT_PERIOD_YEAR
    if data == "product_period_quarter":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"product_period_year_quarter_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="product_period_cancel")])
        await query.edit_message_text("Выберите год для товарного отчёта по кварталам:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PRODUCT_PERIOD_YEAR
    if data == "product_period_year":
        current_year = get_moscow_today().year
        years = list(range(current_year - 9, current_year + 1))
        buttons = [[InlineKeyboardButton(str(y), callback_data=f"product_period_year_only_{y}")] for y in years]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="product_period_cancel")])
        await query.edit_message_text("Выберите год для товарного отчёта:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PRODUCT_YEAR_SELECT
    if data == "product_period_custom":
        now = get_moscow_today()
        keyboard = create_calendar(now.year, now.month, "product_start_")
        await query.edit_message_text("Выберите начальную дату для товарного отчёта:", reply_markup=keyboard)
        return WAITING_PRODUCT_PERIOD_START
    if data == "product_period_cancel":
        await query.edit_message_text("Выбор периода отменён.")
        await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
        return ConversationHandler.END

    if data.startswith("product_period_year_month_"):
        year = int(data.split("_")[-1])
        context.user_data['product_period_year'] = year
        months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        buttons = [[InlineKeyboardButton(name, callback_data=f"product_period_month_{i}_{year}")] for i, name in enumerate(months, 1)]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="product_period_cancel")])
        await query.edit_message_text(f"Выберите месяц {year}:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PRODUCT_PERIOD_MONTH
    if data.startswith("product_period_year_quarter_"):
        year = int(data.split("_")[-1])
        context.user_data['product_period_year'] = year
        quarters = ["1 квартал (янв-мар)", "2 квартал (апр-июн)", "3 квартал (июл-сен)", "4 квартал (окт-дек)"]
        buttons = [[InlineKeyboardButton(name, callback_data=f"product_period_quarter_{i}_{year}")] for i, name in enumerate(quarters, 1)]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="product_period_cancel")])
        await query.edit_message_text(f"Выберите квартал {year}:", reply_markup=InlineKeyboardMarkup(buttons))
        return WAITING_PRODUCT_PERIOD_QUARTER

    if data.startswith("product_period_year_only_"):
        year = int(data.split("_")[-1])
        first_day = datetime.date(year, 1, 1)
        last_day = datetime.date(year, 12, 31)
        prod_stats = get_product_stats_for_period(first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d"))
        sorted_items = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
        top = sorted_items[:20]
        msg = format_product_top_block(top, f"Год {year} (топ-20)")
        msg += "\n\n" + format_product_period_summary(prod_stats, f"Год {year} (сводка)")
        await query.edit_message_text(msg, parse_mode="Markdown")
        await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
        return ConversationHandler.END

    if data.startswith("product_period_month_"):
        parts = data.split("_")
        month_num, year = int(parts[3]), int(parts[4])
        first_day = datetime.date(year, month_num, 1)
        if month_num == 12:
            last_day = datetime.date(year, 12, 31)
        else:
            last_day = datetime.date(year, month_num+1, 1) - datetime.timedelta(days=1)
        date_from, date_to = first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")
        prod_stats = get_product_stats_for_period(date_from, date_to)
        sorted_items = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
        top = sorted_items[:20]
        msg = format_product_top_block(top, f"Месяц {first_day.strftime('%B %Y')} (топ-20)")
        msg += "\n\n" + format_product_period_summary(prod_stats, f"Месяц {first_day.strftime('%B %Y')} (сводка)")
        await query.edit_message_text(msg, parse_mode="Markdown")
        await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
        return ConversationHandler.END

    if data.startswith("product_period_quarter_"):
        parts = data.split("_")
        q, year = int(parts[3]), int(parts[4])
        start_month = (q-1)*3 + 1
        end_month = q*3
        first_day = datetime.date(year, start_month, 1)
        if end_month == 12:
            last_day = datetime.date(year, 12, 31)
        else:
            last_day = datetime.date(year, end_month+1, 1) - datetime.timedelta(days=1)
        date_from, date_to = first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")
        prod_stats = get_product_stats_for_period(date_from, date_to)
        sorted_items = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
        top = sorted_items[:20]
        msg = format_product_top_block(top, f"{q} квартал {year} (топ-20)")
        msg += "\n\n" + format_product_period_summary(prod_stats, f"{q} квартал {year} (сводка)")
        await query.edit_message_text(msg, parse_mode="Markdown")
        await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
        return ConversationHandler.END

    if data.startswith("product_start_"):
        if data == "product_start_cancel":
            await query.edit_message_text("Выбор периода отменён.")
            await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
            return ConversationHandler.END
        if "prev_month" in data or "next_month" in data:
            match = re.search(r'prev_month_(\d+)_(\d+)|next_month_(\d+)_(\d+)', data)
            if match:
                if match.group(1) and match.group(2):
                    year = int(match.group(1)); month = int(match.group(2)); action = "prev_month"
                else:
                    year = int(match.group(3)); month = int(match.group(4)); action = "next_month"
            else:
                await query.edit_message_text("❌ Ошибка формата навигации.")
                return WAITING_PRODUCT_PERIOD_START
            if action == "prev_month":
                month -= 1
                if month == 0: month = 12; year -= 1
            else:
                month += 1
                if month == 13: month = 1; year += 1
            keyboard = create_calendar(year, month, "product_start_")
            await query.edit_message_reply_markup(reply_markup=keyboard)
            return WAITING_PRODUCT_PERIOD_START
        date_str = data[13:]  # "product_start_" length 13
        if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            context.user_data['product_period_start_date'] = date_str
            now = get_moscow_today()
            keyboard = create_calendar(now.year, now.month, "product_end_")
            await query.edit_message_text(f"Начало: {date_str}\nТеперь выберите конечную дату:", reply_markup=keyboard)
            return WAITING_PRODUCT_PERIOD_END
        else:
            await query.edit_message_text("❌ Ошибка формата даты.")
            return WAITING_PRODUCT_PERIOD_START

    if data.startswith("product_end_"):
        if data == "product_end_cancel":
            await query.edit_message_text("Выбор периода отменён.")
            await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
            return ConversationHandler.END
        if "prev_month" in data or "next_month" in data:
            match = re.search(r'prev_month_(\d+)_(\d+)|next_month_(\d+)_(\d+)', data)
            if match:
                if match.group(1) and match.group(2):
                    year = int(match.group(1)); month = int(match.group(2)); action = "prev_month"
                else:
                    year = int(match.group(3)); month = int(match.group(4)); action = "next_month"
            else:
                await query.edit_message_text("❌ Ошибка формата навигации.")
                return WAITING_PRODUCT_PERIOD_END
            if action == "prev_month":
                month -= 1
                if month == 0: month = 12; year -= 1
            else:
                month += 1
                if month == 13: month = 1; year += 1
            keyboard = create_calendar(year, month, "product_end_")
            await query.edit_message_reply_markup(reply_markup=keyboard)
            return WAITING_PRODUCT_PERIOD_END
        end_date_str = data[11:]  # "product_end_" length 11
        if re.match(r"\d{4}-\d{2}-\d{2}", end_date_str):
            start_date = context.user_data.get('product_period_start_date')
            if not start_date:
                await query.edit_message_text("❌ Ошибка: начальная дата не найдена. Попробуйте снова.")
                return ConversationHandler.END
            if start_date > end_date_str:
                await query.edit_message_text("❌ Начальная дата позже конечной. Попробуйте сначала.")
                now = get_moscow_today()
                keyboard = create_calendar(now.year, now.month, "product_start_")
                await query.message.reply_text("Выберите начальную дату заново:", reply_markup=keyboard)
                return WAITING_PRODUCT_PERIOD_START
            prod_stats = get_product_stats_for_period(start_date, end_date_str)
            sorted_items = sorted(prod_stats.items(), key=lambda x: x[1]["ordered_sum"], reverse=True)
            top = sorted_items[:20]
            msg = format_product_top_block(top, f"Период {start_date} – {end_date_str} (топ-20)")
            msg += "\n\n" + format_product_period_summary(prod_stats, f"Период {start_date} – {end_date_str} (сводка)")
            await query.edit_message_text(msg, parse_mode="Markdown")
            await query.message.reply_text("Выберите действие:", reply_markup=product_reports_keyboard())
            context.user_data.pop('product_period_start_date', None)
            return ConversationHandler.END
        else:
            await query.edit_message_text("❌ Ошибка формата даты.")
            return WAITING_PRODUCT_PERIOD_END

    await query.edit_message_text("❌ Неизвестная команда.")
    return ConversationHandler.END

# ---------- ДИАЛОГИ ДЛЯ ДИНАМИКИ (диапазон) ----------
async def dynamics_range_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Пожалуйста, введите число (год).")
        return WAITING_DYNAMICS_RANGE_START
    year = int(text)
    if year < 2000 or year > get_moscow_today().year + 1:
        await update.message.reply_text("❌ Некорректный год. Введите год от 2000 до текущего.")
        return WAITING_DYNAMICS_RANGE_START
    context.user_data['dynamics_range_start'] = year
    await update.message.reply_text("Введите конечный год (включительно):")
    return WAITING_DYNAMICS_RANGE_END

async def dynamics_range_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Пожалуйста, введите число (год).")
        return WAITING_DYNAMICS_RANGE_END
    year_end = int(text)
    year_start = context.user_data.get('dynamics_range_start')
    if year_start is None:
        await update.message.reply_text("❌ Ошибка: начальный год не найден. Начните заново.")
        return ConversationHandler.END
    if year_end < year_start:
        await update.message.reply_text("❌ Конечный год должен быть не меньше начального.")
        return WAITING_DYNAMICS_RANGE_END
    years = list(range(year_start, year_end + 1))
    if len(years) > 10:
        await update.message.reply_text("⚠️ Слишком много лет (максимум 10). Пожалуйста, выберите меньший диапазон.")
        return ConversationHandler.END
    await update.message.reply_text(f"⏳ Загружаю данные за годы {year_start}-{year_end}...")
    chart_buf = generate_sales_chart(years)
    if chart_buf:
        caption = f"Динамика доставленных заказов за {year_start}-{year_end} гг."
        await update.message.reply_photo(photo=chart_buf, caption=caption)
    else:
        await update.message.reply_text("❌ Не удалось построить график.")
    await update.message.reply_text("Выберите действие:", reply_markup=reports_keyboard())
    context.user_data.pop('dynamics_range_start', None)
    return ConversationHandler.END

# ---------- ЗАПУСК ----------
def main():
    if not all([OZON_CLIENT_ID, OZON_API_KEY, TELEGRAM_BOT_TOKEN]):
        write_log("❌ ОШИБКА: Не все переменные окружения установлены!")
        return
    if not OZON_PERFORMANCE_CLIENT_ID or not OZON_PERFORMANCE_CLIENT_SECRET:
        write_log("⚠️ ВНИМАНИЕ: OZON_PERFORMANCE_CLIENT_ID или CLIENT_SECRET не заданы. Рекламные расходы не будут отображаться.")
    write_log("🚀 Запуск бота...")
    application = (Application.builder()
                   .token(TELEGRAM_BOT_TOKEN)
                   .connect_timeout(30.0)
                   .read_timeout(30.0)
                   .write_timeout(30.0)
                   .build())

    application.add_handler(CommandHandler("start", start))
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if is_admin(chat_id):
            help_text = (
                "📖 *Справка для администратора*\n\n"
                "🔹 *Основные функции*\n"
                "• 📊 Отчёт по продажам – сводка по продажам за сегодня и текущий месяц.\n"
                "• 📦 Отчёт по товарам – аналитика по товарам (топ, динамика).\n"
                "• ⚙️ Администрирование – управление доступом менеджеров.\n\n"
                "🔹 *Отчёт по продажам*\n"
                "• 📅 Продажи за сегодня – быстрый доступ к сводке.\n"
                "• 📆 Выбрать дату – просмотр за конкретный день.\n"
                "• 📊 Выбрать период – месяц, квартал, год, произвольный.\n"
                "• 📈 Динамика продаж – график по доставленным заказам.\n\n"
                "🔹 *Отчёт по товарам*\n"
                "• 📅 Топ товаров за сегодня – топ‑10 по выручке за сегодня и месяц.\n"
                "• 📆 Выбрать дату – топ‑15 товаров за выбранную дату.\n"
                "• 📊 Выбрать период – топ‑20 товаров за период + сводка.\n"
                "• 📈 Динамика продаж по товару – пока в разработке.\n\n"
                "🔹 *Метрики*\n"
                "• 🛒 Заказано – сумма и количество.\n"
                "• 📦 Доставлено – сумма и количество.\n"
                "• ❌ Отменено – сумма и количество.\n"
                "• 📢 Реклама – расходы, ДРР общий и по доставленным.\n"
                "• 💰 Расходы (финансовые) – комиссии, логистика, эквайринг, кросс-докинг, страхование, упаковка и др.\n\n"
                "🔹 *Сравнение динамики*\n"
                "• Для «Сегодня» – сравнение с аналогичным временем вчера.\n"
                "• Для «Текущий месяц» – сравнение с аналогичным периодом предыдущего месяца (с учётом времени).\n\n"
                "🔹 *Часовой пояс*\n"
                "• Все расчёты ведутся по московскому времени (МСК, UTC+3).\n"
            )
        else:
            help_text = (
                "📖 *Справка для менеджера*\n\n"
                "🔹 *Основные функции*\n"
                "• 📊 Отчёт по продажам – сводка по продажам за сегодня и текущий месяц.\n"
                "• 📦 Отчёт по товарам – аналитика по товарам (топ, динамика).\n\n"
                "🔹 *Отчёт по продажам*\n"
                "• 📅 Продажи за сегодня – быстрый доступ к сводке.\n"
                "• 📆 Выбрать дату – просмотр за конкретный день.\n"
                "• 📊 Выбрать период – месяц, квартал, год, произвольный.\n"
                "• 📈 Динамика продаж – график по доставленным заказам.\n\n"
                "🔹 *Отчёт по товарам*\n"
                "• 📅 Топ товаров за сегодня – топ‑10 по выручке за сегодня и месяц.\n"
                "• 📆 Выбрать дату – топ‑15 товаров за выбранную дату.\n"
                "• 📊 Выбрать период – топ‑20 товаров за период + сводка.\n"
                "• 📈 Динамика продаж по товару – пока в разработке.\n\n"
                "🔹 *Метрики*\n"
                "• 🛒 Заказано – сумма и количество.\n"
                "• 📦 Доставлено – сумма и количество.\n"
                "• ❌ Отменено – сумма и количество.\n"
                "• 📢 Реклама – расходы, ДРР общий и по доставленным.\n"
                "• 💰 Расходы (финансовые) – комиссии, логистика, эквайринг, кросс-докинг, страхование, упаковка и др.\n\n"
                "🔹 *Сравнение динамики*\n"
                "• Для «Сегодня» – сравнение с аналогичным временем вчера.\n"
                "• Для «Текущий месяц» – сравнение с аналогичным периодом предыдущего месяца (с учётом времени).\n\n"
                "🔹 *Часовой пояс*\n"
                "• Все расчёты ведутся по московскому времени (МСК, UTC+3).\n"
            )
        await update.message.reply_text(help_text, parse_mode="Markdown")
    application.add_handler(CommandHandler("help", help_command))

    # основные обработчики меню
    application.add_handler(MessageHandler(filters.Text(["📊 Отчёт по продажам", "📦 Отчёт по товарам", "⚙️ Администрирование", "📖 Справка"]), handle_main_menu))
    application.add_handler(MessageHandler(filters.Text(["📅 Продажи за сегодня", "📆 Выбрать дату", "📊 Выбрать период", "📈 Динамика продаж", "🔙 Назад"]), handle_reports_menu))
    application.add_handler(MessageHandler(filters.Text(["📅 Топ товаров за сегодня", "📆 Выбрать дату", "📊 Выбрать период", "📈 Динамика продаж по товару", "🔙 Назад"]), handle_product_reports_menu))
    application.add_handler(MessageHandler(filters.Text(["📋 Список менеджеров", "🔙 Назад"]), handle_admin_menu))

    conv_date = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📆 Выбрать дату"), handle_reports_menu)],
        states={WAITING_DATE_SINGLE: [CallbackQueryHandler(handle_callback_query)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_period = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📊 Выбрать период"), handle_reports_menu)],
        states={
            WAITING_PERIOD_TYPE: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PERIOD_START: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PERIOD_END: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PERIOD_YEAR: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PERIOD_MONTH: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PERIOD_QUARTER: [CallbackQueryHandler(handle_callback_query)],
            WAITING_YEAR_SELECT: [CallbackQueryHandler(handle_callback_query)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_dynamics = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📈 Динамика продаж"), handle_reports_menu)],
        states={
            WAITING_DYNAMICS_SELECT: [CallbackQueryHandler(handle_callback_query)],
            WAITING_DYNAMICS_RANGE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, dynamics_range_start)],
            WAITING_DYNAMICS_RANGE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, dynamics_range_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_product_date = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📆 Выбрать дату"), handle_product_reports_menu)],
        states={WAITING_PRODUCT_DATE: [CallbackQueryHandler(handle_callback_query)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_product_period = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📊 Выбрать период"), handle_product_reports_menu)],
        states={
            WAITING_PRODUCT_PERIOD_TYPE: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PRODUCT_PERIOD_START: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PRODUCT_PERIOD_END: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PRODUCT_PERIOD_YEAR: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PRODUCT_PERIOD_MONTH: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PRODUCT_PERIOD_QUARTER: [CallbackQueryHandler(handle_callback_query)],
            WAITING_PRODUCT_YEAR_SELECT: [CallbackQueryHandler(handle_callback_query)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_add = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("➕ Добавить менеджера"), add_manager_start)],
        states={
            WAITING_ADD_MANAGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manager_input)],
            WAITING_MANAGER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manager_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_remove = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("➖ Удалить менеджера"), remove_manager_start)],
        states={WAITING_REMOVE_MANAGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_manager_input)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_date)
    application.add_handler(conv_period)
    application.add_handler(conv_dynamics)
    application.add_handler(conv_product_date)
    application.add_handler(conv_product_period)
    application.add_handler(conv_add)
    application.add_handler(conv_remove)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(scheduled_report, interval=3600, first=0)
        write_log("✅ Планировщик запущен (отправка в 10:00 и 22:00 МСК).")
    else:
        write_log("⚠️ JobQueue недоступен.")

    write_log("🚀 Бот готов.")
    application.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

async def scheduled_report(context):
    moscow_tz = MOSCOW_TZ
    now = datetime.datetime.now(moscow_tz)
    hour = now.hour
    if hour not in (10, 22):
        return
    include_yesterday = (hour == 10)
    report = format_combined_metrics_with_deltas(include_yesterday=include_yesterday)
    managers = load_managers()
    if not managers:
        return
    for m in managers:
        try:
            await context.bot.send_message(chat_id=m['id'], text=report, parse_mode="Markdown")
        except Exception as e:
            write_log(f"Ошибка отправки {m['id']}: {e}")

if __name__ == "__main__":
    main()
