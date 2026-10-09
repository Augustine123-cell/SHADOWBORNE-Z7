import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()}
MONOTECH_USER_ID = int(os.getenv('MONOTECH_USER_ID', '0') or 0)
# OWNER_IDS = the main admin(s) from ADMIN_IDS. The MONOTECH co-admin is NOT an owner:
# co-admin gets lifetime Premium + upload/moderation tools only; owner-only tools
# (grant Premium, credit coins, ban/unban, active users, payments...) are never shown to MONOTECH.
OWNER_IDS = {i for i in ADMIN_IDS if i != MONOTECH_USER_ID}
if MONOTECH_USER_ID > 0: ADMIN_IDS.add(MONOTECH_USER_ID)
DB_PATH = os.getenv('DB_PATH', 'shadowborne_mart.db')
SELLER_COMMISSION = int(os.getenv('SELLER_COMMISSION', '20'))
REFUND_WINDOW_MIN_HOURS = 2
REFUND_WINDOW_MAX_HOURS = 5
REFUND_COOLDOWN_DAYS = 10
REFERRAL_REWARD_REF = int(os.getenv('REFERRAL_REWARD_REF', '20'))
REFERRAL_REWARD_NEW = int(os.getenv('REFERRAL_REWARD_NEW', '10'))
REFERRAL_DAILY_CAP = int(os.getenv('REFERRAL_DAILY_CAP', '10'))
MAX_PENDING_REQUESTS = int(os.getenv('MAX_PENDING_REQUESTS', '3'))
ADMIN_RESERVE_COINS = int(os.getenv('ADMIN_RESERVE_COINS', '99999999999'))
COIN_NGN_RATE = float(os.getenv('COIN_NGN_RATE', '25'))
COIN_NGN_MIN_RATE = float(os.getenv('COIN_NGN_MIN_RATE', '20'))
COIN_NGN_MAX_RATE = float(os.getenv('COIN_NGN_MAX_RATE', '75'))
COIN_USDT_RATE = float(os.getenv('COIN_USDT_RATE', '0.005'))
PAYOUT_FEE_PERCENT = float(os.getenv('PAYOUT_FEE_PERCENT', '5'))
MIN_WITHDRAW_COINS = int(os.getenv('MIN_WITHDRAW_COINS', '1000'))
PAYOUT_MIN_DAYS = int(os.getenv('PAYOUT_MIN_DAYS', '3'))
PAYOUT_MAX_DAYS = int(os.getenv('PAYOUT_MAX_DAYS', '7'))
# Premium is a separate manual-payment product; it never consumes coins.
PREMIUM_PAYMENT_ACCOUNT = os.getenv('PREMIUM_PAYMENT_ACCOUNT', '8063258989').strip()
PREMIUM_PAYMENT_NAME = os.getenv('PREMIUM_PAYMENT_NAME', 'Augustine Uchechi Chinaecherem').strip()
PREMIUM_PAYMENT_PROVIDER = os.getenv('PREMIUM_PAYMENT_PROVIDER', 'OPay').strip()
ADMIN_CONTACT_URL = os.getenv('ADMIN_CONTACT_URL', 'https://t.me/lord_sylum').strip()
PREMIUM_GRACE_DAYS = int(os.getenv('PREMIUM_GRACE_DAYS', '7'))
PREMIUM_PLANS = {30: 2500, 60: 5000, 90: 7500, 365: 14500, 0: 25000}  # 0 = lifetime
COIN_PACKS = {1000: 100, 2000: 200}
PREMIUM_COIN_PACKS = {500: 100, 1000: 170}
MONOTECH_STARTING_COINS = 2000
COIN_PURCHASE_PRICE_NGN = 25
BROADCAST_DELAY_SECONDS = float(os.getenv('BROADCAST_DELAY_SECONDS', '0.05'))
WITHDRAWAL_MIN_ACCOUNT_AGE_DAYS = int(os.getenv('WITHDRAWAL_MIN_ACCOUNT_AGE_DAYS', '7'))


if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN is not configured. Put it in .env or the deployment environment.')
if not ADMIN_IDS or not OWNER_IDS:
    raise RuntimeError('ADMIN_IDS is not configured. Put at least one numeric Telegram user ID (the owner, not MONOTECH) in ADMIN_IDS.')
if not 0 <= SELLER_COMMISSION <= 100:
    raise RuntimeError('SELLER_COMMISSION must be between 0 and 100.')
if len(ADMIN_IDS) > 4: raise RuntimeError('ADMIN_IDS supports at most 4 admins including MONOTECH.')
if ADMIN_RESERVE_COINS <= 0: raise RuntimeError('ADMIN_RESERVE_COINS must be positive.')
if COIN_NGN_RATE <= 0 or COIN_USDT_RATE <= 0: raise RuntimeError('Payout rates must be positive.')
if COIN_NGN_MIN_RATE <= 0 or COIN_NGN_MAX_RATE < COIN_NGN_MIN_RATE: raise RuntimeError('Invalid coin-rate bounds.')
if not (COIN_NGN_MIN_RATE <= COIN_NGN_RATE <= COIN_NGN_MAX_RATE): raise RuntimeError('COIN_NGN_RATE must stay inside its configured bounds.')
if PREMIUM_GRACE_DAYS < 0: raise RuntimeError('PREMIUM_GRACE_DAYS cannot be negative.')
if not 0 <= PAYOUT_FEE_PERCENT < 100: raise RuntimeError('PAYOUT_FEE_PERCENT must be between 0 and 100.')
if MIN_WITHDRAW_COINS <= 0 or PAYOUT_MIN_DAYS <= 0 or PAYOUT_MAX_DAYS < PAYOUT_MIN_DAYS: raise RuntimeError('Invalid payout settings.')
