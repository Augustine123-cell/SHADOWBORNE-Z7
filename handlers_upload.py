"""Guided upload wizard.

Who can use it
  * Admins (owner + MONOTECH co-admin): Admin -> 📤 Upload. Published immediately.
  * Premium sellers: Seller Panel -> ➕ Add Product. Goes to admin review first.
Normal users never see an upload option.

Steps: category -> title -> author -> description -> chapters -> price -> (admin: Stars price,
premium-only) -> cover photo -> file -> preview -> publish.
"""
import html
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from middlewares import admin_only
from states import Upload
from flowutil import escaped
from config import SELLER_COMMISSION, OWNER_IDS, MONOTECH_USER_ID

router = Router()
SKIP = '-'


def _kb(*rows):
    b = InlineKeyboardBuilder()
    for text, cb in rows:
        b.button(text=text, callback_data=cb)
    b.adjust(1)
    return b.as_markup()


def _cancel_row():
    return ('❌ Cancel', 'up:cancel')


def _preview_text(d, desc_max=1500):
    lines = [f"<b>{html.escape(d['name'])}</b>"]
    if d.get('author'):
        lines.append(f"✍️ Author: {html.escape(d['author'])}")
    if d.get('chapters'):
        lines.append(f"📖 Chapters: {d['chapters']}")
    desc = d['desc'] if len(d['desc']) <= desc_max else d['desc'][:desc_max - 1] + '…'
    lines.append(f"\n{html.escape(desc)}\n")
    lines.append(f"💰 Price: <b>{d['price']}</b> coins")
    if d.get('stars'):
        lines.append(f"⭐ Stars price: {d['stars']}")
    if d.get('premium_only'):
        lines.append('👑 Premium only')
    lines.append('📎 File: ' + ('text content' if d['ctype'] == 'text' else 'attached ✅'))
    return '\n'.join(lines)


# ---------------- entry points ----------------
async def _start(cb: CallbackQuery, state: FSMContext, db, mode: str):
    cats = db.get_categories()
    b = InlineKeyboardBuilder()
    for c in cats:
        b.button(text=f"{c['icon']} {c['name']}", callback_data=f"upcat:{c['id']}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text='❌ Cancel', callback_data='up:cancel'))
    await state.clear()
    await state.set_state(Upload.category)
    await state.update_data(mode=mode)
    await cb.message.answer('📤 <b>Upload</b>\n\nWhich category are you uploading to?', reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data == 'admin:upload')
@admin_only
async def admin_upload_start(cb: CallbackQuery, state: FSMContext, db):
    await _start(cb, state, db, 'admin')


@router.callback_query(F.data == 'sel:add')
async def seller_upload_start(cb: CallbackQuery, state: FSMContext, db):
    # Sellers must hold an approved (= Premium) seller account. Normal users are refused.
    if db.seller_status(cb.from_user.id) != 'approved':
        await cb.answer('⭐ Premium is required to sell. Renew/buy Premium first.', show_alert=True)
        return
    await _start(cb, state, db, 'seller')


# ---------------- cancel ----------------
@router.message(Command('cancel'))
async def cancel_cmd(msg: Message, state: FSMContext):
    if await state.get_state() is None:
        await msg.answer('Nothing to cancel.')
        return
    await state.clear()
    await msg.answer('❎ Cancelled.')


@router.callback_query(F.data == 'up:cancel')
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer('❎ Upload cancelled.')
    await cb.answer()


# ---------------- steps ----------------
@router.callback_query(Upload.category, F.data.startswith('upcat:'))
async def step_category(cb: CallbackQuery, state: FSMContext):
    await state.update_data(category=int(cb.data.split(':')[1]))
    await state.set_state(Upload.name)
    await cb.message.answer('📝 Send the <b>title / name</b>:')
    await cb.answer()


@router.message(Upload.name)
async def step_name(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    name = (msg.text or '').strip()
    if len(name) < 2 or len(name) > 120:
        await msg.answer('Title must be 2–120 characters. Try again.')
        return
    await state.update_data(name=name)
    await state.set_state(Upload.author)
    await msg.answer('✍️ Send the <b>author</b> (or send <code>-</code> to skip):')


@router.message(Upload.author)
async def step_author(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    t = (msg.text or '').strip()
    await state.update_data(author='' if t == SKIP else t[:80])
    await state.set_state(Upload.desc)
    await msg.answer('📝 Send the <b>description</b>:')


@router.message(Upload.desc)
async def step_desc(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    t = (msg.text or '').strip()
    if len(t) < 3 or len(t) > 1500:
        await msg.answer('Description must be 3–1500 characters. Try again.')
        return
    await state.update_data(desc=t)
    await state.set_state(Upload.chapters)
    await msg.answer('📖 How many <b>chapters</b>? Send a number (or <code>-</code> to skip):')


@router.message(Upload.chapters)
async def step_chapters(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    t = (msg.text or '').strip()
    if t == SKIP:
        n = 0
    elif t.isdigit() and 0 < int(t) <= 5000:
        n = int(t)
    else:
        await msg.answer('Send a whole number like 12, or <code>-</code> to skip.')
        return
    await state.update_data(chapters=n)
    d = await state.get_data()
    await state.set_state(Upload.price)
    extra = f"\n\nYou keep {100 - SELLER_COMMISSION}% of each sale (standard seller rate)." if d['mode'] == 'seller' else ''
    await msg.answer('💰 Send the <b>price in coins</b> (whole number, <code>0</code> = free):' + extra)


@router.message(Upload.price)
async def step_price(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    t = (msg.text or '').strip()
    if not t.isdigit() or int(t) > 10_000_000:
        await msg.answer('Send a whole number of coins, like 50.')
        return
    await state.update_data(price=int(t))
    d = await state.get_data()
    if d['mode'] == 'admin':
        await state.set_state(Upload.stars)
        await msg.answer('⭐ Send the <b>Telegram Stars price</b> (<code>0</code> = no direct Stars purchase):')
    else:
        await state.update_data(stars=0, premium_only=False)
        await _ask_cover(msg, state)


@router.message(Upload.stars)
async def step_stars(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    t = (msg.text or '').strip()
    if not t.isdigit() or int(t) > 1_000_000:
        await msg.answer('Send 0 or a positive whole number.')
        return
    await state.update_data(stars=int(t))
    await state.set_state(Upload.premium)
    await msg.answer('👑 Premium members only?', reply_markup=_kb(('✅ Yes, Premium only', 'uppre:1'), ('🌍 No, everyone', 'uppre:0'), _cancel_row()))


@router.callback_query(Upload.premium, F.data.startswith('uppre:'))
async def step_premium(cb: CallbackQuery, state: FSMContext):
    await state.update_data(premium_only=cb.data.endswith(':1'))
    await cb.answer()
    await _ask_cover(cb.message, state)


async def _ask_cover(msg: Message, state: FSMContext):
    await state.set_state(Upload.cover)
    await msg.answer('🖼️ Send the <b>cover image</b> (as a photo), or skip:', reply_markup=_kb(('⏭️ Skip cover', 'upcover:skip'), _cancel_row()))


@router.callback_query(Upload.cover, F.data == 'upcover:skip')
async def cover_skip(cb: CallbackQuery, state: FSMContext):
    await state.update_data(cover=None)
    await state.set_state(Upload.file)
    await cb.message.answer('📎 Now send the <b>file</b> (PDF, ZIP, script… send it as a <b>File/Document</b>).\nFor a text-only product, just type or paste the text.')
    await cb.answer()


@router.message(Upload.cover, F.photo)
async def cover_photo(msg: Message, state: FSMContext):
    await state.update_data(cover=msg.photo[-1].file_id)
    await state.set_state(Upload.file)
    await msg.answer('✅ Cover saved.\n\n📎 Now send the <b>file</b> (PDF, ZIP, script… send it as a <b>File/Document</b>).\nFor a text-only product, just type or paste the text.')


@router.message(Upload.cover)
async def cover_invalid(msg: Message, state: FSMContext):
    if await escaped(msg, state):
        return
    await msg.answer('Please send the cover as a photo, or tap ⏭️ Skip cover.')


@router.message(Upload.file)
async def step_file(msg: Message, state: FSMContext):
    if msg.document:
        ctype, content = 'file', msg.document.file_id
    elif msg.text:
        if await escaped(msg, state):
            return
        ctype, content = 'text', msg.text
    elif msg.video or msg.audio or msg.photo or msg.voice:
        await msg.answer('Please send it as a <b>File/Document</b> (attach menu → File), not as media, so it downloads exactly as-is.')
        return
    else:
        await msg.answer('Send the file as a document, or paste the text.')
        return
    await state.update_data(ctype=ctype, content=content)
    await state.set_state(Upload.confirm)
    d = await state.get_data()
    kb = _kb(('✅ Publish' if d['mode'] == 'admin' else '✅ Submit for review', 'upgo'), _cancel_row())
    if d.get('cover'):
        await msg.answer_photo(d['cover'], caption='👀 <b>Preview</b>\n\n' + _preview_text(d, 450), reply_markup=kb)
    else:
        await msg.answer('👀 <b>Preview</b>\n\n' + _preview_text(d), reply_markup=kb)


@router.callback_query(Upload.confirm, F.data == 'upgo')
async def publish(cb: CallbackQuery, state: FSMContext, db, is_admin):
    d = await state.get_data()
    if not d or 'content' not in d:
        await cb.answer('Session expired. Start again.', show_alert=True)
        await state.clear()
        return
    mode = d['mode']
    # Re-check permission at the moment of publishing.
    if mode == 'admin' and not is_admin:
        await cb.answer('🚫 Admins only.', show_alert=True)
        await state.clear()
        return
    if mode == 'seller' and db.seller_status(cb.from_user.id) != 'approved':
        await cb.answer('⭐ Premium is required to sell.', show_alert=True)
        await state.clear()
        return
    pid = db.add_product(
        d['category'], d['name'], d['desc'], d['price'], d['ctype'], d['content'],
        premium_only=bool(d.get('premium_only')),
        seller_id=(cb.from_user.id if mode == 'seller' or (mode == 'admin' and MONOTECH_USER_ID > 0 and cb.from_user.id == MONOTECH_USER_ID) else None),
        status='approved' if mode == 'admin' else 'pending',
        stars_price=int(d.get('stars', 0)),
        author=d.get('author', ''), chapters=int(d.get('chapters', 0)),
        cover_file_id=d.get('cover'))
    await state.clear()
    if mode == 'admin':
        done = f'✅ Product <b>#{pid}</b> published. It is live in the Store now.'
    else:
        done = f'✅ Product <b>#{pid}</b> submitted. It goes live as soon as the admin approves it.'
        for oid in OWNER_IDS:
            try:
                await cb.bot.send_message(oid, f"🎫 New seller product pending: #{pid} <b>{html.escape(d['name'])}</b>\nOpen 🛠️ Admin → 🎫 Pending Products.")
            except Exception:
                pass
    await cb.message.answer(done)
    await cb.answer()
