"""
scraper.py — поиск Telegram-каналов и чатов через tgsearch.org

tgsearch.org отдаёт каналы и чаты в одной выдаче. Тип определяется
по текстовым признакам (слова "чат", "группа", "group" и т.п.
в названии/описании) — точного поля "тип" в HTML нет.
"""

import logging
import re
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass
from config import MIN_SUBSCRIBERS

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

CHAT_MARKERS = [
    "чат", "chat", "группа", "group", "групп",
    "обсужден", "флуд", "болталк", "общение", "коммьюнити",
    "community", "форум", "forum",
]


@dataclass
class TGChannel:
    name: str
    username: str
    subscribers: int
    description: str
    category: str = ""
    entry_type: str = "channel"   # "channel" или "chat"

    def tg_link(self) -> str:
        return f"https://t.me/{self.username.lstrip('@')}"

    def subscribers_fmt(self) -> str:
        if self.subscribers >= 1_000_000:
            return f"{self.subscribers / 1_000_000:.1f}M"
        if self.subscribers >= 1_000:
            return f"{self.subscribers / 1_000:.1f}K"
        return str(self.subscribers)

    def type_emoji(self) -> str:
        return "💬" if self.entry_type == "chat" else "📢"

    def type_label(self) -> str:
        return "Чат" if self.entry_type == "chat" else "Канал"


def _parse_subscribers(text: str) -> int:
    text = text.strip().upper().replace(",", ".").replace("\xa0", "").replace(" ", "")
    try:
        if "M" in text or "М" in text:
            return int(float(re.sub(r"[^\d.]", "", text)) * 1_000_000)
        if "K" in text or "К" in text:
            return int(float(re.sub(r"[^\d.]", "", text)) * 1_000)
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
    except Exception:
        return 0


def _detect_type(name: str, description: str) -> str:
    text = f"{name} {description}".lower()
    for marker in CHAT_MARKERS:
        if marker in text:
            return "chat"
    return "channel"


def _parse_page(html: str) -> list[TGChannel]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for h2 in soup.find_all("h2"):
        try:
            name = h2.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            parent = h2.find_parent(["div", "section", "article", "li"])
            if not parent:
                continue

            block_text = parent.get_text(separator="\n", strip=True)

            username = ""
            for a in parent.find_all("a", href=True):
                if "t.me/" in a["href"]:
                    slug = a["href"].split("t.me/")[-1].strip("/")
                    if slug and "+" not in slug and len(slug) >= 3:
                        username = "@" + slug
                        break
            if not username:
                m = re.search(r"@([\w_]{3,32})", block_text)
                if m:
                    username = "@" + m.group(1)
            if not username:
                continue

            subs = 0
            m = re.search(r"([\d]+[.,]?[\d]*\s*[KkМMмm])", block_text)
            if m:
                subs = _parse_subscribers(m.group(1))

            desc = ""
            p = parent.find("p")
            if p:
                desc = p.get_text(strip=True)[:200]

            cat = ""
            for a in parent.find_all("a", href=re.compile(r"query=")):
                t = a.get_text(strip=True)
                if t and t != name:
                    cat = t
                    break

            entry_type = _detect_type(name, desc)

            results.append(TGChannel(
                name=name,
                username=username,
                subscribers=subs,
                description=desc,
                category=cat,
                entry_type=entry_type,
            ))
        except Exception as e:
            logger.debug(f"Ошибка карточки: {e}")

    return results


def _fetch(query: str, page: int = 1) -> list[TGChannel]:
    url = f"https://tgsearch.org/search?query={query}&page={page}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []
        items = _parse_page(resp.text)
        logger.info(f"[TG] '{query}' стр.{page}: {len(items)}")
        return items
    except Exception as e:
        logger.error(f"[TG] '{query}': {e}")
        return []


def search_channels(query: str, max_results: int = 30) -> list[TGChannel]:
    """Поиск каналов и чатов по ключевому слову. Возвращает вперемешку."""
    all_results: list[TGChannel] = []
    seen: set[str] = set()

    for page in range(1, 9):
        items = _fetch(query, page)
        if not items:
            break
        for ch in items:
            key = ch.username.lower().lstrip("@")
            if key and key not in seen:
                seen.add(key)
                all_results.append(ch)

    filtered = [
        ch for ch in all_results
        if ch.subscribers >= MIN_SUBSCRIBERS
        and "+" not in ch.username
    ]

    filtered.sort(key=lambda x: x.subscribers, reverse=True)
    return filtered[:max_results]
