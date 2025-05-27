import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
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

def extract_channel_username():
    """Извлекаем username канала из GROUP_LINK"""
    if GROUP_LINK.startswith("https://t.me/"):
        return GROUP_LINK.split('/')[-1].replace('@', '')
    elif GROUP_LINK.startswith("@"):
        return GROUP_LINK[1:]
    return GROUP_LINK.replace('@', '')

async def get_channel_info():
    """Универсальный метод получения информации о канале"""
    try:
        username = extract_channel_username()
        chat = await bot.get_chat(f"@{username}")
        
        # Для supergroups и channels
        if chat.type in [ChatType.CHANNEL, ChatType.SUPERGROUP]:
            try:
                members_count = await bot.get_chat_member_count(chat.id)
                return {
                    'chat_id': chat.id,
                    'username': username,
                    'type': chat.type,
                    'members_count': members_count
                }
            except Exception as e:
                logger.error(f"Ошибка получения количества участников: {str(e)}")
                return None
        else:
            logger.error("Указанный чат не является каналом или супергруппой")
            return None
            
    except Exception as e:
        error_msg = f"Критическая ошибка доступа к каналу: {str(e)}"
        logger.error(error_msg)
        await notify_admin(error_msg)
        return None

async def get_chat_members_count():
    """Альтернативный метод подсчета участников"""
    try:
        channel_info = await get_channel_info()
        if not channel_info:
            return 0
            
        # Попробуем несколько методов получения количества
        try:
            # Метод 1: через get_chat_member_count
            count = await bot.get_chat_member_count(channel_info['chat_id'])
            logger.info(f"Участников (метод 1): {count}")
            return count
        except Exception as e:
            logger.warning(f"Метод 1 не сработал: {str(e)}")
            
        try:
            # Метод 2: для публичных каналов
            chat = await bot.get_chat(channel_info['chat_id'])
            if hasattr(chat, 'members_count'):
                logger.info(f"Участников (метод 2): {chat.members_count}")
                return chat.members_count
        except Exception as e:
            logger.warning(f"Метод 2 не сработал: {str(e)}")
            
        # Если оба метода не сработали
        logger.error("Не удалось получить количество участников")
        return 0
        
    except Exception as e:
        logger.error(f"Фатальная ошибка при подсчете участников: {str(e)}")
        return 0

async def is_user_subscribed(user_id: int) -> bool:
    """Проверка подписки пользователя"""
    try:
        channel_info = await get_channel_info()
        if not channel_info:
            return False
            
        member = await bot.get_chat_member(channel_info['chat_id'], user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {str(e)}")
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
    username = extract_channel_username()
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
        logger.error(f"Ошибка отправки уведомления админу: {str(e)}")

# Обработчики команд
@dp.message(Command("start"))
async def start(message: Message):
    """Обработка команды /start"""
    try:
        if await check_participants_limit():
            await message.answer(
                "🏆 Конкурс завершен!\n\n"
                f"Мы достигли максимального количества участников - {MAX_PARTICIPANTS}!\n"
                "Результаты будут объявлены в ближайшее время.\n\n"
                "Спасибо за участие! ❤️"
            )
            return

        user = message.from_user
        await add_participant(user)

        # Обработка реферальной ссылки
        args = message.text.split()
        if len(args) > 1 and args[1].startswith("ref"):
            referrer_id = int(args[1][3:])
            if referrer_id != user.id:
                await add_referral(referrer_id, user.id)
                await bot.send_message(
                    referrer_id,
                    f"🎉 Новый реферал: {user.first_name}!\n"
                    f"Теперь у вас {(await get_user_stats(referrer_id))['referrals']} приглашений!"
                )

        if not await is_user_subscribed(user.id):
            await message.answer(
                "📢 Для участия в конкурсе необходимо подписаться на наш канал!\n\n"
                f"Осталось свободных мест: {MAX_PARTICIPANTS - CURRENT_PARTICIPANTS}",
                reply_markup=get_subscribe_keyboard()
            )
            return

        bot_username = (await bot.me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref{user.id}"
        
        await message.answer(
            f"🏡 <b>Розыгрыш акций ПИК!</b>\n\n"
            f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\n"
            f"🏆 <b>Призовой фонд:</b>\n"
            f"🥇 1 место: 3 акции ПИК (~1,050 руб)\n"
            f"🥈 2 место: 2 акции ПИК (~700 руб)\n"
            f"🥉 3 место: 1 акция ПИК (~350 руб)\n\n"
            f"📌 <b>Как увеличить шансы:</b>\n"
            f"• Приглашайте друзей по своей ссылке\n"
            f"• Каждый реферал = +1 балл\n\n"
            f"⏳ <b>Осталось мест:</b> {MAX_PARTICIPANTS - CURRENT_PARTICIPANTS}\n"
            f"📅 <b>Итоги конкурса:</b> При достижении {MAX_PARTICIPANTS} участников",
            reply_markup=get_main_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка в /start: {str(e)}")
        await message.answer("⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(F.data == "check_sub")
async def check_subscription(callback_query: CallbackQuery):
    """Проверка подписки на канал"""
    try:
        user = callback_query.from_user
        
        if await is_user_subscribed(user.id):
            await callback_query.message.edit_reply_markup(reply_markup=None)
            bot_username = (await bot.me()).username
            ref_link = f"https://t.me/{bot_username}?start=ref{user.id}"
            
            await callback_query.message.answer(
                f"✅ <b>{user.first_name}, вы успешно подписаны!</b>\n\n"
                "Теперь вы можете участвовать в конкурсе.\n\n"
                f"🔗 Ваша реферальная ссылка:\n{ref_link}",
                reply_markup=get_main_keyboard()
            )
            await callback_query.answer()
        else:
            await callback_query.answer(
                "❌ Вы не подписаны на канал!\n\n"
                "1. Нажмите кнопку 'Подписаться на канал'\n"
                "2. Подпишитесь на канал\n"
                "3. Вернитесь в бот и нажмите 'Проверить подписку'",
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {str(e)}")
        await callback_query.answer(
            "⚠️ Ошибка проверки подписки. Пожалуйста, попробуйте позже.",
            show_alert=True
        )

@dp.callback_query(F.data == "my_stats")
async def show_stats(callback_query: CallbackQuery):
    """Показать статистику пользователя"""
    try:
        stats = await get_user_stats(callback_query.from_user.id)
        bot_username = (await bot.me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref{callback_query.from_user.id}"
        
        await callback_query.message.answer(
            f"📊 <b>Ваша статистика:</b>\n\n"
            f"👤 ID: <code>{callback_query.from_user.id}</code>\n"
            f"👥 Приглашено друзей: <b>{stats['referrals']}</b>\n"
            f"🏆 Место в рейтинге: <b>В процессе...</b>\n\n"
            f"🔗 <b>Реферальная ссылка:</b>\n<code>{ref_link}</code>\n\n"
            f"⏳ <b>Осталось мест:</b> {MAX_PARTICIPANTS - CURRENT_PARTICIPANTS}",
            reply_markup=get_main_keyboard()
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка показа статистики: {str(e)}")
        await callback_query.answer("⚠️ Ошибка получения статистики", show_alert=True)

@dp.callback_query(F.data == "top_list")
async def show_top(callback_query: CallbackQuery):
    """Показать топ участников"""
    try:
        top_users = await get_top_referrers()
        text = "🏆 <b>Топ участников:</b>\n\n"
        
        if top_users:
            for i, (uid, username, first_name, refs) in enumerate(top_users, 1):
                name = f"@{username}" if username else first_name
                text += f"{i}. {name}: <b>{refs}</b> рефералов\n"
        else:
            text = "Пока нет данных о участниках."
            
        text += f"\n⏳ <b>Осталось мест:</b> {MAX_PARTICIPANTS - CURRENT_PARTICIPANTS}"
        
        await callback_query.message.answer(
            text,
            reply_markup=get_main_keyboard()
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка показа топа: {str(e)}")
        await callback_query.answer("⚠️ Ошибка получения топа", show_alert=True)

async def on_startup():
    """Действия при запуске"""
    try:
        # Проверка подключения к API
        me = await bot.get_me()
        logger.info(f"Бот @{me.username} успешно подключен к API")

        # Проверка канала
        channel_info = await get_channel_info()
        if not channel_info:
            error_msg = "Не удалось получить информацию о канале. Проверьте ссылку и права бота."
            logger.error(error_msg)
            await notify_admin(error_msg)
            raise Exception(error_msg)

        # Проверка прав бота
        bot_member = await bot.get_chat_member(channel_info['chat_id'], me.id)
        if bot_member.status not in ['administrator', 'creator']:
            error_msg = "Бот не является администратором канала!"
            logger.error(error_msg)
            await notify_admin(error_msg)
            raise Exception(error_msg)

        # Инициализация БД
        await init_db()
        
        # Уведомление админа
        members_count = await get_chat_members_count()
        await notify_admin(
            "🤖 Бот успешно запущен!\n\n"
            f"📢 Канал: {GROUP_LINK}\n"
            f"👥 Участников: {members_count}\n"
            f"🏆 Лимит: {MAX_PARTICIPANTS}"
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске: {str(e)}")
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
