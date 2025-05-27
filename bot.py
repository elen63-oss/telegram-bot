import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery
)
import aiosqlite
from config import BOT_TOKEN, ADMIN_ID, GROUP_LINK, MAX_PARTICIPANTS

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="bot.log"
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Глобальные переменные
CONTEST_ENDED = False
CURRENT_PARTICIPANTS = 0

async def get_channel_info():
    """Получение информации о канале"""
    try:
        if GROUP_LINK.startswith("https://t.me/"):
            channel_username = GROUP_LINK.split('/')[-1]
        elif GROUP_LINK.startswith("@"):
            channel_username = GROUP_LINK[1:]
        else:
            channel_username = GROUP_LINK
            
        chat = await bot.get_chat(f"@{channel_username}")
        members_count = await bot.get_chat_members_count(chat.id)
        return {
            'chat_id': chat.id,
            'username': channel_username,
            'members_count': members_count
        }
    except Exception as e:
        logger.error(f"Ошибка получения информации о канале: {e}")
        await notify_admin(f"Ошибка доступа к каналу: {e}")
        return None

async def get_chat_members_count():
    """Получение количества участников канала"""
    channel_info = await get_channel_info()
    return channel_info['members_count'] if channel_info else 0

async def is_user_subscribed(user_id: int) -> bool:
    """Проверка подписки пользователя на канал"""
    try:
        channel_info = await get_channel_info()
        if not channel_info:
            return False
            
        member = await bot.get_chat_member(channel_info['chat_id'], user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect("contest.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contest_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrals INTEGER DEFAULT 0,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                user_id INTEGER UNIQUE,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES participants(user_id)
            )
        """)
        
        await db.execute(
            "INSERT OR IGNORE INTO contest_settings (key, value) VALUES (?, ?)",
            ("contest_ended", "false")
        )
        await db.commit()

async def check_contest_status():
    """Проверка статуса конкурса"""
    async with aiosqlite.connect("contest.db") as db:
        cursor = await db.execute(
            "SELECT value FROM contest_settings WHERE key = 'contest_ended'"
        )
        result = await cursor.fetchone()
        return result and result[0] == "true"

async def end_contest():
    """Завершение конкурса"""
    async with aiosqlite.connect("contest.db") as db:
        await db.execute(
            "UPDATE contest_settings SET value = 'true' WHERE key = 'contest_ended'"
        )
        await db.commit()
    global CONTEST_ENDED
    CONTEST_ENDED = True
    await notify_admin("🏆 Конкурс завершен! Достигнут лимит участников!")

async def check_participants_limit():
    """Проверка лимита участников"""
    global CURRENT_PARTICIPANTS, CONTEST_ENDED
    
    if CONTEST_ENDED:
        return True
        
    CURRENT_PARTICIPANTS = await get_chat_members_count()
    
    if CURRENT_PARTICIPANTS >= MAX_PARTICIPANTS:
        await end_contest()
        return True
        
    return False

async def add_participant(user: types.User):
    """Добавление участника"""
    async with aiosqlite.connect("contest.db") as db:
        await db.execute(
            """INSERT OR IGNORE INTO participants 
               (user_id, username, first_name) 
               VALUES (?, ?, ?)""",
            (user.id, user.username, user.first_name)
        )
        await db.commit()

async def add_referral(referrer_id: int, user_id: int):
    """Добавление реферала"""
    async with aiosqlite.connect("contest.db") as db:
        await db.execute(
            "UPDATE participants SET referrals = referrals + 1 WHERE user_id = ?",
            (referrer_id,)
        )
        await db.execute(
            """INSERT OR IGNORE INTO referrals 
               (referrer_id, user_id) 
               VALUES (?, ?)""",
            (referrer_id, user_id)
        )
        await db.commit()

async def get_user_stats(user_id: int) -> dict:
    """Получение статистики пользователя"""
    async with aiosqlite.connect("contest.db") as db:
        cursor = await db.execute(
            """SELECT referrals FROM participants 
               WHERE user_id = ?""",
            (user_id,)
        )
        result = await cursor.fetchone()
        return {"referrals": result[0] if result else 0}

async def get_top_referrers(limit: int = 5) -> list:
    """Получение топа участников"""
    async with aiosqlite.connect("contest.db") as db:
        cursor = await db.execute(
            """SELECT p.user_id, p.username, p.first_name, p.referrals 
               FROM participants p
               ORDER BY p.referrals DESC 
               LIMIT ?""",
            (limit,)
        )
        return await cursor.fetchall()

def get_subscribe_keyboard():
    """Клавиатура для подписки"""
    channel_info = asyncio.run(get_channel_info())
    if not channel_info:
        return None
        
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подписаться на канал", 
                    url=f"https://t.me/{channel_info['username']}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔁 Проверить подписку", 
                    callback_data="check_sub"
                )
            ]
        ]
    )

def get_main_keyboard():
    """Основная клавиатура"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats"),
                InlineKeyboardButton(text="🏆 Топ участников", callback_data="top_list")
            ],
            [
                InlineKeyboardButton(
                    text="👥 Пригласить друзей", 
                    switch_inline_query="Присоединяйся к конкурсу!"
                )
            ]
        ]
    )

async def notify_admin(message: str):
    """Уведомление администратора"""
    try:
        await bot.send_message(ADMIN_ID, message)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

# [Остальные обработчики остаются без изменений]
# ... (добавьте свои обработчики команд и callback'ов)

async def on_startup():
    """Действия при запуске"""
    try:
        await init_db()
        
        # Проверка подключения к каналу
        channel_info = await get_channel_info()
        if not channel_info:
            raise Exception("Не удалось подключиться к каналу!")
            
        await notify_admin(
            f"🤖 Бот успешно запущен!\n"
            f"📢 Канал: @{channel_info['username']}\n"
            f"👥 Участников: {channel_info['members_count']}\n"
            f"🏆 Лимит: {MAX_PARTICIPANTS}"
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        raise

async def on_shutdown():
    """Действия при выключении"""
    await notify_admin("🔴 Бот выключается...")

async def main():
    """Основная функция"""
    await on_startup()
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
