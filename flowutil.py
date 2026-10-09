"""Small helper shared by every multi-step (FSM) flow."""
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from keyboards import MENU_TEXTS


async def escaped(msg: Message, state: FSMContext) -> bool:
    """If the person taps a menu button or sends /cancel in the middle of a flow, drop the flow
    instead of storing the button label as an answer. Returns True when the flow was cancelled."""
    text = (msg.text or '').strip()
    if text in MENU_TEXTS or text.split('@')[0].lower() == '/cancel':
        await state.clear()
        await msg.answer('❎ Cancelled. Tap what you want again.')
        return True
    return False
