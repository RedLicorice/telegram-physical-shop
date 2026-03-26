import logging
import aiohttp
from decimal import Decimal
from bot.payments.checkers.base import BaseChecker

from bot.config.env import EnvKeys

logger = logging.getLogger(__name__)

class BitcoinChecker(BaseChecker):
    def __init__(self):
        if EnvKeys.USE_TESTNET:
            self.base_url = "https://blockstream.info/testnet/api"
        else:
            self.base_url = "https://blockstream.info/api"

    async def check_payment(self, address: str, expected_amount: Decimal, currency: str = 'BTC', **kwargs) -> bool:
        """
        Check Bitcoin payment using blockstream.info API.
        Since we generate a new address for each order, we can check `funded_txo_sum` 
        which represents total received satoshis.
        """
        if currency != 'BTC':
            logger.error(f"BitcoinChecker cannot check currency {currency}")
            return False

        try:
            url = f"{self.base_url}/address/{address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        chain_stats = data.get('chain_stats', {})
                        mempool_stats = data.get('mempool_stats', {})
                        
                        # Use both confirmed and unconfirmed (mempool) received amounts
                        received_sats = chain_stats.get('funded_txo_sum', 0) + mempool_stats.get('funded_txo_sum', 0)
                        
                        received_btc = Decimal(received_sats) / Decimal('100000000')
                        
                        logger.info(f"BTC Check for {address}: Found {received_btc} BTC (including mempool), expected {expected_amount}")
                        return received_btc >= expected_amount
                    else:
                        logger.warning(f"Blockstream API error for {address}: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Error checking BTC balance for {address}: {e}")
            
        return False
