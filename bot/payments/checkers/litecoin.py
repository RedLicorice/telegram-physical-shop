import logging
import aiohttp
from decimal import Decimal
from bot.payments.checkers.base import BaseChecker

from bot.config.env import EnvKeys

logger = logging.getLogger(__name__)

class LitecoinChecker(BaseChecker):
    async def check_payment(self, address: str, expected_amount: Decimal, currency: str, use_testnet: bool, **kwargs) -> bool:
        """
        Check Litecoin payment using blockcypher API.
        Checks total received (to handle new addresses per order).
        """
        if use_testnet:
            base_url = "https://api.blockcypher.com/v1/ltc/test3/addrs"
        else:
            base_url = "https://api.blockcypher.com/v1/ltc/main/addrs"

        if currency != 'LTC':
            logger.error(f"LitecoinChecker cannot check currency {currency}")
            return False

        try:
            url = f"{base_url}/{address}/balance"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Get total received in litoshis (10^-8 LTC)
                        received_litoshis = data.get('total_received', 0) + data.get('unconfirmed_n_tx', 0) # unconfirmed might need unconfirmed_balance
                        
                        # Actually blockcypher has 'unconfirmed_balance' but for total received let's just use balance + unconfirmed
                        balance_litoshis = data.get('balance', 0) + data.get('unconfirmed_balance', 0)
                        
                        # If address is strictly one-time use, balance or total_received are both fine.
                        # We use total_received in case they pay in multiple txs and we sweep it? 
                        # Let's use total_received + unconfirmed_balance for checking.
                        total_received_litoshis = data.get('total_received', 0) + max(0, data.get('unconfirmed_balance', 0))
                        
                        received_ltc = Decimal(total_received_litoshis) / Decimal('100000000')
                        
                        logger.info(f"LTC Check for {address}: Found {received_ltc} LTC, expected {expected_amount}")
                        return received_ltc >= expected_amount
                    else:
                        logger.warning(f"Blockcypher API error for {address}: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Error checking LTC balance for {address}: {e}")
            
        return False
