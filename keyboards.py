from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


MENU_TEXTS = {'🛍️ Store','📚 Library','💰 Balance','💳 Buy Coins','⭐ Premium','🔗 Refer','👤 Profile','🎟️ Redeem','❤️ Wishlist','🎁 Daily Check-in','🆘 Support','👨‍💼 Seller Panel','🏪 Become a Seller','🛠️ Admin'}


def main_menu(is_seller=False, is_admin=False):
    b = ReplyKeyboardBuilder()
    texts = ['🛍️ Store','📚 Library','💰 Balance']
    if not is_admin: texts.append('💳 Buy Coins')          # admins never buy coins
    texts += ['⭐ Premium','🔗 Refer','👤 Profile','🎟️ Redeem','❤️ Wishlist','🎁 Daily Check-in','🆘 Support']
    for text in texts:
        b.button(text=text)
    # everybody sees this button; it only works for Premium members
    b.button(text='👨‍💼 Seller Panel' if is_seller else '🏪 Become a Seller')
    if is_admin: b.button(text='🛠️ Admin')
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def admin_menu(is_owner=True):
    b = InlineKeyboardBuilder()
    items = [('📤 Upload','admin:upload'),('🎫 Pending Products','admin:prod'),('🗑️ Delete Product','admin:delete')]
    if is_owner:
        items += [
            ('⭐ Grant Premium','admin:grant'),('🪙 Credit Coins','admin:sendcoins'),
            ('👥 Active Users','admin:active'),('🚫 Ban User','admin:ban'),('✅ Unban User','admin:unban'),
            ('📊 Dashboard','admin:dash'),('💰 Coin Requests','admin:req'),('⭐ Premium Requests','admin:premium'),
            ('💸 Refunds','admin:ref'),('👨‍💼 Sellers','admin:sel'),('💸 Withdrawals','admin:withdrawals'),
            ('🎟️ Create Code','admin:code'),('📢 Broadcast','admin:bc')]
    for text, cb in items:
        b.button(text=text, callback_data=cb)
    b.adjust(2)
    return b.as_markup()


def categories_kb(cats, prefix='cat'):
    b=InlineKeyboardBuilder()
    for c in cats: b.button(text=f"{c['icon']} {c['name']}", callback_data=f'{prefix}:{c["id"]}')
    b.adjust(2); return b.as_markup()


def product_kb(p, owned=False, own=False):
    # own=True: admin / the product's own seller. They only need Download (no rate/refund/buy).
    b=InlineKeyboardBuilder()
    if own:
        b.button(text='📥 Download', callback_data=f'get:{p["id"]}')
    elif owned:
        b.button(text='📥 Download', callback_data=f'get:{p["id"]}')
        b.button(text='⭐ Rate', callback_data=f'rate:{p["id"]}')
        b.button(text='↩️ Refund', callback_data=f'ref:{p["id"]}')
    else:
        b.button(text=f'💳 Buy ({p["price"]} coins)', callback_data=f'buy:{p["id"]}')
        if p.get('stars_price'):
            b.button(text=f'⭐ Buy with Stars ({p["stars_price"]}⭐)', callback_data=f'starbuy:{p["id"]}')
    if not own: b.button(text='❤️ Wishlist', callback_data=f'wish:{p["id"]}')
    b.button(text='⬅️ Back', callback_data='store')
    b.adjust(1); return b.as_markup()


def rate_kb(pid):
    b=InlineKeyboardBuilder()
    for n in range(1,6): b.button(text='⭐'*n, callback_data=f'stars:{pid}:{n}')
    b.adjust(5); return b.as_markup()


def review_kb(prefix, rid):
    b=InlineKeyboardBuilder(); b.button(text='✅ Approve',callback_data=f'{prefix}:ok:{rid}'); b.button(text='❌ Reject',callback_data=f'{prefix}:no:{rid}'); b.adjust(2); return b.as_markup()


def premium_kb(plans):
    b=InlineKeyboardBuilder()
    for days,price in plans:
        label = '♾️ Lifetime' if days == 0 else ('1 year' if days == 365 else f'{days} days')
        b.button(text=f'{label} — ₦{price:,}',callback_data=f'prem:{days}')
    b.adjust(1)
    b.button(text='🔄 Renew Premium',callback_data='prem:renew')
    return b.as_markup()

def premium_renew_only_kb():
    b=InlineKeyboardBuilder(); b.button(text='🔄 Renew Premium',callback_data='prem:renew'); return b.as_markup()

def premium_payment_kb():
    b=InlineKeyboardBuilder()
    b.button(text='⬅️ Premium Plans',callback_data='premium_plans')
    return b.as_markup()


def user_list_kb(users, prefix='sendto'):
    b=InlineKeyboardBuilder()
    for u in users[:50]:
        label = f"{u['first_name'][:20]} (@{u['username']})" if u.get('username') else f"{u['first_name'][:25]} · {u['user_id']}"
        b.button(text=label, callback_data=f'{prefix}:{u["user_id"]}')
    b.adjust(1); return b.as_markup()
