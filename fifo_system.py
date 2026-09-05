"""
Система управления товарами с методом FIFO, расчетом себестоимости и ROI
для Telegram бота Ozon.

Структура:
- purchases.json - история закупок
- sales_log.json - история продаж с FIFO
"""

import json
import os
import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict

# ===================== ФАЙЛЫ ДАННЫХ =====================
PURCHASES_FILE = "purchases.json"
SALES_LOG_FILE = "sales_log.json"
PRODUCT_NAMES_FILE = "product_names.json"

# ===================== МОДЕЛИ ДАННЫХ =====================

@dataclass
class Purchase:
    """Модель закупки товара"""
    id: str  # PURCHASE_20240115_001
    date: str  # 2024-01-15
    offer_id: str  # ТОВАР-001
    product_name: str  # Кружка красная
    quantity: int  # 100
    purchase_price: float  # 500.00
    total_cost: float  # 50000.00
    remaining: int  # 45 (осталось на складе)

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
    date: str  # 2024-03-01
    offer_id: str
    product_name: str
    quantity_sold: int
    sale_price: float  # цена продажи за единицу
    total_revenue: float  # выручка
    fifo_breakdown: List[FIFOBreakdown]  # FIFO разбор
    total_cost_of_goods_sold: float  # себестоимость по FIFO
    gross_profit: float  # валовая прибыль
    gross_margin_percent: float  # валовая маржа %

# ===================== РАБОТА С ФАЙЛАМИ =====================

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
    """
    Расчет себестоимости по методу FIFO
    
    Возвращает:
    - total_cost: общая себестоимость
    - breakdown: детализация по поставкам
    - updated_purchases: обновленный список поставок с новыми остатками
    """
    purchases = load_purchases()
    
    # Фильтруем поставки по товару
    relevant_purchases = [p for p in purchases if p.offer_id == offer_id]
    
    # Сортируем по дате (старые первыми) - это FIFO!
    relevant_purchases.sort(key=lambda x: x.date)
    
    total_cost = 0.0
    breakdown = []
    remaining = quantity_sold
    
    # Обходим поставки по очереди
    for purchase in relevant_purchases:
        if remaining == 0:
            break
        
        # Сколько можем взять из этой поставки
        available = purchase.remaining
        take = min(remaining, available)
        
        if take == 0:
            continue
        
        # Рассчитываем стоимость
        cost = take * purchase.purchase_price
        total_cost += cost
        
        # Добавляем в детализацию
        breakdown.append(FIFOBreakdown(
            purchase_id=purchase.id,
            quantity=take,
            unit_cost=purchase.purchase_price,
            total_cost=cost
        ))
        
        # Обновляем остаток в поставке
        purchase.remaining -= take
        remaining -= take
    
    # Сохраняем обновленные остатки
    save_purchases(purchases)
    
    return total_cost, breakdown, purchases

def add_purchase(offer_id: str, product_name: str, quantity: int, purchase_price: float, date: Optional[str] = None) -> Purchase:
    """Добавить новую закупку"""
    if date is None:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    purchases = load_purchases()
    
    # Генерируем ID
    purchase_id = f"PURCHASE_{date.replace('-', '')}_{len(purchases) + 1:03d}"
    
    # Создаем новую закупку
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
    
    # Сохраняем название товара
    names = load_product_names()
    names[offer_id] = product_name
    save_product_names(names)
    
    return new_purchase

def log_sale(offer_id: str, quantity_sold: int, sale_price: float, date: Optional[str] = None) -> Sale:
    """Зафиксировать продажу товара"""
    if date is None:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Рассчитываем себестоимость по FIFO
    total_cost_of_goods_sold, fifo_breakdown, _ = calculate_fifo_cost(offer_id, quantity_sold)
    
    # Рассчитываем прибыль
    total_revenue = quantity_sold * sale_price
    gross_profit = total_revenue - total_cost_of_goods_sold
    gross_margin_percent = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    # Получаем название товара
    names = load_product_names()
    product_name = names.get(offer_id, offer_id)
    
    # Создаем запись продажи
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
    
    # Сохраняем в логи продаж
    sales = load_sales_log()
    sales.append(sale)
    save_sales_log(sales)
    
    return sale

# ===================== АНАЛИТИКА =====================

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
    
    # Фильтруем по датам
    period_sales = [
        s for s in sales
        if date_from <= s.date <= date_to
    ]
    
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

# ===================== ФОРМАТИРОВАНИЕ =====================

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
