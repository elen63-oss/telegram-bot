import asyncio
from config import GROUP_LINK, BOT_TOKEN
from aiogram import Bot

async def test_channel_access():
    print("\n=== Testing channel access ===")
    print("Channel link:", GROUP_LINK)
    
    username = GROUP_LINK.replace('https://t.me/', '').replace('@', '')
    print("Extracted username:", username)
    
    try:
        bot = Bot(BOT_TOKEN)
        print("\n1. Connecting to Telegram API...")
        me = await bot.get_me()
        print(f"Bot @{me.username} connected successfully")
        
        print("\n2. Getting chat info...")
        chat = await bot.get_chat(f"@{username}")
        print("Chat ID:", chat.id)
        print("Chat type:", chat.type)
        
        print("\n3. Getting members count...")
        count = await bot.get_chat_member_count(chat.id)
        print("Members count:", count)
        
        print("\n4. Checking bot permissions...")
        bot_member = await bot.get_chat_member(chat.id, me.id)
        print("Bot status:", bot_member.status)
        
        print("\n✅ All checks passed successfully!")
    except Exception as e:
        print("\n❌ Error:", str(e))
    finally:
        await bot.session.close()

asyncio.run(test_channel_access())