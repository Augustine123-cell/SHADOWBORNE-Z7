import inspect
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from config import ADMIN_IDS, OWNER_IDS
from database import Database

class UserMiddleware(BaseMiddleware):
    def __init__(self, db: Database): self.db = db
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, 'from_user', None)
        if user:
            pending = None
            if isinstance(event, Message) and event.text and event.text.startswith('/start'):
                parts = event.text.split(maxsplit=1)
                if len(parts) == 2 and parts[1].startswith('ref_'):
                    try: pending = int(parts[1][4:])
                    except ValueError: pass
            self.db.add_or_update_user(user.id, user.username, user.first_name, pending_ref=pending)
            data['db'] = self.db
            data['is_admin'] = user.id in ADMIN_IDS      # owner + MONOTECH co-admin
            data['is_owner'] = user.id in OWNER_IDS      # main admin only
            data['user_row'] = self.db.get_user(user.id)
            if data['user_row'] and data['user_row']['is_banned'] and not data['is_admin']:
                if isinstance(event, CallbackQuery): await event.answer('🚫 Your account is banned.', show_alert=True)
                elif isinstance(event, Message): await event.answer('🚫 Your account is banned.')
                return
        return await handler(event, data)


def _only_accepted(func, kwargs):
    """aiogram passes ALL middleware data to a handler that accepts **kwargs.
    The real handler only declares the few it needs, so forward just those
    (this was the bug that made every admin handler crash with TypeError)."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def _role_guard(flag, deny_text):
    def decorator(func):
        async def wrapper(event, *args, **kwargs):
            if not kwargs.get(flag, False):
                if isinstance(event, Message): await event.answer(deny_text)
                elif isinstance(event, CallbackQuery): await event.answer(deny_text, show_alert=True)
                return
            return await func(event, *args, **_only_accepted(func, kwargs))
        return wrapper
    return decorator

# Owner or co-admin (upload, product review, delete product)
admin_only = _role_guard('is_admin', '🚫 Admins only.')
# Main owner only (Premium grants, coins, ban/unban, payments, broadcast...)
owner_only = _role_guard('is_owner', '🚫 Owner only.')
