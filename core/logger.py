from telegram import Bot
from config import CONFIG

bot = Bot(CONFIG.TELEGRAM_TOKEN) if CONFIG.TELEGRAM_TOKEN else None

async def log(msg: str):
    logger.info(msg)
    if bot:
        try:
            await bot.send_message(chat_id=CONFIG.TELEGRAM_CHAT_ID, text=msg[:4096])
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
