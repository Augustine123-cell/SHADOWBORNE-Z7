import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fsm_storage import SQLiteFSMStorage
from config import MONOTECH_USER_ID, MONOTECH_STARTING_COINS
from config import BOT_TOKEN, DB_PATH, ADMIN_IDS, OWNER_IDS
from database import Database
from middlewares import UserMiddleware
import handlers_admin, handlers_upload, handlers_seller, handlers_payments, handlers_user

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

async def on_error(event: ErrorEvent):
    """Log every crash and always answer the user, so buttons never spin forever."""
    logging.error('Unhandled error while processing an update', exc_info=event.exception)
    try:
        cq = event.update.callback_query
        if cq: await cq.answer('⚠️ Something went wrong. Please try again.', show_alert=True)
        elif event.update.message: await event.update.message.answer('⚠️ Something went wrong. Please try again.')
    except Exception: pass
    return True

async def premium_watchdog(bot: Bot, db: Database):
    """Send 14/7-day Premium warnings and enforce the 7-day seller grace period."""
    while True:
        try:
            now=datetime.now(timezone.utc)
            for u in db.premium_notification_candidates():
                uid=u['user_id']
                until=datetime.fromisoformat(u['premium_until']) if u['premium_until'] else None
                if not until:
                    continue
                delta=until-now
                days=delta.total_seconds()/86400
                if 0 < days <= 14 and not u['premium_warn_14_sent']:
                    if db.mark_premium_notification(uid,'premium_warn_14_sent'):
                        try:
                            await bot.send_message(uid,'⚠️ <b>Premium expires soon</b>\n\nYour Premium access expires in about 14 days. Renew now with /premium to keep uninterrupted access.' + ('\n\n👨‍💼 Because you are a seller, renewing on time protects your Verified Seller access.' if u['seller_status']=='approved' else ''))
                        except Exception: pass
                if 0 < days <= 7 and not u['premium_warn_7_sent']:
                    if db.mark_premium_notification(uid,'premium_warn_7_sent'):
                        try:
                            await bot.send_message(uid,'🚨 <b>Premium expires within 7 days</b>\n\nRenew with /premium before expiry.' + ('\n\n👨‍💼 Seller warning: after Premium expires you receive a 7-day grace period. If you do not renew before the grace ends, Seller access will be suspended automatically.' if u['seller_status']=='approved' else ''))
                        except Exception: pass
                if days <= 0 and not u['premium_expiry_sent']:
                    if db.mark_premium_notification(uid,'premium_expiry_sent'):
                        try:
                            await bot.send_message(uid,'⏰ <b>Premium has expired</b>\n\nRenew with /premium to restore Premium.' + ('\n\n👨‍💼 Your Verified Seller account has a 7-day grace period before suspension.' if u['seller_status']=='approved' else ''))
                        except Exception: pass
                status_before=u['seller_status']
                status_after=db.seller_access_sync(uid)
                if status_before=='approved' and status_after=='suspended' and not u['seller_grace_sent']:
                    if db.mark_premium_notification(uid,'seller_grace_sent'):
                        try:
                            await bot.send_message(uid,'🔒 <b>Seller access suspended</b>\n\nYour Premium grace period ended. Your Seller account and products remain intact, but Seller tools are locked. Renew Premium with /premium and your Verified Seller access will automatically return with the same Seller ID and history.')
                        except Exception: pass
        except Exception:
            logging.exception('Premium watchdog cycle failed')
        await asyncio.sleep(3600)

async def main():
    db=Database(DB_PATH); db.init_db()
    if MONOTECH_USER_ID > 0: db.setup_monotech_partner(MONOTECH_USER_ID, MONOTECH_STARTING_COINS)
    # Owner + co-admin always hold LIFETIME Premium (created even before they press /start).
    for admin_id in ADMIN_IDS: db.ensure_lifetime_premium(admin_id)
    logging.getLogger(__name__).info('Owners: %s | All admins: %s', sorted(OWNER_IDS), sorted(ADMIN_IDS))
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher(storage=SQLiteFSMStorage(DB_PATH + ".fsm.sqlite3"))
    dp.errors.register(on_error)
    middleware=UserMiddleware(db)
    dp.message.middleware(middleware); dp.callback_query.middleware(middleware); dp.pre_checkout_query.middleware(middleware)
    dp.include_router(handlers_admin.router); dp.include_router(handlers_upload.router); dp.include_router(handlers_seller.router); dp.include_router(handlers_payments.router); dp.include_router(handlers_user.router)
    await bot.delete_webhook(drop_pending_updates=True)
    watchdog=asyncio.create_task(premium_watchdog(bot,db))
    logging.getLogger(__name__).info('SHADOWBORNE MART started')
    try:
        await dp.start_polling(bot)
    finally:
        watchdog.cancel()
        await dp.storage.close()
        await bot.session.close()

if __name__=='__main__': asyncio.run(main())
