"""
handlers.py — обработчики команд.
"""

import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hbold, hlink

from scraper import search_channels, ChannelResult
from config import MAX_RESULTS, ALLOWED_USERS

router = Router()
logger = logging.getLogger(__name__)


def _check_access(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def _format_channel(ch: ChannelResult, index: int) -> str:
    lines = [f"{index}. {hbold(ch.name)}"]
    lines.append(f"👤 {ch.username}  |  👥 {ch.subscribers_fmt()} подписчиков")
    if ch.category:
        lines.append(f"📂 {ch.category}")
    if ch.description:
        desc = ch.description[:120] + ("…" if len(ch.description) > 120 else "")
        lines.append(f"📝 {desc}")
    lines.append(f"🔗 {hlink('Открыть канал', ch.tg_link())}")
    return "\n".join(lines)


def _format_results(channels: list[ChannelResult], query: str) -> list[str]:
    if not channels:
        return [
            f"😔 По запросу <b>{query}</b> ничего не найдено.\n\n"
            "Попробуй другое ключевое слово."
        ]

    messages = []
    header = (
        f"🔍 Результаты по запросу <b>{query}</b>: {len(channels)} каналов\n"
        f"Фильтр: публичные · от 1 000 подписчиков\n"
        + "─" * 30
    )
    messages.append(header)

    chunk = []
    for i, ch in enumerate(channels, 1):
        chunk.append(_format_channel(ch, i))
        if len(chunk) == 5:
            messages.append("\n\n".join(chunk))
            chunk = []
    if chunk:
        messages.append("\n\n".join(chunk))

    return messages


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not _check_access(message.from_user.id):
        return
    await message.answer(
        "👋 <b>Channel Finder</b> — поиск Telegram-каналов для рекламы\n\n"
        "Напиши ключевое слово или используй /search:\n\n"
        "/search маркетинг\n"
        "/search таджвид\n"
        "/search фитнес Москва\n\n"
        f"Показывает до {MAX_RESULTS} каналов · от 1 000 подписчиков"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    if not _check_access(message.from_user.id):
        return
    await message.answer(
        "📖 <b>Справка</b>\n\n"
        "/search [запрос] — поиск каналов\n"
        "/help — эта справка\n\n"
        "<b>Примеры:</b>\n"
        "• /search маркетинг\n"
        "• /search таджвид\n"
        "• /search фитнес\n"
        "• /search python курс\n"
        "• /search бизнес Казахстан\n\n"
        f"Максимум результатов: {MAX_RESULTS}\n"
        f"Минимум подписчиков: 1 000"
    )


@router.message(Command("search"))
async def cmd_search(message: Message):
    if not _check_access(message.from_user.id):
        return
    query = message.text.removeprefix("/search").strip()
    if not query:
        await message.answer("❓ Укажи запрос. Пример: /search маркетинг")
        return
    await _do_search(message, query)


@router.message(F.text & ~F.text.startswith("/"))
async def msg_search(message: Message):
    if not _check_access(message.from_user.id):
        return
    query = message.text.strip()
    if len(query) < 2:
        return
    await _do_search(message, query)


async def _do_search(message: Message, query: str):
    wait_msg = await message.answer(f"🔍 Ищу каналы по запросу <b>{query}</b>...")
    try:
        loop = asyncio.get_event_loop()
        channels = await loop.run_in_executor(
            None, search_channels, query, MAX_RESULTS
        )
        await wait_msg.delete()
        for msg_text in _format_results(channels, query):
            await message.answer(msg_text, disable_web_page_preview=True)
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Ошибка поиска '{query}': {e}")
        await wait_msg.edit_text("❌ Ошибка при поиске. Попробуй снова.")
