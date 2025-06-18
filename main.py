
import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiosqlite
from datetime import datetime, timedelta
from aiogram.client.default import DefaultBotProperties
import matplotlib.pyplot as plt
import io
from collections import defaultdict
from aiogram.types import InputFile
import os
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

async def init_db():
    async with aiosqlite.connect("expenses.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                category TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        await db.commit()

# ---------------- Состояния FSM ----------------
class ExpenseForm(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()

# ---------------- Клавиатура ----------------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить расход")],
        [KeyboardButton(text="📊 Показать статистику")],
        [KeyboardButton(text="📅 Все расходы")],
        [KeyboardButton(text="📈 Отчет")],
        [KeyboardButton(text="🗑️ Очистить все расходы")],
    ],
    resize_keyboard=True,
)

category_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍔 Еда"), KeyboardButton(text="🚕 Такси")],
        [KeyboardButton(text="🛍️ Покупки"), KeyboardButton(text="🎮 Развлечения")],
        [KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True
)

report_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📆 За день"), KeyboardButton(text="📅 За неделю")],
        [KeyboardButton(text="🗓️ За месяц"), KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True
)

# ---------------- Команды ----------------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для учёта твоих расходов.\n\nВыбери действие ниже:",
        reply_markup=main_kb
    )

@dp.message(F.text == "➕ Добавить расход")
async def add_expense_start(message: Message, state: FSMContext):
    await message.answer("💰 Введи сумму расхода:")
    await state.set_state(ExpenseForm.waiting_for_amount)

@dp.message(StateFilter(ExpenseForm.waiting_for_amount))
async def get_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        await state.update_data(amount=amount)
        await message.answer("🏷️ Выбери категорию:", reply_markup=category_kb)
        await state.set_state(ExpenseForm.waiting_for_category)
    except ValueError:
        await message.answer("⚠️ Введи сумму числом, например: 250.50")

@dp.message(StateFilter(ExpenseForm.waiting_for_category))
async def get_category(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("🚫 Добавление отменено.", reply_markup=main_kb)
        return

    category = message.text.strip().replace("🍔 ", "").replace("🚕 ", "").replace("🛍️ ", "").replace("🎮 ", "")
    data = await state.get_data()
    amount = data["amount"]
    user_id = message.from_user.id

    async with aiosqlite.connect("expenses.db") as db:
        await db.execute(
            "INSERT INTO expenses (user_id, amount, category) VALUES (?, ?, ?)",
            (user_id, amount, category)
        )
        await db.commit()

    await message.answer(f"✅ Добавил: <b>{amount} руб</b> — <b>{category}</b>", reply_markup=main_kb)
    await state.clear()

@dp.message(F.text == "📊 Показать статистику")
async def show_stats(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("expenses.db") as db:
        async with db.execute("SELECT amount, category FROM expenses WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("📭 Пока нет сохранённых расходов.")
        return

    total = sum(row[0] for row in rows)
    text = "<b>📊 Краткая статистика:</b>\n\n"
    for amount, category in rows[-10:]:
        text += f"• {amount:.2f} руб — {category}\n"
    text += f"\n💰 <b>Итого: {total:.2f} руб</b>"

    await message.answer(text)

@dp.message(F.text == "📅 Все расходы")
async def show_all_expenses(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("expenses.db") as db:
        async with db.execute("""
            SELECT amount, category, created_at 
            FROM expenses 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("📭 У тебя пока нет расходов.")
        return

    text = "<b>🗓️ Все расходы:</b>\n\n"
    for amount, category, created_at in rows[-20:]:
        text += f"• {amount:.2f} руб — {category} ({created_at})\n"

    await message.answer(text)

@dp.message(F.text == "🗑️ Очистить все расходы")
async def clear_all_expenses(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("expenses.db") as db:
        await db.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        await db.commit()

    await message.answer("🗑️ Все твои расходы удалены.", reply_markup=main_kb)


# ---------------- Отчёты ----------------
@dp.message(F.text == "📈 Отчет")
async def ask_report_range(message: Message):
    await message.answer("📊 За какой период показать отчет?", reply_markup=report_kb)

@dp.message(F.text.in_({"📆 За день", "📅 За неделю", "🗓️ За месяц"}))
async def report_by_period(message: Message):
    user_id = message.from_user.id
    now = datetime.now()

    if message.text == "📆 За день":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif message.text == "📅 За неделю":
        start = now - timedelta(days=7)
    elif message.text == "🗓️ За месяц":
        start = now - timedelta(days=30)
    else:
        await message.answer("❌ Неизвестный период.", reply_markup=main_kb)
        return

    async with aiosqlite.connect("expenses.db") as db:
        async with db.execute("""
            SELECT amount, category, DATE(created_at)
            FROM expenses
            WHERE user_id = ? AND datetime(created_at) >= datetime(?)
            ORDER BY created_at DESC
        """, (user_id, start.strftime("%Y-%m-%d %H:%M:%S"))) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("🚫 Нет расходов за выбранный период.", reply_markup=main_kb)
        return

    # Текстовый отчет
    total = sum(row[0] for row in rows)
    text = f"<b>🧾 Отчёт ({message.text}):</b>\n\n"
    for amount, category, created_at in rows:
        text += f"• {amount:.2f} руб — {category} ({created_at})\n"
    text += f"\n💰 <b>Итого: {total:.2f} руб</b>"
    await message.answer(text)

    # --- Построение графиков ---

    # Считаем суммы по категориям и по датам
    cat_totals = defaultdict(float)
    date_totals = defaultdict(float)
    for amount, category, date in rows:
        cat_totals[category] += amount
        date_totals[date] += amount

    # 1. Круговая диаграмма расходов по категориям
    fig1, ax1 = plt.subplots()
    ax1.pie(cat_totals.values(), labels=cat_totals.keys(), autopct='%1.1f%%', startangle=140)
    ax1.axis("equal")
    plt.title("📊 Расходы по категориям")
    buf1 = io.BytesIO()
    plt.savefig(buf1, format="png")
    plt.close(fig1)
    buf1.seek(0)

    # 2. Линейный график расходов по дням
    fig2, ax2 = plt.subplots()
    dates_sorted = sorted(date_totals.keys())
    values_sorted = [date_totals[d] for d in dates_sorted]
    ax2.plot(dates_sorted, values_sorted, marker='o', linestyle='-', color='blue')
    plt.xticks(rotation=45)
    plt.title("📈 Расходы по дням")
    plt.tight_layout()
    buf2 = io.BytesIO()
    plt.savefig(buf2, format="png")
    plt.close(fig2)
    buf2.seek(0)

    # Отправляем картинки в чат
    photo1 = InputFile(buf1, filename="categories.png")
    await message.answer_photo(photo1)

    photo2 = InputFile(buf2, filename="daily.png")
    await message.answer_photo(photo2, reply_markup=main_kb)  # <-- Тут клавиатура сбрасывается


@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=main_kb)

# ---------------- Запуск ----------------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
