import asyncio
import logging
import os
import pickle
import random
import time
import uuid
from pathlib import Path
from typing import Dict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

# ---------- НАСТРОЙКИ ИЗ .env ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
SUPPORT_ID = int(os.getenv("SUPPORT_ID", 0))
STARS_WALLET_USERNAME = os.getenv("STARS_WALLET_USERNAME", "onyx_wallet")

CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "💎")
CURRENCY_RATE = int(os.getenv("CURRENCY_RATE", 10))
MIN_REFILL = int(os.getenv("MIN_REFILL", 10))
STARS_RATE = int(os.getenv("STARS_RATE", 8))

DATA_FILE = "shop_data.pkl"

LEVELS = [
    (0, "Новичок", 0),
    (500, "Любитель", 0),
    (2000, "Бывалый", 5),
    (5000, "Ветеран", 10),
    (15000, "Элита", 15),
]

ACHIEVEMENTS = {
    "first_purchase": "Первая покупка",
    "big_spender_10k": "Кит (потрачено 10k 💎)",
    "collector_50": "Коллекционер (50 товаров)",
    "referral_5": "Реферал-мастер (5 друзей)",
    "level_elite": "Элитный ранг",
}

# ---------- ПОЛНЫЙ КАТАЛОГ (пример структуры, полный список скопируйте из предыдущих версий) ----------
CATALOG = {
    "📱 Telegram аккаунты": [
        ("🇷🇺 РФ старый", "Аккаунт Telegram с отлёжкой, зарегистрирован на российский номер. Передаётся в формате: номер + код подтверждения. Вы получите ссылку на вход.", 12.0),
        ("🇷🇺 РФ свежий", "Свежий аккаунт, ручная регистрация, без спамблока. Моментальная выдача в боте после оплаты.", 9.0),
        ("🇷🇺 РФ верифицированный", "Привязан паспорт, высокая надёжность. После покупки администратор пришлёт данные для входа в течение часа.", 40.0),
        # ... весь остальной каталог (вставьте полный список из предыдущего кода)
    ],
    # ... остальные категории
}
CATEGORY_KEYS = list(CATALOG.keys())

# ---------- БАЗА ДАННЫХ (добавлено поле admin_refilled) ----------
class Database:
    def __init__(self):
        self.users: Dict[int, dict] = {}

    def get_user(self, user_id: int) -> dict:
        if user_id not in self.users:
            ref_code = str(uuid.uuid4())[:8]
            self.users[user_id] = {
                "balance": 0.0,
                "cart": [],
                "purchases": [],
                "total_spent": 0.0,
                "purchases_count": 0,
                "refill_requests": 0,
                "achievements": [],
                "ref_code": ref_code,
                "referred_by": None,
                "referral_bonus_claimed": False,
                "admin_refilled": False,      # флаг пополнения админом
                "referrals_count": 0,
                "total_referral_earnings": 0.0,
            }
        return self.users[user_id]

    def save(self):
        with open(DATA_FILE, "wb") as f:
            pickle.dump(self.users, f)

    def load(self):
        if Path(DATA_FILE).exists():
            with open(DATA_FILE, "rb") as f:
                self.users = pickle.load(f)

db = Database()
db.load()

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

# ---------- Состояния ----------
class PaymentStates(StatesGroup):
    waiting_for_check = State()

class StarsStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_stars_check = State()

class RubleStates(StatesGroup):
    waiting_for_rub_amount = State()
    waiting_for_rub_check = State()

class SupportStates(StatesGroup):
    waiting_for_issue = State()

class AdminRefillStates(StatesGroup):
    waiting_for_amount = State()

# ---------- Вспомогательные функции ----------
def get_user_level(total_spent: float):
    for threshold, name, discount in reversed(LEVELS):
        if total_spent >= threshold:
            return name, discount
    return LEVELS[0][1], LEVELS[0][2]

def apply_discount(price: float, discount: int) -> float:
    return round(price * (100 - discount) / 100, 1)

def get_discount_for_user(user: dict) -> int:
    _, discount = get_user_level(user.get("total_spent", 0.0))
    return discount

# ---------- КЛАВИАТУРЫ ----------
def main_kb(user_id: int) -> InlineKeyboardMarkup:
    user = db.get_user(user_id)
    discount = get_discount_for_user(user)
    discount_text = f" (скидка {discount}%)" if discount else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔥 СКИДКИ ДО 30% СЕГОДНЯ! ЖМИ!{discount_text}", callback_data="catalog")],
        [
            InlineKeyboardButton(text=f"{CURRENCY_SYMBOL} Баланс: {user['balance']:.1f}", callback_data="balance"),
            InlineKeyboardButton(text=f"💰 Пополнить (мин. {MIN_REFILL}💎)", callback_data="refill_menu"),
        ],
        [
            InlineKeyboardButton(text="🛒 Корзина", callback_data="cart"),
            InlineKeyboardButton(text="📜 Мои покупки", callback_data="purchases"),
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🎲 Дуэль (ставка 50💎)", callback_data="duel"),
        ],
        [InlineKeyboardButton(text="🏆 Достижения", callback_data="achievements")],
        [InlineKeyboardButton(text="💌 Рефералы", callback_data="referral")],
        [InlineKeyboardButton(text="🛡 Правила", callback_data="rules")],
        [InlineKeyboardButton(text="🆘 Помощь", callback_data="help")],
        [InlineKeyboardButton(text="🛟 Техподдержка", callback_data="support")],
    ])

def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

# ---------- ОБРАБОТЧИК START ----------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = db.get_user(message.from_user.id)
    args = message.text.split()
    if len(args) > 1 and user.get("referred_by") is None:
        ref_code = args[1]
        for uid, u in db.users.items():
            if u.get("ref_code") == ref_code and uid != message.from_user.id:
                user["referred_by"] = uid
                referrer = db.users[uid]
                referrer["balance"] += 0.2
                referrer["total_referral_earnings"] += 0.2
                referrer["referrals_count"] = referrer.get("referrals_count", 0) + 1
                db.save()
                try:
                    await bot.send_message(uid, "🎉 По вашей ссылке новый пользователь! +0.2💎", parse_mode='HTML')
                except:
                    pass
                break
    await message.answer(
        "🕶️ Добро пожаловать в <b>OnyxHub</b> – единственный подпольный супермаркет!\n"
        "🔥 <b>ТОЛЬКО СЕГОДНЯ:</b> скидки до 30% на ВСЁ! Не упусти!\n"
        "⚠️ <b>Остерегайтесь подделок!</b> Это оригинальный бот.\n"
        f"💰 Мин. пополнение {MIN_REFILL}💎. Жми «Каталог» 👇",
        reply_markup=main_kb(message.from_user.id),
        parse_mode='HTML',
    )

# ---------- ГЛАВНОЕ МЕНЮ ----------
@dp.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛒 <b>OnyxHub – главное меню</b>\n⚡️ Эксклюзивные предложения! Пополни счёт и получи бонус.\n"
        "🛟 Нужна помощь? Жми «Техподдержка».",
        reply_markup=main_kb(callback.from_user.id),
        parse_mode='HTML',
    )
    await callback.answer()

# ---------- ПРОФИЛЬ ----------
@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    spent = user["total_spent"]
    rank_name, discount = get_user_level(spent)
    next_threshold = None
    for th, _, _ in LEVELS:
        if th > spent:
            next_threshold = th
            break
    if next_threshold:
        progress = spent
        max_progress = next_threshold
        bar_len = 10
        filled = int(progress / max_progress * bar_len) if max_progress > 0 else 0
        bar = "▓" * filled + "░" * (bar_len - filled)
        progress_text = f"{progress:.1f} / {max_progress}"
    else:
        bar = "▓" * 10
        progress_text = "MAX"

    text = (
        f"👤 <b>Профиль OnyxHub</b>\n"
        f"🆔 <code>{callback.from_user.id}</code>\n"
        f"📛 @{callback.from_user.username or 'нет'}\n"
        f"💎 Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL}\n"
        f"⬆️ Ранг: {rank_name} (скидка {discount}%)\n"
        f"📊 Уровень: [{bar}] {progress_text}\n"
        f"💰 Потрачено: {spent:.1f}{CURRENCY_SYMBOL}\n"
        f"📦 Куплено: {user['purchases_count']} товаров\n"
        f"🏆 Достижений: {len(user['achievements'])}\n"
        f"👥 Рефералов: {user['referrals_count']}\n"
        f"💸 Заработано на рефералах: {user['total_referral_earnings']:.1f}{CURRENCY_SYMBOL}\n"
        f"🔗 Реф. код: <code>{user['ref_code']}</code>"
    )
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

# ---------- ДОСТИЖЕНИЯ ----------
@dp.callback_query(F.data == "achievements")
async def show_achievements(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    achieved = user["achievements"]
    text = "🏆 <b>Достижения</b>\n"
    for key, name in ACHIEVEMENTS.items():
        text += f"{'✅' if key in achieved else '🔒'} {name}\n"
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

# ---------- РЕФЕРАЛЬНАЯ ПРОГРАММА ----------
@dp.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    bot_username = (await bot.me()).username
    ref_link = f"https://t.me/{bot_username}?start={user['ref_code']}"
    text = (
        "💌 <b>Реферальная программа</b>\n"
        "Пригласи друга – получи <b>0.2💎</b> за каждого!\n\n"
        f"Твой код: <code>{user['ref_code']}</code>\n"
        f"Ссылка: {ref_link}\n\n"
        f"👥 Приглашено: {user['referrals_count']}\n"
        f"💸 Заработано: {user['total_referral_earnings']:.1f}{CURRENCY_SYMBOL}"
    )
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

# ---------- ДУЭЛЬ (КУБЫ) ----------
@dp.callback_query(F.data == "duel")
async def start_duel(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user["balance"] < 50:
        await callback.answer("Недостаточно средств! Нужно 50💎", show_alert=True)
        return
    user["balance"] -= 50
    db.save()

    client_dice = random.randint(1, 6)
    bot_dice = random.randint(1, 6)

    result_text = f"🎲 Вы бросили кубик: {client_dice}\n"
    result_text += f"🎲 Соперник бросил: {bot_dice}\n\n"

    if client_dice > bot_dice:
        user["balance"] += 100
        db.save()
        result_text += "🎉 Победа! Вы получаете +50💎 (итого +50💎 к балансу)."
    elif client_dice == bot_dice:
        user["balance"] += 50
        db.save()
        result_text += "🤝 Ничья! Ваша ставка возвращена."
    else:
        result_text += "😞 Поражение! Вы потеряли 50💎."

    await callback.message.edit_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Сыграть ещё (50💎)", callback_data="duel")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
        ]),
        parse_mode='HTML',
    )
    await callback.answer()

# ---------- ТЕХПОДДЕРЖКА ----------
@dp.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🛟 <b>Техподдержка</b>\nОпишите вашу проблему или вопрос в одном сообщении.\nМенеджер ответит вам в ближайшее время.",
        reply_markup=back_to_main_kb(),
        parse_mode='HTML',
    )
    await state.set_state(SupportStates.waiting_for_issue)
    await callback.answer()

@dp.message(SupportStates.waiting_for_issue)
async def receive_issue(message: Message, state: FSMContext):
    user = db.get_user(message.from_user.id)
    text_to_support = (
        f"🛟 <b>Новое обращение в техподдержку</b>\n"
        f"От: @{message.from_user.username or 'нет юзернейма'} (ID: <code>{message.from_user.id}</code>)\n"
        f"Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL}\n\n"
        f"<b>Сообщение:</b>\n{message.text}"
    )
    try:
        await bot.send_message(SUPPORT_ID, text_to_support, parse_mode='HTML')
    except Exception as e:
        logging.error(f"Не удалось отправить менеджеру: {e}")
        await message.answer("⚠️ Не удалось отправить обращение. Попробуйте позже.", reply_markup=back_to_main_kb())
        await state.clear()
        return
    await message.answer("✅ Ваше обращение принято. Ожидайте ответа от администратора.", reply_markup=back_to_main_kb())
    await state.clear()

# ---------- ПОПОЛНЕНИЕ (меню) ----------
@dp.callback_query(F.data == "refill_menu")
async def refill_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Пополнить через Telegram Stars", callback_data="refill_stars")],
        [InlineKeyboardButton(text="💸 Пополнить через рубли (Stars)", callback_data="refill_rubles")],
        [InlineKeyboardButton(text="💱 CryptoBot (чек @send)", callback_data="refill_crypto")],
        [InlineKeyboardButton(text="🔹 Запрос админу (обычное)", callback_data="request_refill")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])
    await callback.message.edit_text(
        f"⚠️ <b>Минимальная сумма пополнения:</b> {MIN_REFILL}💎.\nВыберите способ:",
        reply_markup=kb,
        parse_mode='HTML',
    )
    await callback.answer()

# ---------- Stars ----------
@dp.callback_query(F.data == "refill_stars")
async def refill_stars_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💎 <b>Пополнение через Telegram Stars</b>\n\n"
        "Введите, сколько 💎 вы хотите получить (минимум 10).\n"
        f"Курс: 1💎 ≈ {STARS_RATE} звёзд.\n\n"
        f"Переведите нужное количество звёзд на аккаунт <b>@{STARS_WALLET_USERNAME}</b>, а затем отправьте сюда скриншот или описание перевода.",
        reply_markup=back_to_main_kb(),
        parse_mode='HTML',
    )
    await state.set_state(StarsStates.waiting_for_amount)

@dp.message(StarsStates.waiting_for_amount, F.text)
async def stars_amount_entered(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount < MIN_REFILL:
            await message.answer(f"❌ Минимальная сумма {MIN_REFILL}💎. Попробуйте ещё раз.", reply_markup=back_to_main_kb())
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ Введите число.", reply_markup=back_to_main_kb())
        await state.clear()
        return

    stars_needed = round(amount * STARS_RATE)
    instruction = (
        f"💎 Чтобы получить {amount}💎, переведите <b>{stars_needed} звёзд</b> на аккаунт <b>@{STARS_WALLET_USERNAME}</b>.\n\n"
        "После перевода отправьте сюда <b>скриншот</b> или <b>ссылку на чек</b>.\n"
        "Администратор проверит перевод и зачислит 💎."
    )
    await message.answer(instruction, parse_mode='HTML', reply_markup=back_to_main_kb())
    await state.update_data(amount=amount)
    await state.set_state(StarsStates.waiting_for_stars_check)

@dp.message(StarsStates.waiting_for_stars_check, F.text)
async def stars_check_received(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    user = db.get_user(message.from_user.id)
    text_to_admin = (
        f"⭐ <b>Пополнение через Stars</b>\n"
        f"От: @{message.from_user.username or 'нет юзернейма'} (ID: <code>{message.from_user.id}</code>)\n"
        f"Запрошено: {amount}💎 (≈ {round(amount * STARS_RATE)} звёзд)\n"
        f"Баланс сейчас: {user['balance']:.1f}{CURRENCY_SYMBOL}\n\n"
        f"<b>Сообщение пользователя:</b>\n{message.text}\n\n"
        "<i>Нажмите кнопку ниже, чтобы ввести сумму для начисления.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Начислить 💎", callback_data=f"admin_refill_{message.from_user.id}")]
    ])
    await bot.send_message(ADMIN_ID, text_to_admin, parse_mode='HTML', reply_markup=kb)
    await message.answer("✅ Чек отправлен на проверку. Администратор скоро начислит вам 💎.", reply_markup=back_to_main_kb())
    await state.clear()

# ---------- Рубли ----------
@dp.callback_query(F.data == "refill_rubles")
async def refill_rubles_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💸 <b>Пополнение через рубли (Telegram Stars)</b>\n\n"
        "Введите сумму в <b>рублях</b>, которую хотите потратить (минимум 130₽).\n"
        f"Курс: 1💎 ≈ {STARS_RATE} звёзд, 100 звёзд ≈ 130₽ ≈ 13💎.\n"
        f"Звёзды можно купить дешевле в боте @inkLandStarsBot, а затем перевести на <b>@{STARS_WALLET_USERNAME}</b>.",
        reply_markup=back_to_main_kb(),
        parse_mode='HTML',
    )
    await state.set_state(RubleStates.waiting_for_rub_amount)

@dp.message(RubleStates.waiting_for_rub_amount, F.text)
async def rub_amount_entered(message: Message, state: FSMContext):
    try:
        rub_amount = float(message.text)
        if rub_amount < 130:
            await message.answer("❌ Минимальная сумма 130₽. Попробуйте снова.", reply_markup=back_to_main_kb())
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ Введите число.", reply_markup=back_to_main_kb())
        await state.clear()
        return

    diamonds = rub_amount / CURRENCY_RATE
    stars_needed = round(diamonds * STARS_RATE)
    instruction = (
        f"💸 Чтобы получить примерно {diamonds:.1f}💎, переведите <b>{stars_needed} звёзд</b> на аккаунт <b>@{STARS_WALLET_USERNAME}</b>.\n\n"
        "1. Приобретите звёзды в @inkLandStarsBot (там дешевле).\n"
        "2. Переведите их на @onyx_wallet.\n"
        "3. Пришлите сюда скриншот или чек.\n\n"
        "Администратор начислит 💎 после проверки."
    )
    await message.answer(instruction, parse_mode='HTML', reply_markup=back_to_main_kb())
    await state.update_data(diamonds=diamonds)
    await state.set_state(RubleStates.waiting_for_rub_check)

@dp.message(RubleStates.waiting_for_rub_check, F.text)
async def rub_check_received(message: Message, state: FSMContext):
    data = await state.get_data()
    diamonds = data.get("diamonds")
    user = db.get_user(message.from_user.id)
    text_to_admin = (
        f"💸 <b>Пополнение через рубли</b>\n"
        f"От: @{message.from_user.username or 'нет юзернейма'} (ID: <code>{message.from_user.id}</code>)\n"
        f"Примерная сумма: {diamonds:.1f}💎\n"
        f"Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL}\n\n"
        f"<b>Сообщение:</b>\n{message.text}\n\n"
        "<i>Нажмите кнопку для начисления.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Начислить 💎", callback_data=f"admin_refill_{message.from_user.id}")]
    ])
    await bot.send_message(ADMIN_ID, text_to_admin, parse_mode='HTML', reply_markup=kb)
    await message.answer("✅ Чек отправлен. Ожидайте зачисления 💎.", reply_markup=back_to_main_kb())
    await state.clear()

# ---------- Обычный запрос админу ----------
@dp.callback_query(F.data == "request_refill")
async def request_refill(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    user["refill_requests"] += 1
    db.save()
    await bot.send_message(
        ADMIN_ID,
        f"🔄 Запрос пополнения\nОт: @{callback.from_user.username or '—'} (ID: {callback.from_user.id})\n"
        f"Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL}\n"
        "Используйте админ-панель для начисления."
    )
    await callback.answer("📤 Заявка отправлена.", show_alert=True)
    await callback.message.edit_text("Заявка отправлена. Ожидайте.", reply_markup=back_to_main_kb())

# ---------- CryptoBot ----------
@dp.callback_query(F.data == "refill_crypto")
async def refill_crypto(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("💱 Отправьте ссылку на чек @send (мин. 10💎).", reply_markup=back_to_main_kb())
    await state.set_state(PaymentStates.waiting_for_check)

@dp.message(PaymentStates.waiting_for_check, F.text)
async def receive_check(message: Message, state: FSMContext):
    user = db.get_user(message.from_user.id)
    check_text = message.text
    text_to_admin = (
        f"💱 Чек от @{message.from_user.username or '—'} (ID: {message.from_user.id})\n"
        f"Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL}\n\n"
        f"{check_text}\n\n"
        "<i>Нажмите для начисления.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Начислить 💎", callback_data=f"admin_refill_{message.from_user.id}")]
    ])
    await bot.send_message(ADMIN_ID, text_to_admin, reply_markup=kb)
    await message.answer("✅ Чек получен, ожидайте пополнения.")
    await state.clear()

# ---------- Админ: начисление произвольной суммы + установка флага ----------
@dp.callback_query(F.data.startswith("admin_refill_"))
async def admin_refill_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    uid_str = callback.data.split("_")[2]
    uid = int(uid_str)
    await state.update_data(target_uid=uid)
    await callback.message.answer(f"Введите сумму 💎 для начисления пользователю ID {uid}:")
    await state.set_state(AdminRefillStates.waiting_for_amount)

@dp.message(AdminRefillStates.waiting_for_amount)
async def admin_refill_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return

    data = await state.get_data()
    uid = data.get("target_uid")
    user = db.get_user(uid)
    user["balance"] += amount
    user["admin_refilled"] = True
    db.save()
    await message.answer(f"✅ Начислено {amount}{CURRENCY_SYMBOL} пользователю ID {uid}.")
    try:
        await bot.send_message(uid, f"💰 Ваш баланс пополнен на {amount}{CURRENCY_SYMBOL}!")
    except:
        pass
    await state.clear()

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("apanel"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    total = len(db.users)
    await message.answer(
        f"🛡️ Админ-панель\nПользователей: {total}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="💾 Сохранить", callback_data="admin_save")],
        ]),
    )

@dp.callback_query(F.data.startswith("admin_"))
async def admin_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    data = callback.data
    if data == "admin_users":
        text = "👥 Пользователи:\n"
        for uid, u in db.users.items():
            text += f"• ID {uid} | {u['balance']:.1f}{CURRENCY_SYMBOL} | корзина: {len(u['cart'])}\n"
        kb = [[InlineKeyboardButton(f"ID {uid}", callback_data=f"admin_user_{uid}")] for uid in db.users]
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    elif data.startswith("admin_user_"):
        uid = int(data.split("_")[2])
        u = db.get_user(uid)
        await callback.message.edit_text(
            f"Пользователь {uid}\nБаланс: {u['balance']:.1f}{CURRENCY_SYMBOL}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Начислить/Списать", callback_data=f"admin_refill_{uid}")],
                [InlineKeyboardButton(text="🗑 Очистить корзину", callback_data=f"admin_clear_cart_{uid}")],
                [InlineKeyboardButton(text="🔙 К списку", callback_data="admin_users")],
            ]),
        )
    elif data.startswith("admin_clear_cart_"):
        uid = int(data.split("_")[3])
        db.get_user(uid)["cart"] = []
        db.save()
        await callback.answer("Корзина очищена.", show_alert=True)
    elif data == "admin_broadcast":
        await callback.message.edit_text("Используйте /broadcast <текст>")
    elif data == "admin_save":
        db.save()
        await callback.answer("Сохранено.", show_alert=True)
    elif data == "admin_back":
        await admin_panel(callback.message)

@dp.message(Command("broadcast"))
async def broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.partition(" ")[2]
    if not text:
        return await message.answer("Формат: /broadcast текст")
    sent = 0
    for uid in db.users:
        try:
            await bot.send_message(uid, f"📢 Рассылка OnyxHub:\n{text}")
            sent += 1
        except:
            pass
    await message.answer(f"Отправлено {sent} пользователям.")

# ---------- КАТАЛОГ И ПОКУПКИ (с проверкой admin_refilled и оповещением) ----------
@dp.callback_query(F.data == "catalog")
async def show_catalog(callback: CallbackQuery):
    kb = [[InlineKeyboardButton(text=cat_name, callback_data=f"category_{i}")] for i, cat_name in enumerate(CATEGORY_KEYS)]
    kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    await callback.message.edit_text(
        "📋 <b>Категории товаров OnyxHub</b>\nВсе позиции на 20% ниже рынка! Хватай, пока не разобрали.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode='HTML',
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("category_"))
async def show_category(callback: CallbackQuery):
    idx_str = callback.data.split("_")[1]
    if not idx_str.isdigit():
        await callback.answer("Ошибка категории.", show_alert=True)
        return
    idx = int(idx_str)
    if idx < 0 or idx >= len(CATEGORY_KEYS):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    cat_name = CATEGORY_KEYS[idx]
    items = CATALOG[cat_name]
    if not items:
        await callback.answer("Категория пуста.", show_alert=True)
        return
    kb = []
    for i, (name, desc, price) in enumerate(items):
        kb.append([InlineKeyboardButton(
            text=f"{name}",
            callback_data=f"item_{idx}_{i}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="catalog")])
    await callback.message.edit_text(
        f"📁 <b>{cat_name}</b>\nВыберите товар для подробностей.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode='HTML',
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("item_"))
async def show_item_card(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Неверные данные.", show_alert=True)
        return
    cat_idx_str, item_idx_str = parts[1], parts[2]
    if not cat_idx_str.isdigit() or not item_idx_str.isdigit():
        await callback.answer("Неверные индексы.", show_alert=True)
        return
    cat_idx = int(cat_idx_str)
    item_idx = int(item_idx_str)
    if cat_idx < 0 or cat_idx >= len(CATEGORY_KEYS):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    cat_name = CATEGORY_KEYS[cat_idx]
    items = CATALOG[cat_name]
    if item_idx < 0 or item_idx >= len(items):
        await callback.answer("Товар не найден.", show_alert=True)
        return
    name, desc, price = items[item_idx]
    price_rub = price * CURRENCY_RATE
    card_text = (
        f"💎 <b>{name}</b>\n\n"
        f"📦 <b>Что это:</b> {desc}\n\n"
        f"💰 <b>Цена:</b> {price:.1f}💎 (≈ {price_rub:.0f} ₽)\n\n"
        f"<i>После покупки товар попадёт в раздел «Мои покупки». "
        f"Для получения свяжитесь с администратором (в игре).</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Добавить в корзину", callback_data=f"add_{cat_idx}_{item_idx}")],
        [InlineKeyboardButton(text="🔙 Назад к категории", callback_data=f"category_{cat_idx}")],
    ])
    await callback.message.edit_text(card_text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Неверные данные.", show_alert=True)
        return
    cat_idx_str, item_idx_str = parts[1], parts[2]
    if not cat_idx_str.isdigit() or not item_idx_str.isdigit():
        await callback.answer("Неверные индексы.", show_alert=True)
        return
    cat_idx = int(cat_idx_str)
    item_idx = int(item_idx_str)
    if cat_idx < 0 or cat_idx >= len(CATEGORY_KEYS):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    cat_name = CATEGORY_KEYS[cat_idx]
    items = CATALOG[cat_name]
    if item_idx < 0 or item_idx >= len(items):
        await callback.answer("Товар не найден.", show_alert=True)
        return
    name, desc, price = items[item_idx]
    user = db.get_user(callback.from_user.id)
    user["cart"].append((cat_name, item_idx, name, price))
    db.save()
    await callback.answer(f"{name} добавлен в корзину!", show_alert=False)
    await callback.message.answer(
        f"🛒 <b>Добавлено:</b> {name}\nВ корзине уже {len(user['cart'])} товаров.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Перейти в корзину", callback_data="cart")]
        ]),
        parse_mode='HTML',
    )

@dp.callback_query(F.data == "cart")
async def show_cart(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    cart = user["cart"]
    if not cart:
        text = "🛒 Корзина пуста."
        kb = [[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]
    else:
        discount = get_discount_for_user(user)
        total = 0.0
        text = "🛒 <b>Ваша корзина:</b>\n"
        for i, (cat_name, item_idx, name, price) in enumerate(cart, 1):
            final_price = apply_discount(price, discount) if discount else price
            total += final_price
            text += f"{i}. {name} – {final_price:.1f}{CURRENCY_SYMBOL} (~{final_price*CURRENCY_RATE:.0f}₽)\n"
        text += f"\n💰 Итого: {total:.1f}{CURRENCY_SYMBOL} (~{total*CURRENCY_RATE:.0f}₽)\n"
        text += f"💎 Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL}\n"
        if user["balance"] < total:
            text += "⚠️ <b>Недостаточно средств!</b>"
        kb = [
            [InlineKeyboardButton(text="🛍 Купить всё", callback_data="buy_all")],
            [InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
        ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: CallbackQuery):
    db.get_user(callback.from_user.id)["cart"] = []
    db.save()
    await callback.message.edit_text("🗑 Корзина очищена.", reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == "buy_all")
async def buy_all(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user["admin_refilled"]:
        await callback.answer("❌ Сначала пополните баланс через администратора (мин. 10💎).", show_alert=True)
        return
    cart = user["cart"]
    if not cart:
        await callback.answer("Корзина пуста.", show_alert=True)
        return
    discount = get_discount_for_user(user)
    total = 0.0
    items_purchased = []
    for item in cart:
        price = item[3]
        if discount:
            price = apply_discount(price, discount)
        total += price
        items_purchased.append((item[0], item[1], item[2], price))  # cat_name, idx, name, final_price
    if user["balance"] < total:
        await callback.answer(f"Недостаточно средств! Не хватает {total - user['balance']:.1f}💎", show_alert=True)
        return
    user["balance"] -= total
    user["total_spent"] += total
    user["purchases_count"] += len(cart)

    ach = user.setdefault("achievements", [])
    if "first_purchase" not in ach:
        ach.append("first_purchase")
    if user["purchases_count"] >= 50 and "collector_50" not in ach:
        ach.append("collector_50")
    if user["total_spent"] >= 10000 and "big_spender_10k" not in ach:
        ach.append("big_spender_10k")
    if user["total_spent"] >= 15000 and "level_elite" not in ach:
        ach.append("level_elite")

    if user.get("referred_by") and not user.get("referral_bonus_claimed"):
        referrer_id = user["referred_by"]
        referrer = db.users.get(referrer_id)
        if referrer:
            referrer["balance"] += 50.0
            referrer["total_spent"] += 50.0
            user["balance"] += 50.0
            user["referral_bonus_claimed"] = True
            db.save()
            try:
                await bot.send_message(referrer_id, "🎉 Ваш реферал сделал первую покупку! Вам начислено 50💎.")
            except:
                pass

    purchase_details = []
    for cat_name, item_idx, name, price in items_purchased:
        items = CATALOG[cat_name]
        desc = items[item_idx][1] if item_idx < len(items) else ""
        user["purchases"].append({
            "category": cat_name,
            "name": name,
            "price": price,
            "description": desc,
        })
        purchase_details.append(f"{name} – {price:.1f}💎")
    cart.clear()
    db.save()

    # Оповещение админу
    admin_msg = (
        f"🛍 <b>Новая покупка в OnyxHub</b>\n"
        f"Покупатель: @{callback.from_user.username or 'нет'} (ID: <code>{callback.from_user.id}</code>)\n"
        f"Сумма: {total:.1f}💎\n"
        f"Товары:\n" + "\n".join(purchase_details)
    )
    await bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')

    await callback.message.edit_text(
        f"✅ Покупка совершена! Списано {total:.1f}{CURRENCY_SYMBOL}.\n"
        "Товары в «Мои покупки».\n"
        "Ожидайте выдачу от менеджера в течение 24 часов.",
        reply_markup=back_to_main_kb(),
        parse_mode='HTML',
    )
    await callback.answer("Успешно!")

@dp.callback_query(F.data == "purchases")
async def show_purchases(callback: CallbackQuery):
    purchases = db.get_user(callback.from_user.id)["purchases"]
    if not purchases:
        text = "📜 Покупок нет."
    else:
        text = "📜 <b>Мои покупки:</b>\n"
        for i, p in enumerate(purchases, 1):
            text += f"{i}. {p['name']} – {p['price']:.1f}{CURRENCY_SYMBOL}\n   _{p['description']}_\n"
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == "balance")
async def balance_info(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    await callback.answer(f"Баланс: {user['balance']:.1f}{CURRENCY_SYMBOL} (~{user['balance']*CURRENCY_RATE:.0f}₽)", show_alert=True)

# ---------- ПРАВИЛА И ПОМОЩЬ ----------
@dp.callback_query(F.data == "rules")
async def rules(callback: CallbackQuery):
    text = (
        "🛡 <b>Правила OnyxHub</b>\n\n"
        "✅ Единственный официальный магазин.\n"
        "❗️ Вы берёте на себя ответственность за использование товаров.\n"
        f"💎 Мин. пополнение {MIN_REFILL}💎, возврата нет."
    )
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == "help")
async def help_cmd(callback: CallbackQuery):
    text = (
        "🆘 <b>Помощь</b>\n"
        f"💎 1{CURRENCY_SYMBOL} ≈ {CURRENCY_RATE}₽\n"
        f"💰 Мин. пополнение: {MIN_REFILL}💎\n"
        "🎲 Дуэль (ставка 50💎)\n"
        "👥 Реферальная программа (+0.2💎 за друга)\n"
        "🛟 Техподдержка – по любым вопросам"
    )
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode='HTML')
    await callback.answer()

# ---------- ЗАПУСК ----------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
