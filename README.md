# SHΔDOWBORNE ⸸ MART

Production-oriented Telegram digital marketplace built with Python, aiogram 3 and SQLite.

## Features
- Category-based digital store
- Text and Telegram-file products
- Coin wallet + transaction ledger
- Direct Telegram Stars product payments (Stars are not converted into marketplace coins)
- Seller withdrawals to Nigerian bank accounts or USDT TRC20
- Admin-controlled premium-only products
- Manual payment requests with proof + admin review
- Seller applications, product moderation, seller earnings and payout requests
- Premium subscriptions paid separately by manual NGN payment (30/60/90 days, 1 year, or lifetime)
- Premium verification queue with screenshot proof, admin approve/reject reasons, automatic renewal extension, 14/7-day expiry warnings and 7-day Seller grace period
- Premium is required for Verified Seller approval; expired Seller accounts are suspended after grace and automatically restored after Premium renewal
- Unique persistent Seller IDs
- Controlled coin economy: default payout value is ₦25 per coin, with configurable floor/ceiling bounds
- Refund requests and admin review
- Ratings
- Referral rewards with daily cap
- Redeem codes and daily check-in streaks (spend-only coins)
- Wishlists and admin-triggered price-drop alerts
- Standard/Premium coin bonus packs
- Pro Seller tier (10% commission) and MONOTECH partner co-admin/100% seller allocation
- Persistent SQLite FSM state, throttled broadcasts, duplicate screenshot ID checks, and account-age withdrawal gate
- Admin dashboard, active-user list, broadcasts, ban/unban, product deletion, coin transfers
- SQLite WAL mode, foreign keys, indexes and atomic transactions

## Setup
1. Copy `.env.example` to `.env` (locally) or set the same values as Railway Variables.
2. Set `BOT_TOKEN` and your numeric Telegram ID in `ADMIN_IDS`. Set `MONOTECH_USER_ID` to MONOTECH's numeric Telegram user ID to enable the co-admin and partner seller account. This cannot be inferred from the name alone.
3. Create a virtual environment and install dependencies:
   `python -m pip install -r requirements.txt`
4. Initialize the database:
   `python migrate.py`
5. Start:
   `python bot.py`

Never commit `.env` or the database file.


## Roles & permissions (Z6)
| Who | Can do |
|---|---|
| Normal user | Browse the Store, buy with coins/Stars, library, wishlist, redeem, check-in. **No upload tools.** |
| Premium member | Everything above + **👨‍💼 Seller Panel** (auto-activated): upload products (admin reviews them), earn commission, withdraw. |
| Co-admin (MONOTECH) | Lifetime Premium + **📤 Upload** (published instantly), 🎫 Pending Products review, 🗑️ Delete Product. |
| Owner (first ID in `ADMIN_IDS`) | Everything: ⭐ Grant Premium, 🪙 Credit Coins, 👥 Active Users, 🚫 Ban / ✅ Unban (by ID or @username), dashboard, payments, withdrawals, broadcast. Lifetime Premium + free access to every product. |

- Owner = every ID in `ADMIN_IDS`. `MONOTECH_USER_ID` is added as co-admin only.
- **Buying Premium / coins is manual:** the user taps a tier or a pack, the bot shows your OPay details and the exact ₦ amount, and a **Message Admin** button opens your DM (`ADMIN_CONTACT_URL`). You also get a message with a one-tap **✅ Grant / ✅ Credit** button to press after you confirm the payment.
- **🎟️ Create Code** (owner): asks coins per user, then how many users can redeem; gives you the code.
- Seller IDs are created only when a Premium user taps **🏪 Become a Seller**.
- Send `/myid` to the bot to see your Telegram ID and the role the bot gives you.
- Upload wizard: category → title → author → description → chapters → price → (admin: Stars price, Premium-only) → cover photo → file → preview → publish.
- Railway: attach a **Volume** and point `DB_PATH` at it (e.g. `/data/shadowborne_mart.db`) or the database is wiped on every deploy. Never upload `.env`; use Railway Variables.

## Docker
Set `.env`, then:
`docker compose up -d --build`

The database is persisted in `./data` when using the included compose file. For the compose deployment, set `DB_PATH=data/shadowborne_mart.db` in `.env`.

## Important production notes
- Direct Telegram Stars product payments are recorded by `telegram_payment_charge_id`; Telegram credits the bot owner’s Stars balance, while seller/admin Star attribution is tracked internally. Telegram Bot API does not offer a direct transfer of Stars to another user’s personal Stars balance, so automatic seller-account credit is not technically available through this bot API.
- Seller withdrawals are manually reviewed and can be paid by Nigerian bank transfer or USDT TRC20. Sellers are told to allow 3–7 days.
- Manual coin requests never credit automatically; an admin must verify the payment and approve them. Coin requests display amount at ₦25 per coin; bonus coins are credited only after approval.
- Refund requests require a clear reason and are accepted 2–5 hours after purchase. After an approved refund, the same buyer cannot repurchase that product for 10 days.
- Withdrawable coins are computed from net item-sale earnings only; purchased coins, referrals, redeem codes, check-ins, and the partner seed balance are not withdrawable. Withdrawals require an account age of at least 7 days by default.
- Use `/proseller <telegram_user_id>` to grant the Pro Seller tier (10% commission), and `/setprice <product_id> <new_coin_price>` to update a product and trigger wishlist price-drop alerts.
- All payment instructions default to OPay account 8063258989 / Augustine Uchechi Chinaecherem and can be changed through environment variables before deployment. Coin price is ₦25 per coin; lifetime Premium is ₦25,000 and one-year Premium is ₦14,500.
- Product seller submissions are pending until approved.
- Coins are modified transactionally and every modification is recorded in the ledger.
- SQLite is appropriate for a small/medium single-bot deployment. If you later run multiple bot workers or need high write concurrency, migrate the persistence layer to PostgreSQL.

## Manual payment safety (Z7 fixed patch)
For manual coin and Premium purchases, users must send the payment screenshot or image/document in the bot chat after creating a request. The owner receives the request and proof, verifies the actual bank credit independently, and only then approves it. Each request has a persistent database ID; approvals are atomic and can only be applied once. The bot checks Telegram's `file_unique_id` to reject duplicate proof reused across these manual requests. A request with no proof stops blocking new requests after one hour. This is still manual payment verification, not automatic bank integration.

MONOTECH's admin-uploaded products are assigned to the configured MONOTECH seller account so qualifying sales use the partner's configured commission rule. Main-owner admin uploads remain catalog-managed products without a seller attribution.
