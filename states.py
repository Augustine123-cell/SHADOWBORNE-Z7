from aiogram.fsm.state import State, StatesGroup

class AddProduct(StatesGroup):
    category = State(); name = State(); desc = State(); price = State(); stars_price = State(); ctype = State(); content = State()

class BuyCoins(StatesGroup):
    amount = State(); ref = State(); proof = State()

class RefundFlow(StatesGroup):
    reason = State()

class RedeemFlow(StatesGroup):
    code = State()

class Broadcast(StatesGroup):
    message = State()

class AdminCoins(StatesGroup):
    target = State(); amount = State(); note = State()

class AdminAddProduct(StatesGroup):
    category = State(); name = State(); desc = State(); price = State(); stars_price = State(); premium_only = State(); ctype = State(); content = State()

class WithdrawFlow(StatesGroup):
    amount = State(); method = State(); account_number = State(); account_name = State(); bank_name = State(); usdt_address = State()

class PremiumPurchase(StatesGroup):
    plan = State(); proof = State()

class PremiumReject(StatesGroup):
    reason = State()


class Upload(StatesGroup):
    category = State(); name = State(); author = State(); desc = State(); chapters = State()
    price = State(); stars = State(); premium = State(); cover = State(); file = State(); confirm = State()

class GrantPremium(StatesGroup):
    target = State()

class AdminBan(StatesGroup):
    ban = State(); unban = State()

class CreateCode(StatesGroup):
    coins = State(); uses = State()

class PaymentProof(StatesGroup):
    upload = State()
