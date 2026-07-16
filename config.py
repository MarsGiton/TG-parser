import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MIN_SUBSCRIBERS: int = int(os.getenv("MIN_SUBSCRIBERS", "1000"))
MAX_RESULTS: int = int(os.getenv("MAX_RESULTS", "40"))

ALLOWED_USERS: list[int] = [
    int(x.strip())
    for x in os.getenv("ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
]

def validate_config():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")
