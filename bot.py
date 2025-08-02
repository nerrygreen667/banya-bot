import logging
import sqlite3
from datetime import datetime, timedelta, time

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

API_TOKEN = "7635434708:AAE7b9t_O5XTAHqf8BB4STjMcGDtM9ygT-Y"
ADMIN_ID = 7031989165  # замени на свой Telegram ID

logging.basicConfig(level=logging.INFO)
from aiogram.client.default import DefaultBotProperties
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ========== FSM ==========
class Booking(StatesGroup):
    choosing_date = State()
    choosing_duration = State()
    choosing_time = State()
    entering_name = State()
    entering_phone = State()
    confirming = State()

# ========== БАЗА ==========
conn = sqlite3.connect("bookings.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        date TEXT,
        start_time TEXT,
        duration INTEGER,
        status TEXT
    )
""")
conn.commit()
from aiogram.utils.markdown import hbold

# ==== Клавиатура с датами (7 дней вперёд) ====
def date_keyboard():
    builder = InlineKeyboardBuilder()
    today = datetime.today()
    for i in range(7):
        day = today + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        btn_text = day.strftime("%d %b (%a)")
        builder.button(text=btn_text, callback_data=f"date:{date_str}")
    builder.adjust(2)
    return builder.as_markup()

# ==== Длительность аренды: 1–4 часа ====
def duration_keyboard():
    builder = InlineKeyboardBuilder()
    for i in range(1, 5):
        builder.button(text=f"{i} час(а)", callback_data=f"dur:{i}")
    builder.adjust(2)
    return builder.as_markup()

# ==== /start ====
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await message.answer(
        f"{hbold('Добро пожаловать!')} 🧖‍♂️\nВыберите дату бронирования:",
        reply_markup=date_keyboard()
    )
    await state.clear()
    await state.set_state(Booking.choosing_date)

# ==== Выбор даты ====
@dp.callback_query(StateFilter(Booking.choosing_date), F.data.startswith("date:"))
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    date = callback.data.split(":")[1]
    await state.update_data(date=date)
    await callback.message.edit_text(f"Дата выбрана: {date}\nТеперь выберите длительность аренды:", reply_markup=duration_keyboard())
    await state.set_state(Booking.choosing_duration)

# ==== Выбор длительности ====
@dp.callback_query(StateFilter(Booking.choosing_duration), F.data.startswith("dur:"))
async def duration_chosen(callback: CallbackQuery, state: FSMContext):
    duration = int(callback.data.split(":")[1])
    await state.update_data(duration=duration)
    await callback.message.edit_text(f"Вы выбрали {duration} час(а).\nИдёт загрузка свободных слотов...")

    # переходим к генерации слотов
    await show_free_time_slots(callback, state)
# ==== Генерация и отображение свободных слотов ====
async def show_free_time_slots(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date = data["date"]
    duration = data["duration"]

    WORK_START = 10  # 10:00
    WORK_END = 22    # 22:00

    # Все возможные часы начала
    possible_slots = []
    for hour in range(WORK_START, WORK_END - duration + 1):
        possible_slots.append(time(hour=hour).strftime("%H:%M"))

    # Получаем все уже занятые на эту дату
    cursor.execute("SELECT start_time, duration FROM bookings WHERE date = ? AND status != 'отклонено'", (date,))
    bookings = cursor.fetchall()

    # Проверяем на пересечения
    busy_hours = []
    for start, dur in bookings:
        start_hour = int(start.split(":")[0])
        for h in range(start_hour, start_hour + dur):
            busy_hours.append(h)

    # Фильтруем доступные
    free_slots = []
    for hour in range(WORK_START, WORK_END - duration + 1):
        if all((hour + i) not in busy_hours for i in range(duration)):
            free_slots.append(time(hour=hour).strftime("%H:%M"))

    if not free_slots:
        await callback.message.edit_text("❌ Нет доступных временных слотов на эту дату.\nПопробуйте другую дату.")
        return

    # Показываем пользователю
    builder = InlineKeyboardBuilder()
    for slot in free_slots:
        builder.button(text=slot, callback_data=f"time:{slot}")
    builder.adjust(2)
    await callback.message.edit_text(
        f"✅ Свободные слоты на {date} для {duration} ч:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Booking.choosing_time)

# ==== Выбор времени ====
@dp.callback_query(StateFilter(Booking.choosing_time), F.data.startswith("time:"))
async def time_chosen(callback: CallbackQuery, state: FSMContext):
    time_start = callback.data.split(":")[1]
    await state.update_data(start_time=time_start)
    await callback.message.edit_text("Введите ваше имя:")
    await state.set_state(Booking.entering_name)
# ==== Ввод имени ====
@dp.message(StateFilter(Booking.entering_name))
async def name_entered(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите номер телефона (например, +77001234567):")
    await state.set_state(Booking.entering_phone)

# ==== Ввод телефона ====
@dp.message(StateFilter(Booking.entering_phone))
async def phone_entered(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    data = await state.get_data()

    text = (
        f"<b>Проверьте данные:</b>\n"
        f"📅 Дата: {data['date']}\n"
        f"⏰ Время: {data['start_time']} на {data['duration']} ч\n"
        f"👤 Имя: {data['name']}\n"
        f"📱 Телефон: {data['phone']}\n\n"
        f"Подтвердите бронирование:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_booking")
        ]
    ])
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(Booking.confirming)

# ==== Подтверждение ====
@dp.callback_query(StateFilter(Booking.confirming), F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    cursor.execute("""
        INSERT INTO bookings (name, phone, date, start_time, duration, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (data["name"], data["phone"], data["date"], data["start_time"], data["duration"], "ожидает"))
    conn.commit()
    booking_id = cursor.lastrowid

    # Уведомление админу
    text = (
        f"<b>Новая заявка #{booking_id}</b>\n"
        f"📅 {data['date']}\n"
        f"⏰ {data['start_time']} на {data['duration']} ч\n"
        f"👤 {data['name']}\n"
        f"📱 {data['phone']}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm:{booking_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_reject:{booking_id}")
        ]
    ])
    await bot.send_message(ADMIN_ID, text, reply_markup=keyboard)

    await callback.message.edit_text("✅ Ваша заявка отправлена! Ожидайте ответа администратора.")
    await state.clear()

# ==== Отмена ====
@dp.callback_query(StateFilter(Booking.confirming), F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Бронирование отменено.")
    await state.clear()
# ==== Подтверждение заявки админом ====
@dp.callback_query(F.data.startswith("admin_confirm:"))
async def admin_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    booking_id = callback.data.split(":")[1]
    cursor.execute("UPDATE bookings SET status = 'подтверждено' WHERE id = ?", (booking_id,))
    conn.commit()

    await callback.message.edit_text(f"✅ Заявка #{booking_id} подтверждена.")

# ==== Отклонение заявки админом ====
@dp.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    booking_id = callback.data.split(":")[1]
    cursor.execute("UPDATE bookings SET status = 'отклонено' WHERE id = ?", (booking_id,))
    conn.commit()

    await callback.message.edit_text(f"❌ Заявка #{booking_id} отклонена.")
# ==== /admin - список заявок на сегодня ====
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Нет доступа.")
        return

    today = datetime.today().strftime("%Y-%m-%d")
    cursor.execute("SELECT id, name, phone, start_time, duration, status FROM bookings WHERE date = ?", (today,))
    rows = cursor.fetchall()

    if not rows:
        await message.answer("На сегодня нет заявок.")
        return

    text = f"<b>Заявки на {today}:</b>\n\n"
    for row in rows:
        text += (
            f"#{row[0]} | {row[3]}–{int(row[3].split(':')[0]) + row[4]}:00 | {row[5]}\n"
            f"👤 {row[1]} | 📱 {row[2]}\n\n"
        )
    await message.answer(text)
import asyncio

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
 
