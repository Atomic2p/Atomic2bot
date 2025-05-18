import logging
import aiohttp
import aiosqlite
import os
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton("📈 Курсы"), KeyboardButton("🧮 Калькулятор"))
menu.add(KeyboardButton("📝 Добавить объявление"), KeyboardButton("📋 Объявления"))
menu.add(KeyboardButton("🔄 Обновить курсы"), KeyboardButton("💬 Чат"))

async def init_db():
    async with aiosqlite.connect('data.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS rates (platform TEXT PRIMARY KEY, usdt REAL, btc REAL)')
        await db.execute('CREATE TABLE IF NOT EXISTS ads (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT)')
        await db.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)')
        await db.commit()

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    async with aiosqlite.connect('data.db') as db:
        await db.execute('INSERT OR IGNORE INTO users (id) VALUES (?)', (message.from_user.id,))
        await db.commit()
    await message.answer("Привет! Это бот для обмена и курсов.", reply_markup=menu)

@dp.message_handler(lambda m: m.text == "📈 Курсы")
async def get_rates(message: types.Message):
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

async def fetch_mosca_rates():
    url = "https://mosca.moscow/valuation"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()
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
            continue
        if "USDT" in title:
            usdt = rate
        elif "BTC" in title:
            btc = rate
    return {'platform': 'Mosca', 'usdt': usdt, 'btc': btc}

async def fetch_abcex_rates():
    return {'platform': 'Abcex', 'usdt': 93.2, 'btc': 6700000.0}

@dp.message_handler(lambda m: m.text == "🔄 Обновить курсы")
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
                await db.execute('REPLACE INTO rates (platform, usdt, btc) VALUES (?, ?, ?)', (rate['platform'], rate['usdt'], rate['btc']))
            await db.commit()
        await message.answer("Курсы успешно обновлены!")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message_handler(lambda m: m.text == "🧮 Калькулятор")
async def calculator(message: types.Message):
    await message.answer("Введи в формате:\nMosca USDT 1000")

@dp.message_handler()
async def universal_handler(message: types.Message):
    if any(p in message.text for p in ["Mosca", "Abcex"]):
        parts = message.text.strip().split()
        if len(parts) != 3:
            return
        platform, currency, amount = parts
        try:
            amount = float(amount)
        except ValueError:
            return
        async with aiosqlite.connect('data.db') as db:
            cursor = await db.execute('SELECT usdt, btc FROM rates WHERE platform = ?', (platform,))
            row = await cursor.fetchone()
            if not row:
                await message.answer("Нет данных.")
                return
            usdt_rate, btc_rate = row
            if currency.upper() == "USDT":
                result = amount * usdt_rate
            elif currency.upper() == "BTC":
                result = amount * btc_rate
            else:
                await message.answer("Неверная валюта.")
                return
            await message.answer(f"{amount} {currency.upper()} = {result}₽")
        return

    if message.reply_to_message:
        if "объявление" in message.reply_to_message.text.lower():
            async with aiosqlite.connect('data.db') as db:
                await db.execute('INSERT INTO ads (content) VALUES (?)', (message.text,))
                await db.commit()
            await message.answer("Объявление сохранено")
            return
        if "чат" in message.reply_to_message.text.lower():
            text = f"<b>{message.from_user.first_name}:</b> {message.text}"
            async with aiosqlite.connect('data.db') as db:
                cursor = await db.execute("SELECT id FROM users")
                users = await cursor.fetchall()
            for user in users:
                try:
                    await bot.send_message(user[0], text, parse_mode="HTML")
                except:
                    continue
            return

@dp.message_handler(lambda m: m.text == "📝 Добавить объявление")
async def add_ad(message: types.Message):
    await message.answer("Введи текст объявления")

@dp.message_handler(lambda m: m.text == "📋 Объявления")
async def show_ads(message: types.Message):
    async with aiosqlite.connect('data.db') as db:
        cursor = await db.execute('SELECT content FROM ads')
        rows = await cursor.fetchall()
    if not rows:
        await message.answer("Пусто.")
        return
    text = "\n".join([f"{i+1}. {row[0]}" for i, row in enumerate(rows)])
    await message.answer("<b>Объявления:</b>\n" + text, parse_mode="HTML")

@dp.message_handler(lambda m: m.text == "💬 Чат")
async def chat_entry(message: types.Message):
    await message.answer("Введи сообщение, оно будет разослано всем.")

if __name__ == '__main__':
    import asyncio
    asyncio.run(init_db())
    executor.start_polling(dp, skip_updates=True)
