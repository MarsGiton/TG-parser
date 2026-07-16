"""
scraper.py — поиск Telegram-каналов по ключевым словам через tgsearch.org
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


@dataclass
class ChannelResult:
    name: str
    username: str
    subscribers: int
    description: str
    category: str = ""

    def tg_link(self) -> str:
        return f"https://t.me/{self.username.lstrip('@')}"

    def subscribers_fmt(self) -> str:
        if self.subscribers >= 1_000_000:
            return f"{self.subscribers / 1_000_000:.1f}M"
        if self.subscribers >= 1_000:
            return f"{self.subscribers / 1_000:.1f}K"
        return str(self.subscribers)


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


def _parse_page(html: str) -> list[ChannelResult]:
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

            # Username
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

            # Подписчики
            subs = 0
            m = re.search(r"([\d]+[.,]?[\d]*\s*[KkМMмm])", block_text)
            if m:
                subs = _parse_subscribers(m.group(1))

            # Описание
            desc = ""
            p = parent.find("p")
            if p:
                desc = p.get_text(strip=True)[:200]

            # Категория
            cat = ""
            for a in parent.find_all("a", href=re.compile(r"query=")):
                t = a.get_text(strip=True)
                if t and t != name:
                    cat = t
                    break

            results.append(ChannelResult(
                name=name,
                username=username,
                subscribers=subs,
                description=desc,
                category=cat,
            ))
        except Exception as e:
            logger.debug(f"Ошибка карточки: {e}")

    return results


def _fetch(query: str, page: int = 1) -> list[ChannelResult]:
    url = f"https://tgsearch.org/search?query={query}&page={page}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []
        items = _parse_page(resp.text)
        logger.info(f"[tgsearch] '{query}' стр.{page}: {len(items)}")
        return items
    except Exception as e:
        logger.error(f"[tgsearch] '{query}': {e}")
        return []


def search_channels(query: str, max_results: int = 30) -> list[ChannelResult]:
    """
    Ищем каналы по ключевому слову пользователя.
    Парсим 8 страниц, фильтруем по подписчикам.
    """
    all_results: list[ChannelResult] = []
    seen: set[str] = set()

    for page in range(1, 9):  # 8 страниц
        items = _fetch(query, page)
        if not items:
            break
        for ch in items:
            key = ch.username.lower().lstrip("@")
            if key and key not in seen:
                seen.add(key)
                all_results.append(ch)

    # Фильтр по подписчикам
    filtered = [
        ch for ch in all_results
        if ch.subscribers >= MIN_SUBSCRIBERS
        and "+" not in ch.username
    ]

    filtered.sort(key=lambda x: x.subscribers, reverse=True)

    logger.info(f"'{query}': {len(all_results)} найдено → {len(filtered)} после фильтра")
    return filtered[:max_results]
