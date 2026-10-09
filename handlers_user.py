import html
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import REFUND_WINDOW_MIN_HOURS, REFUND_WINDOW_MAX_HOURS, REFUND_COOLDOWN_DAYS, REFERRAL_REWARD_REF, REFERRAL_REWARD_NEW, REFERRAL_DAILY_CAP, PREMIUM_PLANS, PREMIUM_PAYMENT_ACCOUNT, PREMIUM_PAYMENT_NAME, PREMIUM_PAYMENT_PROVIDER, ADMIN_IDS, OWNER_IDS, COIN_PURCHASE_PRICE_NGN, ADMIN_CONTACT_URL
from states import RedeemFlow, RefundFlow, PremiumPurchase, PaymentProof
from keyboards import main_menu, categories_kb, product_kb, rate_kb, premium_kb
from flowutil import escaped
from handlers_payments import payment_block, dm_kb

router=Router()


async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None):
    """edit_text fails on photo messages (product covers). Replace the message instead."""
    if getattr(cb.message, 'photo', None):
        try: await cb.message.delete()
        except Exception: pass
        await cb.message.answer(text, reply_markup=reply_markup)
    else:
        await cb.message.edit_text(text, reply_markup=reply_markup)


@router.message(Command('myid'))
async def myid(msg: Message, db, is_admin, is_owner):
    role = 'Owner (main admin)' if is_owner else ('Co-admin' if is_admin else 'Normal user')
    extra = f"\n🗄️ Database ID: <code>{db.instance_id()}</code> (if this changes between calls, TWO copies of the bot are running)" if is_admin else ''
    await msg.answer(f"🆔 Your Telegram ID: <code>{msg.from_user.id}</code>\n🔑 Role in this bot: <b>{role}</b>{extra}")

@router.message(CommandStart())
async def start(msg: Message, db, user_row, is_admin):
    db.claim_referral(msg.from_user.id, REFERRAL_REWARD_REF, REFERRAL_REWARD_NEW, REFERRAL_DAILY_CAP)
    seller=db.seller_status(msg.from_user.id)=='approved'
    fresh=db.get_user(msg.from_user.id)
    await msg.answer(f"👋 Welcome, <b>{msg.from_user.first_name}</b>!\n💰 Balance: <b>{fresh['coins']}</b> coins", reply_markup=main_menu(seller,is_admin))

@router.message(F.text=='🛍️ Store')
async def store(msg: Message, db): await msg.answer('🛍️ Choose a category:',reply_markup=categories_kb(db.get_categories()))
@router.callback_query(F.data=='store')
async def store_cb(cb: CallbackQuery, db): await safe_edit(cb,'🛍️ Choose a category:',categories_kb(db.get_categories())); await cb.answer()

@router.callback_query(F.data.startswith('cat:'))
async def list_products(cb: CallbackQuery, db):
    cid=int(cb.data.split(':')[1]); products=db.get_products(cid)
    if not products: await cb.answer('No products here yet.',show_alert=True); return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b=InlineKeyboardBuilder()
    for p in products: b.button(text=f"{p['name'][:45]} — {p['price']}💰 ⭐{p['rating_avg']}",callback_data=f"prod:{p['id']}")
    b.button(text='⬅️ Back',callback_data='store'); b.adjust(1)
    await cb.message.edit_text('📦 Products:',reply_markup=b.as_markup()); await cb.answer()

@router.callback_query(F.data.startswith('prod:'))
async def product_detail(cb: CallbackQuery, db, is_admin):
    p=db.get_product(int(cb.data.split(':')[1]))
    if not p or not p['active'] or p['status']!='approved': await cb.answer('Product unavailable.',show_alert=True); return
    own=bool(is_admin or (p['seller_id'] and int(p['seller_id'])==cb.from_user.id))   # admins & the product's own seller download free
    owned=db.already_purchased(cb.from_user.id,p['id'])
    premium='👑 Premium only\n' if p['premium_only'] else ''
    star_line=f"⭐ Direct Stars price: <b>{p['stars_price']}⭐</b>\n" if p.get('stars_price') else ''
    author=f"✍️ Author: {html.escape(p['author'])}\n" if p.get('author') else ''
    chapters=f"📖 Chapters: {p['chapters']}\n" if p.get('chapters') else ''
    has_cover=bool(p.get('cover_file_id'))
    desc=p['description'] if not has_cover or len(p['description'])<=450 else p['description'][:449]+'…'   # captions max 1024 chars
    text=f"<b>{html.escape(p['name'])}</b>\n\n{author}{chapters}\n{html.escape(desc)}\n\n💰 {p['price']} coins\n{star_line}⭐ {p['rating_avg']} ({p['rating_count']} ratings)\n{premium}"
    kb=product_kb(p,owned,own)
    if has_cover:
        try: await cb.message.delete()
        except Exception: pass
        await cb.message.answer_photo(p['cover_file_id'],caption=text,reply_markup=kb)
    else:
        await safe_edit(cb,text,kb)
    await cb.answer()

@router.callback_query(F.data.startswith('buy:'))
async def buy(cb: CallbackQuery, db):
    from config import SELLER_COMMISSION
    pid=int(cb.data.split(':')[1]); res=db.purchase(cb.from_user.id,pid,SELLER_COMMISSION)
    if not res['ok']:
        reasons={'unavailable':'❌ Not available.','self':'❌ You cannot buy your own product.','owned':'❌ You already own this.','premium':'⭐ Premium members only.','funds':f"💸 Need {res.get('price')} coins; you have {res.get('balance')}."}
        await cb.answer(reasons.get(res['reason'], '🔒 This product cannot be repurchased until 10 days after an approved refund.' if res['reason']=='refund_cooldown' else '❌ Failed.'),show_alert=True); return
    p=db.get_product(pid); await cb.answer('✅ Purchased!',show_alert=True)
    await safe_edit(cb,f"✅ Purchased <b>{html.escape(p['name'])}</b>\nNew balance: <b>{res['balance']}</b>",product_kb(p,True))

@router.callback_query(F.data.startswith('starbuy:'))
async def star_buy(cb: CallbackQuery, db):
    from aiogram.types import LabeledPrice
    pid=int(cb.data.split(':')[1]); p=db.get_product(pid)
    if not p or not p['active'] or p['status']!='approved' or not p.get('stars_price'): await cb.answer('Stars purchase unavailable.',show_alert=True); return
    if db.already_purchased(cb.from_user.id,pid): await cb.answer('You already own this product.',show_alert=True); return
    if p['premium_only'] and not db.premium_info(cb.from_user.id)['active']: await cb.answer('⭐ Premium members only.',show_alert=True); return
    await cb.message.answer_invoice(title=p['name'][:32],description=p['description'][:255],payload=f'product:{pid}:{p["stars_price"]}',currency='XTR',prices=[LabeledPrice(label=p['name'][:32],amount=int(p['stars_price']))])
    await cb.answer()

@router.callback_query(F.data.startswith('rate:'))
async def rate_menu(cb: CallbackQuery, db):
    pid=int(cb.data.split(':')[1])
    if not db.already_purchased(cb.from_user.id,pid): await cb.answer('Buy first.',show_alert=True); return
    await safe_edit(cb,'⭐ Rate this product:',rate_kb(pid))
@router.callback_query(F.data.startswith('stars:'))
async def rate_set(cb: CallbackQuery, db):
    _,pid,n=cb.data.split(':'); ok=db.rate(cb.from_user.id,int(pid),int(n)); await cb.answer('Thanks!' if ok else 'Failed.',show_alert=True)

@router.callback_query(F.data.startswith('ref:'))
async def refund_start(cb: CallbackQuery, db, state: FSMContext):
    pid=int(cb.data.split(':')[1])
    if not db.refund_eligible(cb.from_user.id,pid,REFUND_WINDOW_MAX_HOURS): await cb.answer('Refund not available.',show_alert=True); return
    await state.set_state(RefundFlow.reason); await state.update_data(pid=pid); await safe_edit(cb,'✍️ Clearly explain why you want a refund. Requests are only accepted 2–5 hours after purchase. If approved, the product is locked for 10 days before it can be bought again.')
@router.message(RefundFlow.reason)
async def refund_reason(msg: Message, db, state: FSMContext):
    data=await state.get_data(); reason=(msg.text or '').strip();
    if len(reason)<15: await msg.answer('Please explain the reason clearly (at least 15 characters).'); return
    res=db.request_refund(msg.from_user.id,data['pid'],reason,REFUND_WINDOW_MAX_HOURS); await state.clear()
    await msg.answer('✅ Refund requested.' if res.get('ok') else f"❌ {res.get('reason','Failed')}")

@router.message(F.text=='📚 Library')
async def library(msg: Message, db):
    items=db.library(msg.from_user.id)
    if not items: await msg.answer('📚 Your library is empty.'); return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b=InlineKeyboardBuilder()
    for it in items: b.button(text=it['name'][:50],callback_data=f"get:{it['id']}")
    b.adjust(1); await msg.answer('📚 Your library:',reply_markup=b.as_markup())
@router.callback_query(F.data.startswith('get:'))
async def deliver(cb: CallbackQuery, db, is_admin):
    pid=int(cb.data.split(':')[1]); p=db.get_product(pid)
    if not p: await cb.answer('Missing product.',show_alert=True); return
    allowed=db.already_purchased(cb.from_user.id,pid) or is_admin or (p['seller_id'] and int(p['seller_id'])==cb.from_user.id)
    if not allowed: await cb.answer('Not yours.',show_alert=True); return
    if p['content_type']=='file': await cb.message.answer_document(p['content'],caption=f"📥 {html.escape(p['name'])}")
    else: await cb.message.answer(f"<b>{html.escape(p['name'])}</b>\n\n{html.escape(p['content'])}")
    await cb.answer()

@router.callback_query(F.data.startswith('wish:'))
async def wishlist_toggle(cb: CallbackQuery, db):
    pid=int(cb.data.split(':')[1]); added=db.toggle_wishlist(cb.from_user.id,pid)
    await cb.answer('❤️ Added to wishlist' if added else 'Wishlist entry removed',show_alert=True)

@router.message(F.text=='❤️ Wishlist')
async def wishlist_view(msg: Message, db):
    items=db.wishlist(msg.from_user.id)
    if not items: await msg.answer('❤️ Your wishlist is empty. Open a product and tap Add/Remove Wishlist.'); return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b=InlineKeyboardBuilder()
    for p in items: b.button(text=f"{p['name'][:35]} · {p['price']} coins",callback_data=f"prod:{p['id']}")
    b.adjust(1); await msg.answer('❤️ Your wishlist (price-drop notifications can be sent when a seller/admin updates a listed price):',reply_markup=b.as_markup())

@router.message(F.text=='🎁 Daily Check-in')
async def daily_checkin(msg: Message, db):
    result=db.daily_checkin(msg.from_user.id)
    if result['ok']: await msg.answer(f"🎁 Check-in complete!\n🔥 Streak: {result['streak']} day(s)\n🪙 Reward: +{result['reward']} spend-only coins. These coins cannot be withdrawn.")
    else: await msg.answer(f"✅ You already checked in today. Current streak: {result['streak']} day(s). Come back tomorrow!")

@router.message(F.text=='💰 Balance')
async def balance(msg: Message, db):
    u=db.get_user(msg.from_user.id); txs=db.recent_transactions(msg.from_user.id,5)
    lines=[f"• {t['amount']:+d} — {t['kind']} ({t['note']})" for t in txs] or ['No transactions.']
    await msg.answer(f"💰 <b>{u['coins']}</b> coins\n\n"+'\n'.join(lines))
@router.message(F.text=='🔗 Refer')
async def refer(msg: Message, db):
    bot=await msg.bot.get_me(); await msg.answer(f"🔗 Invite: https://t.me/{bot.username}?start=ref_{msg.from_user.id}\nReferrals: <b>{db.referral_count(msg.from_user.id)}</b>")

@router.message(F.text=='🎟️ Redeem')
async def redeem_start(msg: Message,state:FSMContext): await state.set_state(RedeemFlow.code); await msg.answer('🎟️ <b>Redeem code</b>\n\nEnter your code to redeem coins:\n(Send /cancel to stop.)')
@router.message(RedeemFlow.code)
async def redeem_run(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    res=db.redeem(msg.text or '',msg.from_user.id); await state.clear()
    replies={'not_found':'❌ Invalid code.','expired':'❌ Code expired or fully used.','already_used':'❌ You already used this code.','no_user':'❌ Register first.'}
    await msg.answer(f'✅ +{res} coins!' if isinstance(res,int) else replies.get(res,'❌ Failed.'))

@router.message(F.text=='⭐ Premium')
@router.message(Command('premium'))
async def premium(msg: Message,db):
    info=db.premium_info(msg.from_user.id)
    if info['lifetime']: status='♾️ Lifetime access'
    elif info['active']: status=f"✅ Active until <b>{info['until']}</b> · {info['days_left']} day(s) left"
    elif info['until']: status=f"⚠️ Expired · seller grace until <b>{info['grace_until']}</b>"
    else: status='❌ Not active'
    await msg.answer(f"⭐ <b>SHΔDOWBORNE Premium</b>\n\n{status}\n\nPremium is purchased separately by manual payment — it is <b>not sold for coins</b>.\n\nChoose your access:", reply_markup=premium_kb([(30,2500),(60,5000),(90,7500),(365,14500),(0,25000)]))

@router.callback_query(F.data=='premium_plans')
async def premium_plans(cb:CallbackQuery,db):
    await cb.message.edit_text('⭐ <b>Premium Plans</b>\n\nChoose the duration you want:',reply_markup=premium_kb([(30,2500),(60,5000),(90,7500),(365,14500),(0,25000)])); await cb.answer()

@router.callback_query(F.data.startswith('prem:'))
async def premium_choose(cb:CallbackQuery,state:FSMContext,db):
    raw=cb.data.split(':')[1]
    if raw=='renew':
        await cb.message.edit_text('🔄 <b>Renew Premium</b>\n\nYour new Premium time is added to any time still remaining. Choose a plan:',reply_markup=premium_kb([(30,2500),(60,5000),(90,7500),(365,14500),(0,25000)])); await cb.answer(); return
    days=int(raw); price=PREMIUM_PLANS.get(days)
    if price is None: await cb.answer('Invalid plan.',show_alert=True); return
    duration='Lifetime' if days==0 else ('1 year' if days==365 else f'{days} days')
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b=InlineKeyboardBuilder(); b.button(text='💬 Contact Admin for help',url=ADMIN_CONTACT_URL); b.button(text='⬅️ Premium Plans',callback_data='premium_plans'); b.adjust(1)
    request_id=db.create_manual_payment_request(cb.from_user.id,'premium',price,plan_days=days)
    if not request_id:
        await cb.answer('You already have a pending payment request. Contact the admin if you need help.',show_alert=True)
        return
    await state.set_state(PaymentProof.upload)
    await state.update_data(payment_request_id=request_id)
    await cb.message.edit_text(f"⭐ <b>Premium — {duration}</b>\n\nPayment request: <b>#{request_id}</b>\n\n"+payment_block(price),reply_markup=b.as_markup()); await cb.answer()

@router.message(PremiumPurchase.proof,F.photo)
async def premium_proof(msg:Message,state:FSMContext,db):
    data=await state.get_data(); rid=db.create_premium_request(msg.from_user.id,data['plan_days'],data['amount_ngn'],msg.photo[-1].file_id,'photo'); await state.clear()
    if not rid: await msg.answer('⚠️ A Premium request is already pending. Please wait for admin review.'); return
    duration='Lifetime' if data['plan_days']==0 else ('1 year' if data['plan_days']==365 else f"{data['plan_days']} days")
    await msg.answer(f"⏳ <b>Premium request #{rid} is pending.</b>\n\nPlan: {duration}\nAmount: ₦{data['amount_ngn']:,}\n\nAn admin will verify the screenshot and notify you when it is approved or rejected.")
    for admin_id in OWNER_IDS:
        try:
            await msg.bot.send_message(admin_id, f"⭐ <b>New Premium request #{rid}</b>\nUser: @{msg.from_user.username or 'no_username'} (<code>{msg.from_user.id}</code>)\nPlan: {duration}\nAmount: ₦{data['amount_ngn']:,}\nOpen Admin → ⭐ Premium Requests to review.")
            await msg.bot.send_photo(admin_id, msg.photo[-1].file_id, caption=f"Premium payment proof #{rid}")
        except Exception:
            pass

@router.message(PremiumPurchase.proof)
async def premium_proof_invalid(msg:Message): await msg.answer('📸 Please send the payment screenshot as an image/photo.')

@router.message(F.text=='👤 Profile')
async def profile(msg:Message,db):
    u=db.get_user(msg.from_user.id); info=db.premium_info(msg.from_user.id); status=db.seller_status(msg.from_user.id)
    if status=='approved': seller=f"👨‍💼 Seller: ✅ Verified\n🆔 Seller ID: <code>{db.seller_code(msg.from_user.id)}</code>\n"
    elif status=='suspended': seller="👨‍💼 Seller: 🔒 Suspended (renew Premium)\n"
    else: seller="👨‍💼 Seller: Not a seller yet\n"
    await msg.answer(f"👤 <b>{html.escape(u['first_name'] or 'User')}</b> (@{html.escape(u['username']) if u['username'] else '—'})\n💰 {u['coins']} coins\n🛍️ Purchases: {db.purchase_count(msg.from_user.id)}\n⭐ Premium: {'Lifetime' if info['lifetime'] else ('Yes' if info['active'] else 'No')}\n{seller}🔗 Referrals: {db.referral_count(msg.from_user.id)}")

@router.message(F.text=='🆘 Support')
@router.message(Command('paysupport'))
async def support(msg:Message):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b=InlineKeyboardBuilder(); b.button(text='💬 Message Admin',url=ADMIN_CONTACT_URL)
    await msg.answer('🆘 Need help with a payment, product or your account? Message the admin directly.',reply_markup=b.as_markup())
