"""
Обработчики команд для системы FIFO + Себестоимость + ROI
Добавляются к основному боту (bot_optimized.py)
"""

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters
import datetime
from fifo_system import (
    add_purchase, log_sale, get_inventory, get_product_profitability,
    get_period_profitability, load_purchases, load_sales_log,
    format_inventory_message, format_profitability_message,
    format_product_analysis_message
)

# ===================== СОСТОЯНИЯ ДЛЯ ДИАЛОГОВ =====================

# Добавление поставки
WAITING_PURCHASE_OFFER_ID = 50
WAITING_PURCHASE_QUANTITY = 51
WAITING_PURCHASE_PRICE = 52
WAITING_PURCHASE_DATE = 53

# Регистрация продажи (если добавляется из бота)
WAITING_SALE_OFFER_ID = 60
WAITING_SALE_QUANTITY = 61
WAITING_SALE_PRICE = 62

# Анализ товара
WAITING_PRODUCT_OFFER_ID = 70

# ===================== КОМАНДА: ДОБАВИТЬ ПОСТАВКУ =====================

async def add_purchase_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления поставки"""
    chat_id = update.effective_chat.id
    
    # Проверяем доступ
    from bot_optimized import has_access
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
    context.user_data['purchase_step'] = 'name'
    return WAITING_PURCHASE_OFFER_ID

async def purchase_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    # Валидация даты
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except:
        await update.message.reply_text(
            "❌ Неверный формат даты\n"
            "Используйте ГГГГ-ММ-ДД (например: 2024-01-15)"
        )
        return WAITING_PURCHASE_DATE
    
    # Добавляем поставку
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
    
    from bot_optimized import is_admin, main_admin_keyboard, main_user_keyboard
    chat_id = update.effective_chat.id
    keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
    await update.message.reply_text("Готово!", reply_markup=keyboard)
    
    return ConversationHandler.END

# ===================== КОМАНДА: ОСТАТКИ =====================

async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие остатки"""
    chat_id = update.effective_chat.id
    
    from bot_optimized import has_access
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
        
        from bot_optimized import is_admin, main_admin_keyboard, main_user_keyboard
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("✅ Готово!", reply_markup=keyboard)
    except Exception as e:
        from bot_optimized import write_log
        write_log(f"❌ Ошибка в inventory_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

# ===================== КОМАНДА: РЕНТАБЕЛЬНОСТЬ =====================

async def profitability_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога анализа рентабельности"""
    chat_id = update.effective_chat.id
    
    from bot_optimized import has_access
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
    
    return WAITING_PURCHASE_DATE  # переиспользуем состояние

async def profitability_period_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора периода"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    today = datetime.datetime.now().date()
    
    if text == "❌ Отмена":
        from bot_optimized import is_admin, main_admin_keyboard, main_user_keyboard
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено", reply_markup=keyboard)
        return ConversationHandler.END
    
    if text == "📅 Месяц":
        # Текущий месяц
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
    elif text == "📈 Произвольный период":
        await update.message.reply_text(
            "Введите начальную дату (ГГГГ-ММ-ДД)\n"
            "Пример: 2024-01-01"
        )
        context.user_data['prof_custom'] = True
        return WAITING_PURCHASE_QUANTITY  # Переиспользуем для начальной даты
    else:
        await update.message.reply_text("❌ Неверный выбор")
        return WAITING_PURCHASE_DATE
    
    # Показываем рентабельность
    await show_profitability(update, context, date_from, date_to, period_name)
    
    return ConversationHandler.END

async def show_profitability(update: Update, context: ContextTypes.DEFAULT_TYPE, date_from: str, date_to: str, period_name: str):
    """Показать анализ рентабельности"""
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
        
        from bot_optimized import is_admin, main_admin_keyboard, main_user_keyboard
        chat_id = update.effective_chat.id
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("✅ Готово!", reply_markup=keyboard)
    except Exception as e:
        from bot_optimized import write_log
        write_log(f"❌ Ошибка в show_profitability: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ===================== КОМАНДА: АНАЛИЗ ТОВАРА =====================

async def product_analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало анализа товара"""
    chat_id = update.effective_chat.id
    
    from bot_optimized import has_access
    if not has_access(chat_id):
        await update.message.reply_text("❌ У вас нет доступа")
        return ConversationHandler.END
    
    # Получаем список товаров
    purchases = load_purchases()
    offer_ids = sorted(set(p.offer_id for p in purchases))
    
    if not offer_ids:
        await update.message.reply_text("❌ В системе нет товаров")
        return ConversationHandler.END
    
    # Создаем клавиатуру с товарами
    keyboard = [[KeyboardButton(offer_id)] for offer_id in offer_ids]
    keyboard.append([KeyboardButton("❌ Отмена")])
    
    await update.message.reply_text(
        "📈 <b>АНАЛИЗ ТОВАРА</b>\n\n"
        "Выберите товар:",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    
    return WAITING_PRODUCT_OFFER_ID

async def product_analysis_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора товара"""
    offer_id = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if offer_id == "❌ Отмена":
        from bot_optimized import is_admin, main_admin_keyboard, main_user_keyboard
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("Отменено", reply_markup=keyboard)
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
        
        from bot_optimized import is_admin, main_admin_keyboard, main_user_keyboard
        keyboard = main_admin_keyboard() if is_admin(chat_id) else main_user_keyboard()
        await update.message.reply_text("✅ Готово!", reply_markup=keyboard)
    except Exception as e:
        from bot_optimized import write_log
        write_log(f"❌ Ошибка в product_analysis_select: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

# ===================== КОНВЕРТЕРЫ ДИАЛОГОВ =====================

def get_add_purchase_handler():
    """Получить ConversationHandler для добавления поставки"""
    return ConversationHandler(
        entry_points=[CommandHandler("add_purchase", add_purchase_command)],
        states={
            WAITING_PURCHASE_OFFER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_offer_id)],
            WAITING_PURCHASE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_quantity)],
            WAITING_PURCHASE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_price)],
            WAITING_PURCHASE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, purchase_date)],
        },
        fallbacks=[CommandHandler("cancel", add_purchase_command)],
        name="add_purchase_conversation",
        persistent=False
    )

def get_inventory_handler():
    """Получить handler для просмотра остатков"""
    async def inventory_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await inventory_command(update, context)
    
    return MessageHandler(filters.Regex("^📦 Остатки$"), inventory_wrapper)

def get_profitability_handler():
    """Получить ConversationHandler для анализа рентабельности"""
    return ConversationHandler(
        entry_points=[
            CommandHandler("profitability", profitability_command),
            MessageHandler(filters.Regex("^💰 Рентабельность$"), profitability_command)
        ],
        states={
            WAITING_PURCHASE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, profitability_period_select)],
        },
        fallbacks=[CommandHandler("cancel", profitability_command)],
        name="profitability_conversation",
        persistent=False
    )

def get_product_analysis_handler():
    """Получить ConversationHandler для анализа товара"""
    return ConversationHandler(
        entry_points=[
            CommandHandler("analyze_product", product_analysis_command),
            MessageHandler(filters.Regex("^📈 Анализ товара$"), product_analysis_command)
        ],
        states={
            WAITING_PRODUCT_OFFER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_analysis_select)],
        },
        fallbacks=[CommandHandler("cancel", product_analysis_command)],
        name="product_analysis_conversation",
        persistent=False
    )
