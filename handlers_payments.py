import html
import time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import (COIN_PURCHASE_PRICE_NGN, PREMIUM_PAYMENT_ACCOUNT, PREMIUM_PAYMENT_NAME, PREMIUM_PAYMENT_PROVIDER,
                    COIN_PACKS, PREMIUM_COIN_PACKS, ADMIN_CONTACT_URL, OWNER_IDS)
from states import BuyCoins, PaymentProof
from flowutil import escaped

router = Router()


def payment_block(amount_ngn: int) -> str:
    return (f"Pay the required amount to this account:\n"
            f"🏦 Bank name: <b>{html.escape(PREMIUM_PAYMENT_PROVIDER)}</b>\n"
            f"🔢 Account number: <code>{PREMIUM_PAYMENT_ACCOUNT}</code>\n"
            f"👤 Account name: <b>{html.escape(PREMIUM_PAYMENT_NAME)}</b>\n\n"
            f"💵 Required amount to be paid: <b>₦{amount_ngn:,}</b>\n\n"
            f"After paying, send your <b>payment screenshot in this bot chat</b> so the admin can review your request. Thanks! 🙏")


def dm_kb():
    b = InlineKeyboardBuilder()
    b.button(text='💬 Contact Admin for help', url=ADMIN_CONTACT_URL)
    return b.as_markup()


@router.message(F.text == '💳 Buy Coins')
async def buy_coins(msg: Message, db, is_admin):
    if is_admin:
        await msg.answer('🛠️ Admins don\'t buy coins. Use <b>🪙 Credit Coins</b> in the Admin panel.')
        return
    premium = db.premium_info(msg.from_user.id)['active']
    packs = PREMIUM_COIN_PACKS if premium else COIN_PACKS
    b = InlineKeyboardBuilder()
    for coins, bonus in packs.items():
        b.button(text=f'{coins:,} coins (+{bonus} bonus) — ₦{coins * COIN_PURCHASE_PRICE_NGN:,}', callback_data=f'cbuy:{coins}')
    b.button(text='✏️ Other amount', callback_data='cbuy:custom')
    b.adjust(1)
    await msg.answer(f'💳 <b>Buy Coins</b>\n\nPrice: <b>1 coin = ₦{COIN_PURCHASE_PRICE_NGN}</b>\n\nPick a pack, or choose <b>Other amount</b> and I will calculate the total for you.',
                     reply_markup=b.as_markup())


async def _show_invoice(target: Message, user, db, state: FSMContext, coins: int):
    premium = db.premium_info(user.id)['active']
    bonus = (PREMIUM_COIN_PACKS if premium else COIN_PACKS).get(coins, 0)
    amount = coins * COIN_PURCHASE_PRICE_NGN
    request_id = db.create_manual_payment_request(user.id, 'coins', amount, coins, bonus)
    if not request_id:
        await target.answer('⏳ You already have a pending payment request, or your account cannot create one. Please contact the admin if you need help.')
        return
    await state.set_state(PaymentProof.upload)
    await state.update_data(payment_request_id=request_id)
    bonus_line = f'🎁 Bonus: <b>+{bonus:,}</b> (added once payment is confirmed)\n' if bonus else ''
    await target.answer(f'🧾 <b>Payment request #{request_id}</b>\nBuy <b>{coins:,} coins</b>\n{bonus_line}\n' + payment_block(amount) + '\n\n📎 <b>Now send your payment screenshot here in this bot chat.</b> Your request will only be sent to the admin after the proof is attached.', reply_markup=dm_kb())


@router.callback_query(F.data.startswith('cbuy:'))
async def coin_pack(cb: CallbackQuery, db, state: FSMContext, is_admin):
    if is_admin:
        await cb.answer('Admins don\'t buy coins.', show_alert=True)
        return
    raw = cb.data.split(':')[1]
    if raw == 'custom':
        await state.set_state(BuyCoins.amount)
        await cb.message.answer('✏️ How many coins do you want to buy? Send a number (e.g. 300).\nSend /cancel to stop.')
        await cb.answer()
        return
    await cb.answer()
    await _show_invoice(cb.message, cb.from_user, db, state, int(raw))


@router.message(BuyCoins.amount)
async def custom_amount(msg: Message, state: FSMContext, db):
    if await escaped(msg, state):
        return
    t = (msg.text or '').strip().replace(',', '')
    if not t.isdigit() or not 0 < int(t) <= 1_000_000:
        await msg.answer('Send a whole number of coins, like 300.')
        return
    await state.clear()
    await _show_invoice(msg, msg.from_user, db, state, int(t))


@router.message(PaymentProof.upload, F.photo)
async def manual_payment_photo(msg: Message, state: FSMContext, db):
    data = await state.get_data()
    request_id = data.get('payment_request_id')
    result = db.attach_manual_payment_proof(request_id, msg.from_user.id, msg.photo[-1].file_id, 'photo', msg.photo[-1].file_unique_id) if request_id else {'ok': False, 'reason': 'request_unavailable'}
    if not result.get('ok'):
        if result.get('reason') == 'duplicate_proof':
            await msg.answer('⚠️ This screenshot has already been used for another payment request. Please send the correct, unique payment proof.')
        else:
            await msg.answer('⚠️ I could not attach this screenshot to your request. Please contact support.')
        return
    await state.clear()
    await _notify_payment_proof(msg, db, request_id, result['request'], msg.photo[-1].file_id, 'photo')


@router.message(PaymentProof.upload, F.document)
async def manual_payment_document(msg: Message, state: FSMContext, db):
    data = await state.get_data()
    request_id = data.get('payment_request_id')
    doc = msg.document
    result = db.attach_manual_payment_proof(request_id, msg.from_user.id, doc.file_id, 'document', doc.file_unique_id) if request_id else {'ok': False, 'reason': 'request_unavailable'}
    if not result.get('ok'):
        if result.get('reason') == 'duplicate_proof':
            await msg.answer('⚠️ This file has already been used for another payment request. Please send unique proof.')
        else:
            await msg.answer('⚠️ I could not attach this file to your request. Please contact support.')
        return
    await state.clear()
    await _notify_payment_proof(msg, db, request_id, result['request'], doc.file_id, 'document')


async def _notify_payment_proof(msg: Message, db, request_id, req, file_id, proof_type):
    user = db.get_user(msg.from_user.id) or {}
    b = InlineKeyboardBuilder()
    b.button(text=f'✅ Confirm payment #{request_id}', callback_data=f'qpay:ok:{request_id}')
    b.button(text='❌ Reject request', callback_data=f'qpay:no:{request_id}')
    b.adjust(1)
    kind = 'Coin purchase' if req['request_type'] == 'coins' else 'Premium purchase'
    if req['request_type'] == 'coins':
        details = f"Coins: {req['base_coins']:,} (+{req['bonus_coins']:,} bonus)"
    else:
        days = int(req['plan_days'])
        duration = 'Lifetime' if days == 0 else ('1 year' if days == 365 else f'{days} days')
        details = f'Plan: {duration}'
    await msg.answer(f'⏳ Proof received for request #{request_id}. An admin will verify the payment and review it.')
    from config import OWNER_IDS
    for oid in OWNER_IDS:
        try:
            await msg.bot.send_message(oid, f"💳 <b>{kind} request #{request_id}</b>\nUser: {html.escape(user.get('first_name') or 'User')} (@{html.escape(user.get('username') or '—')}) · <code>{msg.from_user.id}</code>\n{details}\nAmount due: <b>₦{req['amount_ngn']:,}</b>\n\nVerify the actual payment in your account before approving.", reply_markup=b.as_markup())
            if proof_type == 'photo': await msg.bot.send_photo(oid, file_id, caption=f'Payment proof for request #{request_id}')
            else: await msg.bot.send_document(oid, file_id, caption=f'Payment proof for request #{request_id}')
        except Exception:
            pass

@router.pre_checkout_query()
async def precheckout(q: PreCheckoutQuery): await q.answer(ok=True)


@router.message(F.successful_payment)
async def paid_product(msg: Message, db):
    sp = msg.successful_payment; payload = sp.invoice_payload or ''
    if not payload.startswith('product:'): await msg.answer('⚠️ Unknown payment payload. Contact support.'); return
    try: _, pid, expected = payload.split(':', 2); pid = int(pid); expected = int(expected)
    except (ValueError, TypeError): await msg.answer('⚠️ Invalid payment payload. Contact support.'); return
    if int(sp.total_amount) != expected: await msg.answer('⚠️ Payment amount mismatch. Contact support.'); return
    from config import SELLER_COMMISSION
    res = db.star_product_purchase(msg.from_user.id, pid, sp.telegram_payment_charge_id, sp.total_amount, SELLER_COMMISSION)
    if res.get('ok'): await msg.answer(f'✅ Purchased with {sp.total_amount} Telegram Stars. The product is now in your Library.')
    elif res.get('reason') == 'duplicate': await msg.answer('⚠️ This Stars payment was already processed.')
    else: await msg.answer('⚠️ Payment was received but the product could not be fulfilled. Contact support immediately.')
