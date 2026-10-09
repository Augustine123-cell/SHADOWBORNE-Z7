from aiogram import Router, F
from aiogram.filters import Command
from keyboards import main_menu
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from states import AddProduct, WithdrawFlow
from config import COIN_NGN_RATE, COIN_USDT_RATE, PAYOUT_FEE_PERCENT, MIN_WITHDRAW_COINS, PAYOUT_MIN_DAYS, PAYOUT_MAX_DAYS
import re
router=Router()

def _premium_required_kb():
    b=InlineKeyboardBuilder(); b.button(text='⭐ Get Premium',callback_data='premium_plans'); return b.as_markup()

@router.message(F.text.in_({'👨‍💼 Seller Panel','🏪 Become a Seller'}))
@router.message(Command('become_seller'))
async def seller_entry(msg:Message,db,is_admin):
    """One button for everybody. Premium members become Verified Sellers (and get their Seller ID) the moment they tap it."""
    uid=msg.from_user.id; status=db.seller_status(uid); info=db.premium_info(uid)
    if status!='approved':
        if status=='suspended':
            await msg.answer('🔒 Your seller account is suspended because Premium expired beyond the 7-day grace period. Renew Premium to restore it automatically.',reply_markup=_premium_required_kb()); return
        if not info['active']:
            await msg.answer('🔒 <b>Become a Premium user to become a seller.</b>\n\nPremium members can open a seller store, upload products, earn commission and withdraw their profits.',reply_markup=_premium_required_kb()); return
        db.set_seller_status(uid,'approved')
        await msg.answer(f'🎉 <b>You are now a Verified Seller!</b>\n\n🆔 Your Seller ID: <code>{db.seller_code(uid)}</code>',reply_markup=main_menu(True,is_admin))
    grace=''
    if not info['active'] and info['grace_until']: grace=f"\n⚠️ Premium expired. Seller grace ends <b>{info['grace_until']}</b>. Renew before then to keep seller access."
    b=InlineKeyboardBuilder(); b.button(text='📊 My Stats',callback_data='sel:stats'); b.button(text='➕ Add Product',callback_data='sel:add'); b.button(text='💸 Withdraw',callback_data='sel:withdraw'); b.adjust(1)
    await msg.answer(f'👨‍💼 <b>Seller Panel</b>\n\n🆔 Seller ID: <code>{db.seller_code(uid)}</code>\n💰 Withdrawable: <b>{db.seller_withdrawable(uid):,} coins</b>{grace}',reply_markup=b.as_markup())

@router.callback_query(F.data=='sel:stats')
async def stats(cb:CallbackQuery,db):
    s=db.seller_stats(cb.from_user.id); star_earned=db._scalar('SELECT COALESCE(SUM(seller_stars),0) FROM star_product_payments WHERE seller_id=?',(cb.from_user.id,)) or 0; top='\n'.join(f"• {x['name']} — {x['n']} ({x['earned']}💰)" for x in s['top']) or '—'
    await cb.message.edit_text(f"📊 Sales: {s['sales']}\n💰 Earned: {s['earned']} coins\n⭐ Stars earned (tracked): {star_earned} Stars\n💸 Withdrawable: {db.seller_withdrawable(cb.from_user.id):,} coins\n📦 Active: {s['products']}\n\nTop:\n{top}"); await cb.answer()

@router.callback_query(F.data=='sel:withdraw')
async def withdraw_start(cb:CallbackQuery,state:FSMContext,db):
    if db.seller_status(cb.from_user.id)!='approved' or db.premium_info(cb.from_user.id)['active'] is False and not db.premium_info(cb.from_user.id)['grace_until']:
        await cb.answer('Seller access is unavailable. Renew Premium.',show_alert=True); return
    available=db.seller_withdrawable(cb.from_user.id)
    if available<MIN_WITHDRAW_COINS: await cb.answer(f'Minimum withdrawal is {MIN_WITHDRAW_COINS:,} coins. You have {available:,}.',show_alert=True); return
    await state.set_state(WithdrawFlow.amount); await cb.message.edit_text(f'💸 <b>Withdraw Coins</b>\n\nAvailable: <b>{available:,}</b>\nMinimum: <b>{MIN_WITHDRAW_COINS:,}</b>\n\nSend the number of coins you want to convert.'); await cb.answer()

@router.message(WithdrawFlow.amount)
async def withdraw_amount(msg:Message,state:FSMContext,db):
    if not (msg.text or '').isdigit(): await msg.answer('Enter a whole number of coins.'); return
    amount=int(msg.text); available=db.seller_withdrawable(msg.from_user.id)
    if amount<MIN_WITHDRAW_COINS: await msg.answer(f'Minimum withdrawal is {MIN_WITHDRAW_COINS:,} coins.'); return
    if amount>available: await msg.answer(f'You only have {available:,} withdrawable coins.'); return
    ngn=round(amount*COIN_NGN_RATE*(1-PAYOUT_FEE_PERCENT/100),2); usdt=round(amount*COIN_USDT_RATE*(1-PAYOUT_FEE_PERCENT/100),6)
    await state.update_data(amount=amount); await state.set_state(WithdrawFlow.method)
    b=InlineKeyboardBuilder(); b.button(text=f'🏦 Bank — ₦{ngn:,.2f}',callback_data='withdraw_method:bank'); b.button(text=f'₮ USDT TRC20 — {usdt:.6f} USDT',callback_data='withdraw_method:usdt'); b.adjust(1)
    await msg.answer(f'💱 <b>Conversion</b>\n\n{amount:,} coins\nBank net: <b>₦{ngn:,.2f}</b>\nUSDT net: <b>{usdt:.6f} USDT</b>\n\nA {PAYOUT_FEE_PERCENT:g}% payout adjustment is applied. Payments may take <b>{PAYOUT_MIN_DAYS}–{PAYOUT_MAX_DAYS} days</b>.',reply_markup=b.as_markup())

@router.callback_query(WithdrawFlow.method,F.data.startswith('withdraw_method:'))
async def withdraw_method(cb:CallbackQuery,state:FSMContext):
    method=cb.data.split(':',1)[1]; await state.update_data(method=method)
    if method=='bank': await state.set_state(WithdrawFlow.account_number); await cb.message.edit_text('🏦 Send your bank account number:')
    else: await state.set_state(WithdrawFlow.usdt_address); await cb.message.edit_text('₮ Send your <b>USDT TRC20</b> wallet address:')
    await cb.answer()

@router.message(WithdrawFlow.account_number)
async def bank_number(msg:Message,state:FSMContext):
    value=(msg.text or '').strip().replace(' ','')
    if not value.isdigit() or len(value)!=10: await msg.answer('Enter a valid bank account number.'); return
    await state.update_data(account_number=value); await state.set_state(WithdrawFlow.account_name); await msg.answer('👤 Send the exact account name:')
@router.message(WithdrawFlow.account_name)
async def bank_account_name(msg:Message,state:FSMContext):
    value=(msg.text or '').strip()
    if len(value)<2 or len(value)>150: await msg.answer('Enter a valid account name.'); return
    await state.update_data(account_name=value); await state.set_state(WithdrawFlow.bank_name); await msg.answer('🏦 Send the bank/provider name (e.g. OPay, UBA, Access, Fidelity):')
@router.message(WithdrawFlow.bank_name)
async def bank_provider(msg:Message,state:FSMContext,db):
    value=(msg.text or '').strip()
    if len(value)<2 or len(value)>100: await msg.answer('Enter a valid bank/provider name.'); return
    data=await state.get_data(); res=db.create_seller_payout(msg.from_user.id,data['amount'],'bank',data['account_number'],data['account_name'],value,'',PAYOUT_FEE_PERCENT,COIN_NGN_RATE,COIN_USDT_RATE); await state.clear()
    await msg.answer(f"✅ Withdrawal request #{res['id']} submitted.\n\nAmount: <b>{res['amount_coins']:,} coins</b>\nNet payout: <b>₦{res['net']:,.2f}</b>\n\n⏳ Payments may take {PAYOUT_MIN_DAYS}–{PAYOUT_MAX_DAYS} days after review." if res.get('ok') else f"❌ Could not create withdrawal: {res.get('reason')}")
@router.message(WithdrawFlow.usdt_address)
async def usdt_address(msg:Message,state:FSMContext,db):
    value=(msg.text or '').strip()
    if not re.fullmatch(r'T[1-9A-HJ-NP-Za-km-z]{33}',value): await msg.answer('❌ Invalid USDT TRC20 address format. Send the TRON (T...) address only.'); return
    data=await state.get_data(); res=db.create_seller_payout(msg.from_user.id,data['amount'],'usdt','','','',value,PAYOUT_FEE_PERCENT,COIN_NGN_RATE,COIN_USDT_RATE); await state.clear()
    await msg.answer(f"✅ Withdrawal request #{res['id']} submitted.\n\nAmount: <b>{res['amount_coins']:,} coins</b>\nNet payout: <b>{res['net']:.6f} USDT</b>\nNetwork: <b>TRC20</b>\n\n⏳ Payments may take {PAYOUT_MIN_DAYS}–{PAYOUT_MAX_DAYS} days after review." if res.get('ok') else f"❌ Could not create withdrawal: {res.get('reason')}")
