from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.models.main import Permission, BotSettings
from bot.database.main import Database
from bot.database.methods.read import get_bot_setting
from bot.keyboards.inline import wallet_management_keyboard
from bot.filters import HasPermissionFilter
from bot.payments.crypto import get_crypto_address_stats, CHAIN_FILES, add_crypto_addresses_bulk
from bot.payments.wallets import WalletManager

router = Router()

@router.callback_query(F.data == "wallet_management", HasPermissionFilter(Permission.SETTINGS_MANAGE))
async def wallet_menu(call: CallbackQuery, state: FSMContext):
    """
    Show wallet management menu.
    """
    await state.clear()
    
    auto_feed = get_bot_setting("wallet_auto_feed", default="false").lower() == "true"
    threshold = get_bot_setting("wallet_feed_threshold", default="10")
    
    status_text = "💼 <b>Wallet Management</b>\n\n"
    status_text += f"Auto-Feed: <b>{'ENABLED' if auto_feed else 'DISABLED'}</b>\n"
    status_text += f"Threshold: <b>{threshold} addresses</b>\n\n"
    
    for chain in CHAIN_FILES.keys():
        stats = get_crypto_address_stats(chain)
        status_text += f"• <b>{chain}</b>: {stats['available']} available / {stats['total']} total\n"
    
    status_text += "\nClick a button below to manually feed 10 addresses or toggle auto-feed."

    await call.message.edit_text(
        status_text,
        reply_markup=wallet_management_keyboard(CHAIN_FILES.keys(), auto_feed),
        parse_mode='HTML'
    )

@router.callback_query(F.data.startswith("wallet_feed:"), HasPermissionFilter(Permission.SETTINGS_MANAGE))
async def manual_feed(call: CallbackQuery):
    """
    Manually trigger address feeding for a specific chain.
    """
    chain = call.data.split(":")[1]
    manager = WalletManager()
    
    # Get last index
    last_index_key = f"wallet_last_index_{chain.lower()}"
    last_index = int(get_bot_setting(last_index_key, default="0"))
    
    try:
        addresses = manager.derive_addresses(chain, last_index, 10)
        if addresses:
            added = add_crypto_addresses_bulk(chain, addresses)
            
            # Update last index
            with Database().session() as session:
                setting = session.query(BotSettings).filter_by(setting_key=last_index_key).first()
                if setting:
                    setting.setting_value = str(last_index + 10)
                else:
                    setting = BotSettings(setting_key=last_index_key, setting_value=str(last_index + 10))
                    session.add(setting)
                session.commit()
                
            await call.answer(f"✅ Added {added} addresses to {chain}")
            await wallet_menu(call, None) # Refresh menu
        else:
            await call.answer("❌ No addresses derived.")
    except FileNotFoundError:
        await call.answer(f"❌ Public key for {chain} not found!", show_alert=True)
    except Exception as e:
        await call.answer(f"❌ Error: {e}", show_alert=True)

@router.callback_query(F.data == "wallet_toggle_autofeed", HasPermissionFilter(Permission.SETTINGS_MANAGE))
async def toggle_autofeed(call: CallbackQuery, state: FSMContext):
    """
    Toggle auto-feed setting.
    """
    current = get_bot_setting("wallet_auto_feed", default="false").lower() == "true"
    new_value = "false" if current else "true"
    
    with Database().session() as session:
        setting = session.query(BotSettings).filter_by(setting_key="wallet_auto_feed").first()
        if setting:
            setting.setting_value = new_value
        else:
            setting = BotSettings(setting_key="wallet_auto_feed", setting_value=new_value)
            session.add(setting)
        session.commit()
    
    await call.answer(f"✅ Auto-feed {'enabled' if new_value == 'true' else 'disabled'}")
    await wallet_menu(call, state)
