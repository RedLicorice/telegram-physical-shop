import asyncio
import logging
from typing import Optional
from bot.database.main import Database
from bot.database.models.main import BotSettings
from bot.payments.crypto import get_crypto_address_stats, add_crypto_addresses_bulk, CHAIN_FILES
from bot.payments.wallets import WalletManager

logger = logging.getLogger(__name__)

class AddressFeederTask:
    """
    Background task that monitors address pools and feeds new addresses from BIP wallets.
    """
    
    def __init__(self, interval: int = 3600):
        self.interval = interval
        self.wallet_manager = WalletManager()
        self._running = False

    async def get_setting(self, key: str, default: str) -> str:
        with Database().session() as session:
            setting = session.query(BotSettings).filter_by(setting_key=key).first()
            return setting.setting_value if setting else default

    async def run(self):
        self._running = True
        logger.info("Address Feeder Task started")
        
        while self._running:
            try:
                auto_feed = await self.get_setting("wallet_auto_feed", "false")
                if auto_feed.lower() == "true":
                    threshold = int(await self.get_setting("wallet_feed_threshold", "10"))
                    amount = int(await self.get_setting("wallet_feed_amount", "20"))
                    
                    for chain in CHAIN_FILES.keys():
                        await self.check_and_feed(chain, threshold, amount)
                        
            except Exception as e:
                logger.error(f"Error in Address Feeder Task: {e}", exc_info=True)
            
            await asyncio.sleep(self.interval)

    async def check_and_feed(self, chain: str, threshold: int, amount: int):
        stats = get_crypto_address_stats(chain)
        if stats['available'] < threshold:
            logger.info(f"Chain {chain} address pool below threshold ({stats['available']} < {threshold}). Feeding...")
            
            try:
                # We need to know the next index to derive. 
                # For simplicity, we'll use the total number of addresses ever added to this chain as the start index.
                # However, a better approach might be to store the "last derived index" in settings.
                
                last_index_key = f"wallet_last_index_{chain.lower()}"
                last_index = int(await self.get_setting(last_index_key, "0"))
                
                new_addresses = self.wallet_manager.derive_addresses(chain, last_index, amount)
                
                if new_addresses:
                    count = add_crypto_addresses_bulk(chain, new_addresses)
                    logger.info(f"Successfully fed {count} new addresses to {chain}")
                    
                    # Update last index
                    with Database().session() as session:
                        setting = session.query(BotSettings).filter_by(setting_key=last_index_key).first()
                        if setting:
                            setting.setting_value = str(last_index + amount)
                        else:
                            setting = BotSettings(setting_key=last_index_key, setting_value=str(last_index + amount))
                            session.add(setting)
                        session.commit()
                        
            except FileNotFoundError:
                logger.warning(f"Public key for {chain} not found. Skipping auto-feed for this chain.")
            except Exception as e:
                logger.error(f"Failed to feed addresses for {chain}: {e}")

    def stop(self):
        self._running = False
