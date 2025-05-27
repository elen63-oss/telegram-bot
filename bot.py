import logging
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import aiosqlite
from config import BOT_TOKEN, ADMIN_ID, GROUP_LINK, MAX_PARTICIPANTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("contest.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MyBot:
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.username = None
        self.contest_ended = False

    async def init(self):
        me = await self.bot.get_me()
        self.username = me.username
        await self.load_contest_status()
        return self

    async def load_contest_status(self):
        try:
            async with aiosqlite.connect("contest.db") as db:
                cursor = await db.execute(
                    "SELECT value FROM contest_settings WHERE key = 'contest_ended'")
                result = await cursor.fetchone()
                self.contest_ended = result and result[0] == "true"
        except Exception as e:
            logger.error(f"Ошибка загрузки статуса конкурса: {e}")
            await notify_admin(f"⚠️ Ошибка загрузки статуса конкурса: {e}")

async def init_db():
    try:
        async with aiosqlite.connect("contest.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS participants (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    referrals INTEGER DEFAULT 0,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS contest_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT)""")
            await db.execute(
                "INSERT OR IGNORE INTO contest_settings (key, value) VALUES (?, ?)",
                ("contest_ended", "false"))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        await notify_admin(f"⚠️ Критическая ошибка БД: {e}")

async def safe_db_execute(query, params=()):
    try:
        async with aiosqlite.connect("contest.db") as db:
            await db.execute(query, params)
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        await notify_admin(f"⚠️ Ошибка БД: {e}")
        return False

async def check_participants_limit():
    try:
        channel_username = GROUP_LINK.split('/')[-1]
        chat = await bot_instance.bot.get_chat(f"@{channel_username}")
        current = chat.members_count
        
        if current >= MAX_PARTICIPANTS and not bot_instance.contest_ended:
            await end_contest()
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки участников: {e}")
        await notify_admin(f"⚠️ Ошибка проверки участников: {e}")
        return False

async def end_contest():
    if await safe_db_execute(
        "UPDATE contest_settings SET value = 'true' WHERE key = 'contest_ended'"
    ):
        bot_instance.contest_ended = True
        await notify_admin(
            f"🏆 Конкурс завершен!\n"
            f"Участников: {MAX_PARTICIPANTS}\n"
            f"Время завершения: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

async def scheduled_checker():
    while True:
        try:
            if not bot_instance.contest_ended:
                if await check_participants_limit():
                    break
            await asyncio.sleep(1800)
        except Exception as e:
            logger.error(f"Ошибка в scheduled_checker: {e}")
            await asyncio.sleep(300)

async def get_stats():
    try:
        async with aiosqlite.connect("contest.db") as db:
            cursor = await db.execute("SELECT COUNT(*) FROM participants")
            total = (await cursor.fetchone())[0]
            
            cursor = await db.execute("""
                SELECT username, first_name, referrals 
                FROM participants 
                ORDER BY referrals DESC 
                LIMIT 5""")
            top = await cursor.fetchall()
            
            cursor = await db.execute(
                "SELECT value FROM contest_settings WHERE key = 'contest_ended'")
            status = "завершен" if (await cursor.fetchone())[0] == "true" else "активен"
            
            return total, top, status
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await notify_admin(f"⚠️ Ошибка получения статистики: {e}")
        return 0, [], "неизвестен"

async def notify_admin(message: str):
    try:
        await bot_instance.bot.send_message(ADMIN_ID, message)
        logger.info(f"Уведомление отправлено админу: {message}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

def get_keyboards():
    channel_username = GROUP_LINK.split('/')[-1]
    subscribe_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подписаться", url=f"https://t.me/{channel_username}")],
        [InlineKeyboardButton(text="🔁 Проверить", callback_data="check_sub")]
    ])
    main_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="👥 Пригласить", switch_inline_query="Присоединяйся!")]
    ])
    return subscribe_kb, main_kb

async def main():
    global bot_instance
    bot_instance = await MyBot().init()
    dp = bot_instance.dp
    
    @dp.message(Command("stats"))
    async def admin_stats(message: Message):
        if message.from_user.id != ADMIN_ID:
            await message.answer("🚫 Доступ запрещен!")
            return
        
        total, top, status = await get_stats()
        text = (
            f"📊 Статистика конкурса:\n\n"
            f"🏁 Статус: {status}\n"
            f"👥 Всего участников: {total}\n"
            f"🏆 Топ рефералов:\n"
        )
        
        for i, (username, name, refs) in enumerate(top, 1):
            text += f"{i}. {username or name}: {refs}\n"
        
        await message.answer(text)

    @dp.message(Command("start"))
    async def start(message: Message):
        try:
            if bot_instance.contest_ended:
                await message.answer("🏆 Конкурс завершен! Спасибо за участие!")
                return

            user = message.from_user
            
            if not await safe_db_execute(
                "INSERT OR IGNORE INTO participants (user_id, username, first_name) VALUES (?, ?, ?)",
                (user.id, user.username, user.first_name)
            ):
                await message.answer("⚠️ Ошибка регистрации. Попробуйте позже.")
                return

            args = message.text.split()
            if len(args) > 1 and args[1].startswith("ref"):
                referrer_id = int(args[1][3:])
                if referrer_id != user.id:
                    if await safe_db_execute(
                        "UPDATE participants SET referrals = referrals + 1 WHERE user_id = ?",
                        (referrer_id,)
                    ):
                        await notify_admin(f"🎉 Новый реферал: {user.first_name} (@{user.username})")

            subscribe_kb, main_kb = get_keyboards()
            
            if not await is_user_subscribed(user.id):
                await message.answer("📢 Для участия подпишитесь на канал!", 
                                  reply_markup=subscribe_kb)
                return
                
            ref_link = f"https://t.me/{bot_instance.username}?start=ref{user.id}"
            await message.answer(
                f"🎉 Добро пожаловать в конкурс!\n\n"
                f"🔗 Ваша реферальная ссылка:\n<code>{ref_link}</code>",
                reply_markup=main_kb)
                
        except Exception as e:
            logger.error(f"Ошибка в /start: {e}")
            await message.answer("⚠️ Произошла ошибка. Попробуйте позже.")

    @dp.callback_query(F.data == "check_sub")
    async def check_sub(callback_query: CallbackQuery):
        try:
            user = callback_query.from_user
            _, main_kb = get_keyboards()
            
            if await is_user_subscribed(user.id):
                await callback_query.message.edit_reply_markup(reply_markup=None)
                await callback_query.message.answer(
                    f"✅ {user.first_name}, вы подписаны!",
                    reply_markup=main_kb)
                await callback_query.answer()
            else:
                await callback_query.answer("❌ Вы не подписаны!", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback_query.answer("⚠️ Ошибка", show_alert=True)

    @dp.callback_query(F.data == "my_stats")
    async def show_stats(callback_query: CallbackQuery):
        try:
            stats = await get_user_stats(callback_query.from_user.id)
            await callback_query.message.answer(
                f"📊 Ваши рефералы: <b>{stats['referrals']}</b>")
            await callback_query.answer()
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback_query.answer("⚠️ Ошибка", show_alert=True)

    await init_db()
    asyncio.create_task(scheduled_checker())
    await notify_admin(f"🤖 Бот запущен!\nВремя: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    await dp.start_polling(bot_instance.bot)

if __name__ == "__main__":
    asyncio.run(main())
    