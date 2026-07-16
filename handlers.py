"""
handlers.py — команды бота.
/tg [запрос] — поиск Telegram-каналов и чатов (вперемешку, с пометкой типа)
/vk [запрос] — поиск сообществ ВКонтакте
"""

import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hbold, hlink

from tg_scraper import search_tg_channels, TGChannel
from vk_scraper import search_vk_communities, VKCommunity
from config import MAX_RESULTS, ALLOWED_USERS, MIN_MEMBERS, MIN_SUBSCRIBERS

router = Router()
logger = logging.getLogger(__name__)


def _check_access(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


# ── Форматирование TG (каналы + чаты вперемешку) ──────────

def _fmt_tg(ch: TGChannel, i: int) -> str:
    lines = [f"{i}. {ch.type_emoji()} {hbold(ch.name)}"]
    lines.append(
        f"{ch.type_label()}  |  👤 {ch.username}  |  "
        f"👥 {ch.subscribers_fmt()} подписчиков"
    )
    if ch.category:
        lines.append(f"📂 {ch.category}")
    if ch.description:
        lines.append(f"📝 {ch.description[:120]}{'…' if len(ch.description) > 120 else ''}")
    lines.append(f"🔗 {hlink('Открыть', ch.tg_link())}")
    return "\n".join(lines)


# ── Форматирование VK ─────────────────────────────────────

def _fmt_vk(c: VKCommunity, i: int) -> str:
    lines = [f"{i}. {hbold(c.name)}"]
    lines.append(f"{c.status_emoji()} {c.type_label()}  |  👥 {c.members_fmt()} участников")
    if c.description:
        lines.append(f"📝 {c.description[:120]}{'…' if len(c.description) > 120 else ''}")
    lines.append(f"🔗 {hlink('Открыть сообщество', c.vk_link())}")
    return "\n".join(lines)


# ── Сборка сообщений ──────────────────────────────────────

def _build_messages(items: list, fmt_fn, query: str, platform: str, count_label: str) -> list[str]:
    if not items:
        return [f"😔 По запросу <b>{query}</b> ничего не найдено на {platform}."]

    messages = []
    header = (
        f"{'📱' if platform == 'Telegram' else '💙'} "
        f"<b>{platform}</b> · {query}: {len(items)} {count_label}\n"
        f"📢 Канал · 💬 Чат\n"
        + "─" * 32
    )
    messages.append(header)

    chunk = []
    for i, item in enumerate(items, 1):
        chunk.append(fmt_fn(item, i))
        if len(chunk) == 5:
            messages.append("\n\n".join(chunk))
            chunk = []
    if chunk:
        messages.append("\n\n".join(chunk))

    return messages


# ── VK кнопки фильтра ─────────────────────────────────────

def _vk_filter_kb(query: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📋 Все", callback_data=f"vk:0:{query}"),
        InlineKeyboardButton(text="👥 Группы", callback_data=f"vk:1:{query}"),
        InlineKeyboardButton(text="📰 Страницы", callback_data=f"vk:2:{query}"),
    ]])


# ── Команды ───────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    if not _check_access(message.from_user.id):
        return
    await message.answer(
        "👋 <b>Channel & Community Finder</b>\n\n"
        "🔍 Поиск площадок для рекламы:\n\n"
        "📱 <b>Telegram (каналы + чаты):</b>\n"
        "/tg маркетинг\n"
        "/tg таджвид\n"
        "📢 Канал · 💬 Чат — помечено в результатах\n\n"
        "💙 <b>Сообщества ВКонтакте:</b>\n"
        "/vk маркетинг\n"
        "/vk фитнес Москва\n\n"
        f"Фильтр: от 1 000 подписчиков · до {MAX_RESULTS} результатов"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    if not _check_access(message.from_user.id):
        return
    await message.answer(
        "📖 <b>Справка</b>\n\n"
        "<b>Команды:</b>\n"
        "/tg [запрос] — Telegram-каналы и чаты\n"
        "/vk [запрос] — сообщества ВКонтакте\n"
        "/help — эта справка\n\n"
        "<b>Обозначения в Telegram-результатах:</b>\n"
        "📢 — канал (только читают)\n"
        "💬 — чат/группа (можно писать)\n\n"
        "<b>Примеры:</b>\n"
        "• /tg маркетинг\n"
        "• /tg таджвид\n"
        "• /vk фитнес\n"
        "• /vk бизнес Казань"
    )


@router.message(Command("tg"))
async def cmd_tg(message: Message):
    if not _check_access(message.from_user.id):
        return
    query = message.text.removeprefix("/tg").strip()
    if not query:
        await message.answer("❓ Укажи запрос. Пример: /tg маркетинг")
        return
    await _search_tg(message, query)


@router.message(Command("vk"))
async def cmd_vk(message: Message):
    if not _check_access(message.from_user.id):
        return
    query = message.text.removeprefix("/vk").strip()
    if not query:
        await message.answer("❓ Укажи запрос. Пример: /vk маркетинг")
        return
    await _search_vk(message, query)


@router.callback_query(F.data.startswith("vk:"))
async def vk_filter(callback: CallbackQuery):
    _, ctype, query = callback.data.split(":", 2)
    await callback.answer("Фильтрую...")
    await _search_vk(callback.message, query, community_type=ctype)


# ── Логика поиска ─────────────────────────────────────────

async def _search_tg(message: Message, query: str):
    wait = await message.answer(f"📱 Ищу каналы и чаты по запросу <b>{query}</b>...")
    try:
        loop = asyncio.get_event_loop()
        channels = await loop.run_in_executor(
            None, search_tg_channels, query, MAX_RESULTS
        )
        await wait.delete()
        for text in _build_messages(channels, _fmt_tg, query, "Telegram", "результатов"):
            await message.answer(text, disable_web_page_preview=True)
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"TG поиск '{query}': {e}")
        await wait.edit_text("❌ Ошибка при поиске. Попробуй снова.")


async def _search_vk(message: Message, query: str, community_type: str = "0"):
    wait = await message.answer(f"💙 Ищу сообщества ВКонтакте по запросу <b>{query}</b>...")
    try:
        loop = asyncio.get_event_loop()
        communities = await loop.run_in_executor(
            None,
            lambda: search_vk_communities(query, MAX_RESULTS, community_type)
        )
        await wait.delete()
        parts = _build_messages(communities, _fmt_vk, query, "ВКонтакте", "сообществ")
        for i, text in enumerate(parts):
            kb = _vk_filter_kb(query) if (i == len(parts) - 1 and communities) else None
            await message.answer(text, disable_web_page_preview=True, reply_markup=kb)
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"VK поиск '{query}': {e}")
        await wait.edit_text("❌ Ошибка при поиске. Попробуй снова.")
