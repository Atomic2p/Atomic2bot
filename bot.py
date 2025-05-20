import os
import logging
import aiohttp
import asyncpg
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
API_TOKEN = "8193351796:AAH7R7nfykFOHrGnv5bPsKc9AO3bKhGQjm0"
ADMIN_ID = 5245320529
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/botdb")

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Создание меню
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton("📈 Курсы"), KeyboardButton("   Калькулятор"))
menu.add(KeyboardButton("📝 Добавить объявление"), KeyboardButton("📋 Объявления"))
menu.add(KeyboardButton("🔄 Обновить курсы"), KeyboardButton("💬 Чат"))

# Инициализация базы данных (PostgreSQL)
async def init_db():
    try:
        pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rates (
                    platform TEXT PRIMARY KEY,
                    usdt REAL,
                    btc REAL
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS ads (
                    id SERIAL PRIMARY KEY,
                    content TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY
                )
            ''')
        return pool
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise

# Обработчик команды /start
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
        await conn.execute('INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING', message.from_user.id)
    await message.answer("Привет! Это бот для обмена и курсов.", reply_markup=menu)

# Обработчик кнопки "Курсы"
@dp.message(Text("📈 Курсы"))
async def get_rates(message: types.Message):
    async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
        rows = await conn.fetch('SELECT platform, usdt, btc FROM rates')
        if not rows:
            await message.answer("Курсы ещё не установлены.")
            return
        text = "<b>Текущие курсы:</b>\n"
        for row in rows:
            platform, usdt, btc = row['platform'], row['usdt'], row['btc']
            text += f"\n<b>{platform}:</b>\nUSDT: {usdt}₽\nBTC: {btc}₽\n"
        await message.answer(text, parse_mode="HTML")

# Функция для получения курсов с mosca.moscow
async def fetch_mosca_rates():
    url = "https://mosca.moscow/valuation"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                html = await resp.text()
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка при запросе к mosca.moscow: {e}")
        return {'platform': 'Mosca', 'usdt': 0.0, 'btc': 0.0}
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
        async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
            for rate in [mosca, abcex]:
                await conn.execute(
                    'INSERT INTO rates (platform, usdt, btc) VALUES ($1, $2, $3) '
                    'ON CONFLICT (platform) DO UPDATE SET usdt = $2, btc = $3',
                    rate['platform'], rate['usdt'], rate['btc']
                )
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
        async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
            row = await conn.fetchrow('SELECT usdt, btc FROM rates WHERE platform = $1', platform)
            if not row:
                await message.answer(f"Нет данных для платформы {platform}.")
                return
            usdt_rate, btc_rate = row['usdt'], row['btc']
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
        async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
            await conn.execute('INSERT INTO ads (content) VALUES ($1)', message.text)
        await message.answer("Объявление сохранено")
        return

    # Обработка ответа в чат
    if message.reply_to_message and "чат" in message.reply_to_message.text.lower():
        text = f"<b>{message.from_user.first_name}:</b> {message.text}"
        async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
            users = await conn.fetch("SELECT id FROM users")
        for user in users:
            try:
                await bot.send_message(user['id'], text, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение пользователю {user['id']}: {e}")
        return

# Обработчик кнопки "Добавить объявление"
@dp.message(Text("📝 Добавить объявление"))
async def add_ad(message: types.Message):
    await message.answer("Введи текст объявления")

# Обработчик кнопки "Объявления"
@dp.message(Text("📋 Объявления"))
async def show_ads(message: types.Message):
    async with (await asyncpg.create_pool(dsn=DATABASE_URL)).acquire() as conn:
        rows = await conn.fetch('SELECT content FROM ads')
    if not rows:
        await message.answer("Пусто.")
        return
    text = "\n".join([f"{i+1}. {row['content']}" for i, row in enumerate(rows)])
    await message.answer("<b>Объявления:</b>\n" + text, parse_mode="HTML")

# Обработчик кнопки "Чат"
@dp.message(Text("💬 Чат"))
async def chat_entry(message: types.Message):
    await message.answer("Введи сообщение, оно будет разослано всем.")

# Главная функция
async def main():
    try:
        await init_db()
        await dp.start_polling(bot, allowed_updates=["message"])
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
