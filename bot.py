cat > /root/telegram-bot/bot.py <<'EOL'
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

async def get_chat_members_count():
    """Новый метод получения количества участников"""
    try:
        if GROUP_LINK.startswith("https://t.me/"):
            channel_username = GROUP_LINK.split('/')[-1]
        elif GROUP_LINK.startswith("@"):
            channel_username = GROUP_LINK[1:]
        else:
            channel_username = GROUP_LINK
            
        chat = await bot.get_chat(f"@{channel_username}")
        return await bot.get_chat_member_count(chat.id)
    except Exception as e:
        logger.error(f"Ошибка получения количества участников: {e}")
        return 0

async def is_user_subscribed(user_id: int) -> bool:
    """Проверка подписки на канал"""
    try:
        if GROUP_LINK.startswith("https://t.me/"):
            channel_username = GROUP_LINK.split('/')[-1]
        elif GROUP_LINK.startswith("@"):
            channel_username = GROUP_LINK[1:]
        else:
            channel_username = GROUP_LINK
            
        chat = await bot.get_chat(f"@{channel_username}")
        member = await bot.get_chat_member(chat.id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# ================== КЛАВИАТУРЫ ==================
def get_subscribe_keyboard():
    """Клавиатура для подписки"""
    channel_username = GROUP_LINK.replace("https://", "").replace("t.me/", "").replace("@", "")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подписаться на канал", 
                    url=f"https://t.me/{channel_username}"
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
                InlineKeyboardButton(text="👥 Пригласить друзей", switch_inline_query="Присоединяйся к конкурсу!")
            ]
        ]
    )

# ================== ОБРАБОТЧИКИ ==================
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
        logger.error(f"Ошибка в /start: {e}")
        await message.answer("⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(F.data == "check_sub")
async def check_subscription(callback_query: CallbackQuery):
    """Проверка подписки"""
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
        logger.error(f"Ошибка проверки подписки: {e}")
        await callback_query.answer(
            "⚠️ Ошибка проверки подписки. Пожалуйста, попробуйте позже.",
            show_alert=True
        )

@dp.callback_query(F.data == "my_stats")
async def show_stats(callback_query: CallbackQuery):
    """Показать статистику"""
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
        logger.error(f"Ошибка показа статистики: {e}")
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
        logger.error(f"Ошибка показа топа: {e}")
        await callback_query.answer("⚠️ Ошибка получения топа", show_alert=True)

# ================== УВЕДОМЛЕНИЯ ==================
async def notify_admin(message: str):
    """Уведомление администратора"""
    try:
        await bot.send_message(ADMIN_ID, message)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

async def scheduled_check():
    """Периодическая проверка количества участников"""
    while True:
        try:
            if not CONTEST_ENDED:
                if await check_participants_limit():
                    break
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Ошибка в scheduled_check: {e}")
            await asyncio.sleep(600)

# ================== ЗАПУСК БОТА ==================
async def on_startup():
    """Действия при запуске"""
    await init_db()
    asyncio.create_task(scheduled_check())
    await notify_admin(
        f"🤖 Бот успешно запущен!\n\n"
        f"🔗 Ссылка на канал: {GROUP_LINK}\n"
        f"👥 Текущее количество участников: {await get_chat_members_count()}\n"
        f"🏆 Лимит участников: {MAX_PARTICIPANTS}"
    )

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
