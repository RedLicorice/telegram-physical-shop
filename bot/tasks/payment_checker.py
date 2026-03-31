import asyncio
import logging
from bot.database.main import Database
from bot.database.models.main import Order, User
from bot.payments.checkers import PaymentCheckerFactory
from bot.config import EnvKeys
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

logger = logging.getLogger(__name__)


async def run_payment_checker():
    """
    Background task that runs continuously to check crypto payments.
    Checks every 60 seconds.
    """
    logger.info("Payment checker task started")
    bot = Bot(
        token=EnvKeys.TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    while True:
        try:
            await check_pending_payments(bot)
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Error in payment checker task: {e}", exc_info=True)
            await asyncio.sleep(120)


async def check_pending_payments(bot: Bot):
    with Database().session() as session:
        # Find all pending orders that have a crypto address assigned
        pending_orders = session.query(Order).filter(
            Order.order_status == 'pending',
            Order.crypto_address.isnot(None),
            Order.crypto_amount.isnot(None),
            Order.crypto_currency.isnot(None)
        ).all()

        for order in pending_orders:
            try:
                checker = PaymentCheckerFactory.get_checker(order.crypto_currency)
                if not checker:
                    logger.error(f"No checker found for currency {order.crypto_currency} on order {order.order_code}")
                    continue

                is_paid = await checker.check_payment(
                    address=order.crypto_address,
                    expected_amount=order.crypto_amount,
                    currency=order.crypto_currency,
                    use_testnet=order.use_testnet
                )

                if is_paid:
                    logger.info(f"Payment received for order {order.order_code}!")
                    
                    # Transition to confirmed. It still lacks delivery time.
                    # We keep reserved_until untouched, because it's paid.
                    order.order_status = 'confirmed'
                    session.commit()
                    
                    # Notify User
                    try:
                        user_msg = f"✅ Payment for order <b>{order.order_code}</b> has been confirmed confirmed on the blockchain!\nOur team will process it shortly."
                        await bot.send_message(order.buyer_id, user_msg)
                    except Exception as e:
                        logger.error(f"Failed to notify user {order.buyer_id} of payment: {e}")
                    
                    # Notify Admin
                    try:
                        admin_id = int(EnvKeys.OWNER_ID) if EnvKeys.OWNER_ID else None
                        if admin_id:
                            admin_msg = f"💰 <b>Payment Received!</b>\n\nOrder <b>{order.order_code}</b> has received its {order.crypto_currency} payment.\nStatus updated to 'confirmed'.\n<i>Please assign a delivery time or ship the items.</i>"
                            await bot.send_message(admin_id, admin_msg)
                    except Exception as e:
                        logger.error(f"Failed to notify admin of payment: {e}")
                        
            except Exception as e:
                logger.error(f"Error processing order {order.order_code} in payment checker: {e}")


def start_payment_checker():
    """
    Start the payment checker task in the background.
    """
    asyncio.create_task(run_payment_checker())
    logger.info("Payment checker task scheduled")
