import os
import logging
import aiohttp
import aiosqlite
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Text, Command
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN", "8193351796:AAH7R7nfykFOHrGnv5bPsKc9AO3bKhGQjm0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5245320529"))

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Создание меню
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton("📈 Курсы"), KeyboardButton("   Калькулятор"))
menu.add(KeyboardButton("📝 Добавить объявление"), KeyboardButton("📋 Объявления"))
menu.add(KeyboardButton("🔄 Обновить курсы"), KeyboardButton("💬 Чат"))

# Инициализация базы данных (SQLite)
async def init_db():
    try:
        async with aiosqlite.connect('data.db') as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS rates (platform TEXT PRIMARY KEY, usdt REAL, btc REAL)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS ads (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)''')
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise

# Обработчик команды /start
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    try:
        async with aiosqlite.connect('data.db') as db:
            await db.execute('INSERT OR IGNORE INTO users (id) VALUES (?)', (message.from_user.id,))
            await db.commit()
        await message.answer("Привет! Это бот для обмена и курсов.", reply_markup=menu)
    except Exception as e:
        logger.error(f"Ошибка в send_welcome: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

# Обработчик кнопки "Курсы"
@dp.message(Text("📈 Курсы"))
async def get_rates(message: types.Message):
    try:
        async with aiosqlite.connect('data.db') as db:
            cursor = await db.execute('SELECT platform, usdt, btc FROM rates')
            rows = await cursor.fetchall()
            if not rows:
                await message.answer("Курсы ещё не установлены.")
                return
            text = "<b>Текущие курсы:</b>\n"
            for row in rows:
                platform, usdt, btc = row
                text += f"\n<b>{platform}:</b>\nUSDT: {usdt}₽\nBTC: {btc}₽\n"
            await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в get_rates: {e}")
        await message.answer("Произошла ошибка при получении курсов.")

# Функция для получения курсов с mosca.moscow
async def fetch_mosca_rates():
    url = "https://mosca.moscow/valuation"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10, headers=headers) as resp:
                resp.raise_for_status()
                html = await resp.text()
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка при запросе к mosca.moscow: {e}")
        return {'platform': 'Mosca', 'usdt': 0.0, 'btc': 0.0}
    try:
        soup = BeautifulSoup(html, "html.parser")
        usdt = btc = 0.0
        for card in soup.select(".valuation__card"):
            title_tag = card.select_one(".valuation__title")
            value_tag = card.select_one(".valuation__value")
            if not title_tag or not value_tag:
                continue
            title = title_tag.text
            value = value_tag.text.strip().replace("₽", "").replace(" ", "").replace(",", ".")
            try:
                rate = float(value)
            except ValueError:
                logger.warning(f"Невозможно преобразовать значение: {value}")
                continue
            if "USDT" in title:
                usdt = rate
            elif "BTC" in title:
                btc = rate
        return {'platform': 'Mosca', 'usdt': usdt, 'btc': btc}
    except Exception as e:
        logger.error(f"Ошибка парсинга mosca.moscow: {e}")
        return {'platform': 'Mosca', 'usdt': 0.0, 'btc': 0.0}

# Функция для получения курсов Abcex (заглушка)
async def fetch_abcex_rates():
    return {'platform': 'Abcex', 'usdt': 93.2, 'btc': 6700000.0}

# Обработчик кнопки "Обновить курсы"
@dp.message(Text("🔄 Обновить курсы"))
async def update_rates_auto(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет прав.")
        return
    await message.answer("Обновляю курсы...")
    try:
        mosca = await fetch_mosca_rates()
        abcex = await fetch_abcex_rates()
        async with aiosqlite.connect('data.db') as db:
            for rate in [mosca, abcex]:
                await db.execute(
                    'INSERT OR REPLACE INTO rates (platform, usdt, btc) VALUES (?, ?, ?)',
                    (rate['platform'], rate['usdt'], rate['btc'])
                )
            await db.commit()
        await message.answer("Курсы успешно обновлены!")
    except Exception as e:
        logger.error(f"Ошибка обновления курсов: {e}")
        await message.answer(f"Ошибка: {e}")

# Обработчик кнопки "Калькулятор"
@dp.message(Text("   Калькулятор"))
async def calculator(message: types.Message):
    await message.answer("Введи в формате:\nMosca USDT 1000")

# Универсальный обработчик
@dp.message()
async def universal_handler(message: types.Message):
    try:
        # Обработка калькулятора
        if any(p in message.text for p in ["Mosca", "Abcex"]):
            parts = message.text.strip().split()
            if len(parts) != 3:
                await message.answer("Неверный формат. Используй: <Платформа> <Валюта> <Сумма>\nПример: Mosca USDT 1000")
                return
            platform, currency, amount = parts
            try:
                amount = float(amount)
            except ValueError:
                await message.answer("Сумма должна быть числом.")
                return
            async with aiosqlite.connect('data.db') as db:
                cursor = await db.execute('SELECT usdt, btc FROM rates WHERE platform = ?', (platform,))
                row = await cursor.fetchone()
                if not row:
                    await message.answer(f"Нет данных для платформы {platform}.")
                    return
                usdt_rate, btc_rate = row
                if currency.upper() == "USDT":
                    result = amount * usdt_rate
                elif currency.upper() == "BTC":
                    result = amount * btc_rate
                else:
                    await message.answer("Неверная валюта. Используй USDT или BTC.")
                    return
                await message.answer(f"{amount} {currency.upper()} = {result:.2f}₽")
            return

        # Обработка ответа на объявление
        if message.reply_to_message and "объявление" in message.reply_to_message.text.lower():
            async with aiosqlite.connect('data.db') as db:
                await db.execute('INSERT INTO ads (content) VALUES (?)', (message.text,))
                await db.commit()
            await message.answer("Объявление сохранено")
            return

        # Обработка ответа в чат
        if message.reply_to_message and "чат" in message.reply_to_message.text.lower():
            text = f"<b>{message.from_user.first_name}:</b> {message.text}"
            async with aiosqlite.connect('data.db') as db:
                cursor = await db.execute("SELECT id FROM users")
                users = await cursor.fetchall()
            for user in users:
                try:
                    await bot.send_message(user[0], text, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")
            return
    except Exception as e:
        logger.error(f"Ошибка в universal_handler: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

# Обработчик кнопки "Добавить объявление"
@dp.message(Text("📝 Добавить объявление"))
async def add_ad(message: types.Message):
    await message.answer("Введи текст объявления")

# Обработчик кнопки "Объявления"
@dp.message(Text("📋 Объявления"))
async def show_ads(message: types.Message):
    try:
        async with aiosqlite.connect('data.db') as db:
            cursor = await db.execute('SELECT content FROM ads')
            rows = await cursor.fetchall()
        if not rows:
            await message.answer("Пусто.")
            return
        text = "\n".join([f"{i+1}. {row[0]}" for i, row in enumerate(rows)])
        await message.answer("<b>Объявления:</b>\n" + text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в show_ads: {e}")
        await message.answer("Произошла ошибка при получении объявлений.")

# Обработчик кнопки "Чат"
@dp.message(Text("💬 Чат"))
async def chat_entry(message: types.Message):
    await message.answer("Введи сообщение, оно будет разослано всем.")

# Главная функция
async def main():
    try:
        await init_db()
        logger.info("Бот запущен...")
        await dp.start_polling(bot, allowed_updates=["message"])
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
