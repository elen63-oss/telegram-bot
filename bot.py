import logging
import asyncio
import html
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import aiosqlite
from config import BOT_TOKEN, ADMIN_ID, GROUP_LINK, MAX_PARTICIPANTS
from llm import ask_llm

ASK_COOLDOWN = 15  # секунд между запросами /ask от одного пользователя

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="bot.log"
)
logger = logging.getLogger(__name__)

class ContestBot:
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
        self.dp = Dispatcher()
        self.contest_ended = False
        self.current_participants = 0
        self.channel_info = None
        self.last_ask = {}

    async def initialize(self):
        """Инициализация бота"""
        await self.init_db()
        self.channel_info = await self.get_channel_info()
        if not self.channel_info:
            raise Exception("Не удалось получить информацию о канале")
        
        # Проверка прав бота
        me = await self.bot.get_me()
        bot_member = await self.bot.get_chat_member(self.channel_info['chat_id'], me.id)
        if bot_member.status not in ['administrator', 'creator']:
            raise Exception("Бот не является администратором канала!")

    async def get_channel_info(self):
        """Получение информации о канале"""
        try:
            username = self.extract_channel_username()
            chat = await self.bot.get_chat(f"@{username}")
            return {
                'chat_id': chat.id,
                'username': username,
                'chat': chat
            }
        except Exception as e:
            logger.error(f"Ошибка доступа к каналу: {str(e)}")
            await self.notify_admin(f"Ошибка доступа к каналу: {str(e)}")
            return None

    @staticmethod
    def extract_channel_username():
        """Извлекаем username канала"""
        if GROUP_LINK.startswith("https://t.me/"):
            return GROUP_LINK.split('/')[-1].replace('@', '')
        return GROUP_LINK.replace('@', '')

    async def get_chat_members_count(self):
        """Получение количества участников"""
        try:
            if not self.channel_info:
                return 0
            return await self.bot.get_chat_member_count(self.channel_info['chat_id'])
        except Exception as e:
            logger.error(f"Ошибка подсчета участников: {str(e)}")
            return 0

    async def is_user_subscribed(self, user_id: int) -> bool:
        """Проверка подписки пользователя"""
        try:
            if not self.channel_info:
                return False
                
            member = await self.bot.get_chat_member(self.channel_info['chat_id'], user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Ошибка проверки подписки: {str(e)}")
            return False

    async def init_db(self):
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

    async def check_contest_status(self):
        """Проверка статуса конкурса"""
        async with aiosqlite.connect("contest.db") as db:
            cursor = await db.execute(
                "SELECT value FROM contest_settings WHERE key = 'contest_ended'"
            )
            result = await cursor.fetchone()
            return result and result[0] == "true"

    async def end_contest(self):
        """Завершение конкурса"""
        async with aiosqlite.connect("contest.db") as db:
            await db.execute(
                "UPDATE contest_settings SET value = 'true' WHERE key = 'contest_ended'"
            )
            await db.commit()
        self.contest_ended = True
        await self.notify_admin("🏆 Конкурс завершен! Достигнут лимит участников!")

    async def check_participants_limit(self):
        """Проверка лимита участников"""
        if self.contest_ended:
            return True
            
        self.current_participants = await self.get_chat_members_count()
        
        if self.current_participants >= MAX_PARTICIPANTS:
            await self.end_contest()
            return True
            
        return False

    async def add_participant(self, user: types.User):
        """Добавление участника"""
        async with aiosqlite.connect("contest.db") as db:
            await db.execute(
                """INSERT OR IGNORE INTO participants 
                   (user_id, username, first_name) 
                   VALUES (?, ?, ?)""",
                (user.id, user.username, user.first_name)
            )
            await db.commit()

    async def add_referral(self, referrer_id: int, user_id: int):
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

    async def get_user_stats(self, user_id: int) -> dict:
        """Получение статистики пользователя"""
        async with aiosqlite.connect("contest.db") as db:
            cursor = await db.execute(
                """SELECT referrals FROM participants 
                   WHERE user_id = ?""",
                (user_id,)
            )
            result = await cursor.fetchone()
            return {"referrals": result[0] if result else 0}

    async def get_top_referrers(self, limit: int = 5) -> list:
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

    def get_subscribe_keyboard(self):
        """Клавиатура для подписки"""
        username = self.extract_channel_username()
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подписаться на канал", 
                        url=f"https://t.me/{username}"
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

    def get_main_keyboard(self):
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

    async def notify_admin(self, message: str):
        """Уведомление администратора"""
        try:
            await self.bot.send_message(ADMIN_ID, message)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу: {str(e)}")

    async def setup_handlers(self):
        """Настройка обработчиков"""
        
        @self.dp.message(Command("start"))
        async def start(message: Message):
            try:
                if await self.check_participants_limit():
                    await message.answer("Конкурс завершен!")
                    return

                user = message.from_user
                await self.add_participant(user)

                args = message.text.split()
                if len(args) > 1 and args[1].startswith("ref"):
                    referrer_id = int(args[1][3:])
                    if referrer_id != user.id:
                        await self.add_referral(referrer_id, user.id)

                if not await self.is_user_subscribed(user.id):
                    await message.answer(
                        "Подпишитесь на канал для участия!",
                        reply_markup=self.get_subscribe_keyboard()
                    )
                    return

                ref_link = f"https://t.me/{(await self.bot.me()).username}?start=ref{user.id}"
                await message.answer(
                    f"Ваша реферальная ссылка: {ref_link}",
                    reply_markup=self.get_main_keyboard()
                )

            except Exception as e:
                logger.error(f"Ошибка в /start: {str(e)}")
                await message.answer("Произошла ошибка")

        @self.dp.callback_query(F.data == "check_sub")
        async def check_subscription(callback_query: CallbackQuery):
            try:
                if await self.is_user_subscribed(callback_query.from_user.id):
                    await callback_query.message.edit_reply_markup(reply_markup=None)
                    await callback_query.message.answer(
                        "Вы подписаны!",
                        reply_markup=self.get_main_keyboard()
                    )
                else:
                    await callback_query.answer("Вы не подписаны!", show_alert=True)
            except Exception as e:
                logger.error(f"Ошибка проверки подписки: {str(e)}")
                await callback_query.answer("Ошибка проверки", show_alert=True)

        @self.dp.callback_query(F.data == "my_stats")
        async def show_stats(callback_query: CallbackQuery):
            try:
                stats = await self.get_user_stats(callback_query.from_user.id)
                await callback_query.message.answer(
                    f"Ваши рефералы: {stats['referrals']}",
                    reply_markup=self.get_main_keyboard()
                )
            except Exception as e:
                logger.error(f"Ошибка показа статистики: {str(e)}")
                await callback_query.answer("Ошибка статистики", show_alert=True)

        @self.dp.callback_query(F.data == "top_list")
        async def show_top(callback_query: CallbackQuery):
            try:
                top_users = await self.get_top_referrers()
                text = "Топ участников:\n\n"
                for i, (_, username, first_name, refs) in enumerate(top_users, 1):
                    name = f"@{username}" if username else first_name
                    text += f"{i}. {name}: {refs}\n"
                await callback_query.message.answer(text)
            except Exception as e:
                logger.error(f"Ошибка показа топа: {str(e)}")
                await callback_query.answer("Ошибка топа", show_alert=True)

        @self.dp.message(Command("ask"))
        async def ask(message: Message):
            try:
                parts = message.text.split(maxsplit=1)
                if len(parts) < 2:
                    await message.answer("Использование: /ask ваш вопрос")
                    return

                user_id = message.from_user.id
                wait = ASK_COOLDOWN - (time.monotonic() - self.last_ask.get(user_id, 0))
                if wait > 0:
                    await message.answer(f"Подождите {int(wait) + 1} сек.")
                    return
                self.last_ask[user_id] = time.monotonic()

                await self.bot.send_chat_action(message.chat.id, "typing")
                answer = await ask_llm(parts[1])
                for i in range(0, len(answer), 3500):
                    await message.answer(html.escape(answer[i:i + 3500]))
            except Exception as e:
                logger.error(f"Ошибка в /ask: {str(e)}")
                await message.answer("ИИ сейчас недоступен, попробуйте позже")

    async def run(self):
        """Запуск бота"""
        try:
            await self.initialize()
            await self.setup_handlers()
            
            me = await self.bot.get_me()
            logger.info(f"Бот @{me.username} запущен")
            await self.notify_admin(f"Бот @{me.username} запущен")
            
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка запуска: {str(e)}")
            await self.notify_admin(f"Ошибка запуска: {str(e)}")
        finally:
            await self.bot.session.close()

if __name__ == "__main__":
    bot = ContestBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
