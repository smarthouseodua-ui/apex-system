import os


def get_allowed_chat_id() -> int:
    return int(os.getenv("APPS_SYSTEM_BOT_CHAT_ID", "0"))


def is_allowed(user_id: int) -> bool:
    return user_id == get_allowed_chat_id()
