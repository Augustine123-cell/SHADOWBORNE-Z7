import asyncio
import html
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from middlewares import admin_only, owner_only
from keyboards import admin_menu, review_kb
from flowutil import escaped
from states import Broadcast, AdminCoins, PremiumReject, GrantPremium, AdminBan, CreateCode
from config import PAYOUT_MIN_DAYS, PAYOUT_MAX_DAYS, PREMIUM_PLANS, ADMIN_IDS, BROADCAST_DELAY_SECONDS

router=Router()


def _plan_label(days): return '♾️ Lifetime' if days == 0 else ('1 year' if days == 365 else f'{days} days')
def _who(u): return f"{html.escape(u['first_name'] or 'User')} (@{html.escape(u['username']) if u.get('username') else '—'}) · <code>{u['user_id']}</code>"


# ---------------- Admin home (owner + co-admin) ----------------
@router.message(Command('admin'))
@router.message(F.text=='🛠️ Admin')
@admin_only
async def admin_home(msg:Message,state:FSMContext,is_owner):
    await state.clear()
    await msg.answer('🛠️ <b>SHΔDOWBORNE ⸸ MART Admin</b>' + ('' if is_owner else '\n\n<i>Co-admin access: upload, product review, delete product.</i>'),reply_markup=admin_menu(is_owner))

@router.callback_query(F.data=='admin:dash')
@owner_only
async def dash(cb:CallbackQuery,db):
    d=db.dashboard(); await cb.message.edit_text(f"📊 <b>Dashboard</b>\n👥 Users: {d['users']} | Active 24h: {d['active']}\n🚫 Banned: {d['banned']} | ⭐ Premium: {d['premium']}\n🏪 Products: {d['products']} | Pending: {d['pending_products']}\n💰 Sales today: {d['sales_today']} | Revenue: {d['rev_today']} coins\n💸 Pending refunds: {d['pending_refunds']}\n💳 Pending coin requests: {d['pending_requests']}\n⭐ Product Stars: {d['stars']} | Seller share: {d['stars_seller']} | Admin share: {d['stars_admin']}\n📈 7-day sales: {d['series']}",reply_markup=admin_menu(True)); await cb.answer()

@router.callback_query(F.data=='admin:prod')
@admin_only
async def pending_prods(cb:CallbackQuery,db):
    rows=db.pending_products()
    if not rows: await cb.answer('No pending products.',show_alert=True); return
    for p in rows:
        await cb.message.answer(f"#{p['id']} <b>{p['name']}</b> — {p['price']}💰\nSeller: @{p['username'] or p['first_name']}\n{p['description']}",reply_markup=review_kb('aprod',p['id']))
    await cb.answer()
@router.callback_query(F.data.startswith('aprod:'))
@admin_only
async def aprod(cb:CallbackQuery,db):
    _,action,pid=cb.data.split(':'); ok=db.set_product_status(int(pid),'approved' if action=='ok' else 'rejected'); await cb.message.edit_text(f"Product #{pid}: {'approved' if action=='ok' else 'rejected'}" if ok else 'Product no longer exists.'); await cb.answer()

@router.callback_query(F.data=='admin:req')
@owner_only
async def pending_reqs(cb:CallbackQuery,db):
    rows=db.get_pending_requests()
    if not rows: await cb.answer('No pending coin requests.',show_alert=True); return
    for r in rows:
        await cb.message.answer(f"#{r['id']} @{r['username'] or 'no_username'} — {r['coins']}💰\nAmount due: ₦{r.get('amount_ngn',0):,}\nRef: {r['payment_reference']}",reply_markup=review_kb('areq',r['id']))
        if r['proof_file_id']:
            try: await cb.message.answer_photo(r['proof_file_id'])
            except Exception: pass
    await cb.answer()
@router.callback_query(F.data.startswith('areq:'))
@owner_only
async def areq(cb:CallbackQuery,db):
    _,action,rid=cb.data.split(':'); res=db.review_request(int(rid),action=='ok'); await cb.message.edit_text(f"Request #{rid}: {'approved' if action=='ok' else 'rejected'}" if res else 'Request already reviewed.'); await cb.answer()

@router.callback_query(F.data=='admin:ref')
@owner_only
async def pending_refunds(cb:CallbackQuery,db):
    rows=db.pending_refunds()
    if not rows: await cb.answer('No pending refunds.',show_alert=True); return
    for r in rows: await cb.message.answer(f"#{r['id']} {r['product_name']} — {r['price']}💰\nBy @{r['username'] or 'unknown'}\nReason: {r['reason']}",reply_markup=review_kb('aref',r['id']))
    await cb.answer()
@router.callback_query(F.data.startswith('aref:'))
@owner_only
async def aref(cb:CallbackQuery,db):
    _,action,rid=cb.data.split(':'); res=db.review_refund(int(rid),action=='ok'); await cb.message.edit_text(f"Refund #{rid}: {'approved' if action=='ok' else 'rejected'}" if res else 'Refund already reviewed.'); await cb.answer()

@router.callback_query(F.data=='admin:sel')
@owner_only
async def pending_sellers(cb:CallbackQuery,db):
    users=[u for u in db.get_all_users() if u['seller_status']=='pending']
    if not users: await cb.answer('No pending sellers.',show_alert=True); return
    for u in users: await cb.message.answer(f"@{u['username'] or 'no_username'} (id {u['user_id']}) wants to sell.",reply_markup=review_kb('asel',u['user_id']))
    await cb.answer()
@router.callback_query(F.data.startswith('asel:'))
@owner_only
async def asel(cb:CallbackQuery,db):
    _,action,uid=cb.data.split(':'); uid=int(uid)
    if action=='ok' and not db.premium_info(uid)['active']:
        await cb.answer('Cannot approve: user must have active Premium.',show_alert=True); return
    db.set_seller_status(uid,'approved' if action=='ok' else 'none'); await cb.message.edit_text(f"Seller {uid}: {'approved' if action=='ok' else 'rejected'}"); await cb.answer()

@router.callback_query(F.data=='admin:premium')
@owner_only
async def premium_requests(cb:CallbackQuery,db):
    rows=db.pending_premium_requests()
    if not rows: await cb.answer('No pending Premium requests.',show_alert=True); return
    for r in rows:
        duration='Lifetime' if r['plan_days']==0 else ('1 year' if r['plan_days']==365 else f"{r['plan_days']} days")
        await cb.message.answer(f"⭐ <b>Premium Request #{r['id']}</b>\nUser: @{r['username'] or 'no_username'} (<code>{r['user_id']}</code>)\nPlan: <b>{duration}</b>\nAmount: <b>₦{r['amount_ngn']:,}</b>\nSeller status: <b>{r['seller_status']}</b>\nSeller ID: <code>{r['seller_code']}</code>",reply_markup=review_kb('aprem',r['id']))
        if r['proof_file_id']:
            try: await cb.message.answer_photo(r['proof_file_id'],caption=f"Premium request #{r['id']} payment proof")
            except Exception: pass
    await cb.answer()

@router.callback_query(F.data.startswith('aprem:ok:'))
@owner_only
async def premium_approve(cb:CallbackQuery,db):
    rid=int(cb.data.split(':')[2]); res=db.review_premium_request(rid,True)
    if not res: await cb.answer('Request already reviewed or unavailable.',show_alert=True); return
    duration='Lifetime' if res['plan_days']==0 else ('1 year' if res['plan_days']==365 else f"{res['plan_days']} days")
    until='Lifetime' if not res.get('premium_until') else res['premium_until']
    try: await cb.bot.send_message(res['user_id'],f"✅ <b>Premium approved!</b>\n\nPlan: {duration}\nPremium: <b>{until}</b>\n\nYour Seller access has also been restored automatically if you were previously a verified seller.")
    except Exception: pass
    await cb.message.edit_text(f'✅ Premium request #{rid} approved.'); await cb.answer()

@router.callback_query(F.data.startswith('aprem:no:'))
@owner_only
async def premium_reject_start(cb:CallbackQuery,state:FSMContext):
    rid=int(cb.data.split(':')[2]); await state.set_state(PremiumReject.reason); await state.update_data(premium_request_id=rid); await cb.message.edit_text(f'❌ <b>Reject Premium request #{rid}</b>\n\nSend the reason that will be shown to the user.'); await cb.answer()

@router.message(PremiumReject.reason)
@owner_only
async def premium_reject_reason(msg:Message,state:FSMContext,db):
    if await escaped(msg,state): return
    data=await state.get_data(); rid=int(data['premium_request_id']); reason=(msg.text or '').strip() or 'Payment proof could not be verified.'
    res=db.review_premium_request(rid,False,reason); await state.clear()
    if not res: await msg.answer('⚠️ Request already reviewed or unavailable.'); return
    try: await msg.bot.send_message(res['user_id'],f"❌ <b>Premium request #{rid} rejected.</b>\n\nReason: {reason}\n\nYou can submit a new request from /premium after making a valid payment.")
    except Exception: pass
    await msg.answer(f'❌ Premium request #{rid} rejected.')

@router.callback_query(F.data=='admin:withdrawals')
@owner_only
async def withdrawals(cb:CallbackQuery,db):
    rows=db.pending_seller_payouts()
    if not rows: await cb.answer('No pending seller withdrawals.',show_alert=True); return
    for r in rows:
        if r['payout_method']=='bank': dest=f"🏦 {r['bank_name']} | {r['account_number']} | {r['account_name']}"; net=f"₦{r['gross_ngn']*(1-r['fee_percent']/100):,.2f}"
        else: dest=f"₮ USDT TRC20 | {r['usdt_address']}"; net=f"{r['gross_usdt']*(1-r['fee_percent']/100):.6f} USDT"
        text=f"💸 <b>Withdrawal #{r['id']}</b>\nSeller: @{r['username'] or r['first_name']} (<code>{r['seller_id']}</code>)\nCoins: <b>{r['amount_coins']:,}</b>\nPayout: <b>{net}</b>\n{dest}\n\n⏳ Seller payout window: {PAYOUT_MIN_DAYS}–{PAYOUT_MAX_DAYS} days."
        b=InlineKeyboardBuilder(); b.button(text='❌ Reject',callback_data=f'pay:reject:{r["id"]}')
        if r['status']=='pending': b.button(text='✅ Approve',callback_data=f'pay:approve:{r["id"]}')
        if r['status']=='approved': b.button(text='💵 Mark Paid',callback_data=f'pay:paid:{r["id"]}')
        b.adjust(2); await cb.message.answer(text,reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data.startswith('pay:'))
@owner_only
async def payout_action(cb:CallbackQuery,db):
    _,action,pid=cb.data.split(':'); res=db.review_seller_payout(int(pid),action,cb.from_user.id,'')
    if not res: await cb.answer('Request is no longer actionable or seller lacks funds.',show_alert=True); return
    await cb.message.edit_text(f"Withdrawal #{pid}: {'marked paid' if action=='paid' else action}."); await cb.answer()

# ---------------- Active users ----------------
@router.callback_query(F.data.startswith('admin:active'))
@owner_only
async def active(cb:CallbackQuery,db):
    parts=cb.data.split(':'); hours=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 24
    users=db.get_all_users() if hours==0 else db.active_users(hours)
    label='all users' if hours==0 else ('last 24 hours' if hours==24 else f'last {hours//24} days')
    b=InlineKeyboardBuilder(); b.button(text='🕐 24h',callback_data='admin:active:24'); b.button(text='📅 7 days',callback_data='admin:active:168'); b.button(text='👥 All users',callback_data='admin:active:0'); b.adjust(3)
    if not users: await cb.message.answer(f'No users — {label}.',reply_markup=b.as_markup()); await cb.answer(); return
    lines=[f"{n}. {html.escape(u['first_name'] or '—')} | @{html.escape(u['username']) if u['username'] else '—'} | <code>{u['user_id']}</code>" for n,u in enumerate(users,1)]
    chunks=[]; cur=f'👥 <b>Users — {label}</b> ({len(users)})\n'
    for line in lines:
        if len(cur)+len(line)+1>3800: chunks.append(cur); cur=''
        cur+='\n'+line
    chunks.append(cur)
    for n,chunk in enumerate(chunks):
        await cb.message.answer(chunk,reply_markup=b.as_markup() if n==len(chunks)-1 else None)
    await cb.answer()


# ---------------- Credit coins (by ID or @username) ----------------
@router.callback_query(F.data=='admin:sendcoins')
@owner_only
async def sendcoins(cb:CallbackQuery,state:FSMContext):
    await state.set_state(AdminCoins.target)
    await cb.message.answer('🪙 <b>Credit coins</b>\n\nSend the user\'s Telegram <b>ID</b> or <b>@username</b>.\n(Send /cancel to stop.)'); await cb.answer()
@router.message(AdminCoins.target)
@owner_only
async def send_target(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    u=db.find_user(msg.text or '')
    if not u: await msg.answer('❌ User not found. They must open the bot and press /start first. Send another ID/@username, or /cancel.'); return
    await state.update_data(target=u['user_id']); await state.set_state(AdminCoins.amount)
    await msg.answer(f"🪙 Crediting {_who(u)}\n\nSend the amount of coins:")
@router.message(AdminCoins.amount)
@owner_only
async def send_amount(msg:Message,state:FSMContext):
    if await escaped(msg,state): return
    if not (msg.text or '').isdigit() or int(msg.text)<=0: await msg.answer('Enter a positive whole number.'); return
    await state.update_data(amount=int(msg.text)); await state.set_state(AdminCoins.note); await msg.answer('Optional note (or send - to skip):')
@router.message(AdminCoins.note)
@owner_only
async def send_note(msg:Message,state:FSMContext,db):
    if await escaped(msg,state): return
    data=await state.get_data(); note='' if (msg.text or '').strip()=='-' else (msg.text or '').strip(); ok=db.add_coins(data['target'],data['amount'],'admin_credit',note); await state.clear()
    await msg.answer(f"✅ {data['amount']:,} coins sent." if ok else '❌ Could not credit user.')
    if ok:
        try: await msg.bot.send_message(data['target'],f"🪙 You received <b>{data['amount']:,}</b> coins from the admin." + (f"\nNote: {html.escape(note)}" if note else ''))
        except Exception: pass


# ---------------- Ban / Unban (by ID or @username) ----------------
@router.callback_query(F.data=='admin:ban')
@owner_only
async def ban_menu(cb:CallbackQuery,state:FSMContext):
    await state.set_state(AdminBan.ban); await cb.message.answer('🚫 <b>Ban user</b>\n\nSend the Telegram <b>ID</b> or <b>@username</b> to ban.\n(Send /cancel to stop.)'); await cb.answer()
@router.message(AdminBan.ban)
@owner_only
async def ban_target(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    u=db.find_user(msg.text or '')
    if not u: await msg.answer('❌ User not found. Send another ID/@username, or /cancel.'); return
    if u['user_id'] in ADMIN_IDS: await msg.answer('❌ You cannot ban an admin.'); return
    db.set_banned(u['user_id'],True); await state.clear(); await msg.answer(f"🚫 Banned: {_who(u)}")
@router.callback_query(F.data=='admin:unban')
@owner_only
async def unban_menu(cb:CallbackQuery,state:FSMContext):
    await state.set_state(AdminBan.unban); await cb.message.answer('✅ <b>Unban user</b>\n\nSend the Telegram <b>ID</b> or <b>@username</b> to unban.\n(Send /cancel to stop.)'); await cb.answer()
@router.message(AdminBan.unban)
@owner_only
async def unban_target(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    u=db.find_user(msg.text or '')
    if not u: await msg.answer('❌ User not found. Send another ID/@username, or /cancel.'); return
    db.set_banned(u['user_id'],False); await state.clear(); await msg.answer(f"✅ Unbanned: {_who(u)}")


# ---------------- Grant Premium (OWNER ONLY — never the co-admin) ----------------
@router.callback_query(F.data=='admin:grant')
@owner_only
async def grant_start(cb:CallbackQuery,state:FSMContext):
    await state.set_state(GrantPremium.target)
    await cb.message.answer('⭐ <b>Grant Premium</b>\n\nSend the Telegram <b>ID</b> or <b>@username</b> of the user.\n(They must have opened the bot at least once. Send /cancel to stop.)'); await cb.answer()
@router.message(GrantPremium.target)
@owner_only
async def grant_target(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    u=db.find_user(msg.text or '')
    if not u: await msg.answer('❌ User not found. They must open the bot and press /start first. Send another ID/@username, or /cancel.'); return
    await state.update_data(target=u['user_id'])
    b=InlineKeyboardBuilder()
    for days in PREMIUM_PLANS: b.button(text=_plan_label(days),callback_data=f'gprem:{days}')
    b.adjust(2)
    await msg.answer(f"⭐ Grant Premium to {_who(u)}\n\nChoose how long:",reply_markup=b.as_markup())
@router.callback_query(GrantPremium.target,F.data.startswith('gprem:'))
@owner_only
async def grant_apply(cb:CallbackQuery,db,state:FSMContext):
    data=await state.get_data(); uid=data.get('target'); days=int(cb.data.split(':')[1])
    if uid is None or days not in PREMIUM_PLANS: await cb.answer('Start again.',show_alert=True); await state.clear(); return
    res=db.grant_premium_manual(uid,days); await state.clear()
    if not res: await cb.message.edit_text('❌ Could not grant Premium (user not found or banned).'); await cb.answer(); return
    until='Lifetime' if res['lifetime'] else res['until']
    await cb.message.edit_text(f"✅ Premium granted to <code>{uid}</code> — {_plan_label(days)}\nPremium until: <b>{until}</b>"); await cb.answer()
    try: await cb.bot.send_message(uid,f"⭐ <b>You are now a Premium member!</b>\n\nPlan: {_plan_label(days)}\n\nOpen <b>👨‍💼 Seller Panel</b> to start selling and uploading products.")
    except Exception: pass


@router.callback_query(F.data=='admin:delete')
@admin_only
async def delete_menu(cb:CallbackQuery,db):
    rows=db._all("SELECT id,name,price FROM products WHERE active=1 ORDER BY id DESC LIMIT 50")
    if not rows: await cb.answer('No active products.',show_alert=True); return
    b=InlineKeyboardBuilder()
    for p in rows: b.button(text=f"🗑️ #{p['id']} {p['name'][:35]}",callback_data=f"delprod:{p['id']}")
    b.adjust(1); await cb.message.edit_text('Select a product to deactivate:',reply_markup=b.as_markup()); await cb.answer()
@router.callback_query(F.data.startswith('delprod:'))
@admin_only
async def delete_product(cb:CallbackQuery,db,is_owner):
    pid=int(cb.data.split(':')[1]); ok=db.delete_product(pid); await cb.answer('Deleted.' if ok else 'Not found.',show_alert=True); await cb.message.edit_text('🗑️ Product deactivated.',reply_markup=admin_menu(is_owner))

# ---------------- Redeem codes (guided) ----------------
@router.callback_query(F.data=='admin:code')
@owner_only
async def make_code(cb:CallbackQuery,state:FSMContext):
    await state.set_state(CreateCode.coins)
    await cb.message.answer('🎟️ <b>Create redeem code</b>\n\nHow many <b>coins</b> should each user get from this code? Send a number.\n(Send /cancel to stop.)'); await cb.answer()
@router.message(CreateCode.coins)
@owner_only
async def code_coins(msg:Message,state:FSMContext):
    if await escaped(msg,state): return
    t=(msg.text or '').strip().replace(',','')
    if not t.isdigit() or not 0<int(t)<=10_000_000: await msg.answer('Send a whole number of coins, like 50.'); return
    await state.update_data(coins=int(t)); await state.set_state(CreateCode.uses)
    await msg.answer('👥 How many <b>users</b> can redeem this code? Send a number (e.g. 10).')
@router.message(CreateCode.uses)
@owner_only
async def code_uses(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    t=(msg.text or '').strip().replace(',','')
    if not t.isdigit() or not 0<int(t)<=1_000_000: await msg.answer('Send a whole number of users, like 10.'); return
    data=await state.get_data(); await state.clear()
    code=db.create_redeem_code(int(data['coins']),int(t))
    await msg.answer(f"✅ <b>Code created</b>\n\n🎟️ <code>{code}</code>\n🪙 {int(data['coins']):,} coins per user\n👥 Limit: {int(t):,} user(s)\n\nShare it. Users tap <b>🎟️ Redeem</b> and enter it.")
@router.message(Command('createcode'))
@owner_only
async def create_code(msg:Message,db):
    p=(msg.text or '').split()
    if len(p)!=3 or not p[1].isdigit() or not p[2].isdigit() or int(p[1])<=0 or int(p[2])<=0: await msg.answer('Usage: /createcode &lt;coins&gt; &lt;max_uses&gt;'); return
    code=db.create_redeem_code(int(p[1]),int(p[2])); await msg.answer(f'🎟️ <code>{code}</code>')

# ---------------- Persistent, one-time manual payment approvals ----------------
@router.callback_query(F.data.startswith('qpay:'))
@owner_only
async def quick_payment_review(cb:CallbackQuery, db):
    try:
        _, action, raw_id = cb.data.split(':', 2)
        request_id = int(raw_id)
    except (ValueError, TypeError):
        await cb.answer('Invalid payment request.', show_alert=True)
        return
    if action not in ('ok', 'no'):
        await cb.answer('Invalid action.', show_alert=True)
        return
    result = db.review_manual_payment_request(request_id, action == 'ok', cb.from_user.id)
    if not result.get('ok'):
        await cb.answer('Already handled or user unavailable. No balance change was made.', show_alert=True)
        return
    req = result['request']
    uid = req['user_id']
    if action == 'no':
        await cb.message.edit_text(f"❌ Payment request #{request_id} rejected. No coins or Premium were granted.")
        try: await cb.bot.send_message(uid, f"❌ Your payment request #{request_id} was rejected. Contact support if you believe this is an error.")
        except Exception: pass
        await cb.answer('Rejected')
        return
    if req['request_type'] == 'coins':
        total = result['total_coins']
        await cb.message.edit_text(f"✅ Payment request #{request_id} approved. {total:,} coins credited to <code>{uid}</code>.")
        try: await cb.bot.send_message(uid, f"✅ <b>Payment confirmed!</b>\nRequest: #{request_id}\n🪙 <b>{total:,}</b> coins were added to your wallet.")
        except Exception: pass
    else:
        days = int(req['plan_days'])
        duration = _plan_label(days)
        await cb.message.edit_text(f"✅ Payment request #{request_id} approved. Premium ({duration}) granted to <code>{uid}</code>.")
        try: await cb.bot.send_message(uid, f"⭐ <b>Payment confirmed — Premium activated!</b>\nRequest: #{request_id}\nPlan: {duration}\nTap <b>🏪 Become a Seller</b> to open your seller store.")
        except Exception: pass
    await cb.answer('Approved')

@router.callback_query(F.data=='admin:bc')
@owner_only
async def bc_start(cb:CallbackQuery,state:FSMContext): await state.set_state(Broadcast.message); await cb.message.edit_text('📢 Send the message to broadcast:'); await cb.answer()
@router.message(Broadcast.message)
@owner_only
async def bc_send(msg:Message,db,state:FSMContext):
    if await escaped(msg,state): return
    sent=0; failed=0
    users=db.get_all_users()
    await msg.answer(f'📢 Broadcast started for {len(users)} users. Sending with throttle…')
    for u in users:
        try: await msg.copy_to(chat_id=u['user_id']); sent+=1
        except Exception: failed+=1
        await asyncio.sleep(max(0.05, BROADCAST_DELAY_SECONDS))
    await state.clear(); await msg.answer(f'📢 Broadcast finished.\n✅ Sent: {sent}\n⚠️ Failed/blocked: {failed}')

@router.message(Command('user'))
@owner_only
async def user_lookup(msg:Message,db):
    p=(msg.text or '').split(maxsplit=1)
    if len(p)<2: await msg.answer('Usage: /user &lt;id|@username&gt;'); return
    u=db.find_user(p[1]); await msg.answer('Not found.' if not u else f"👤 {u['first_name']} @{u['username'] or '—'} (id {u['user_id']})\n💰 {u['coins']} 🚫 {u['is_banned']} ⭐ {u['is_premium']}")
@router.message(Command('addcoins'))
@owner_only
async def add_coins_cmd(msg:Message,db):
    p=(msg.text or '').split(maxsplit=3)
    if len(p)<3 or not p[1].isdigit() or not p[2].lstrip('-').isdigit(): await msg.answer('Usage: /addcoins &lt;user_id&gt; &lt;amount&gt; [note]'); return
    amount=int(p[2]);
    if amount==0: await msg.answer('Amount cannot be zero.'); return
    kind='admin_credit' if amount>0 else 'admin_debit'
    ok=db.add_coins(int(p[1]),amount,kind,p[3] if len(p)>3 else ''); await msg.answer('✅ Done.' if ok else '❌ User not found or insufficient balance.')
@router.message(Command('ban'))
@owner_only
async def ban(msg:Message,db):
    p=(msg.text or '').split();
    if len(p)!=2 or not p[1].isdigit(): await msg.answer('Usage: /ban &lt;user_id&gt;'); return
    await msg.answer('🚫 Banned.' if db.set_banned(int(p[1]),True) else '❌ User not found.')
@router.message(Command('unban'))
@owner_only
async def unban(msg:Message,db):
    p=(msg.text or '').split();
    if len(p)!=2 or not p[1].isdigit(): await msg.answer('Usage: /unban &lt;user_id&gt;'); return
    await msg.answer('✅ Unbanned.' if db.set_banned(int(p[1]),False) else '❌ User not found.')


@router.message(Command('proseller'))
@owner_only
async def set_pro_seller(msg:Message,db):
    p=(msg.text or '').split()
    if len(p)!=2 or not p[1].isdigit():
        await msg.answer('Usage: /proseller &lt;telegram_user_id&gt; — grants Pro Seller tier (10% commission). Set the plan price before offering paid enrollment.')
        return
    uid=int(p[1])
    if not db.set_seller_tier(uid,'pro'):
        await msg.answer('User not found. They must start the bot first.')
        return
    await msg.answer(f'✅ Pro Seller tier assigned to {uid}. Commission is 10% on future sales.')


@router.message(Command('setprice'))
@owner_only
async def set_product_price(msg:Message,db):
    parts=(msg.text or '').split()
    if len(parts)!=3 or not parts[1].isdigit() or not parts[2].isdigit() or int(parts[2])<0:
        await msg.answer('Usage: /setprice &lt;product_id&gt; &lt;new_coin_price&gt;')
        return
    pid,price=int(parts[1]),int(parts[2])
    old=db.get_product(pid)
    if not old or not db.set_product_price(pid,price):
        await msg.answer('Product not found or price update failed.')
        return
    recipients=db.wishlist_users(pid) if price < int(old['price']) else []
    sent=0
    for uid in recipients:
        try:
            await msg.bot.send_message(uid,f"🔔 <b>Price drop alert</b>\n{old['name']} dropped from {old['price']} to {price} coins. Open the Store to view it.")
            sent+=1
        except Exception: pass
    await msg.answer(f'✅ Product #{pid} price updated: {old["price"]} → {price} coins. Price-drop alerts sent: {sent}.')
