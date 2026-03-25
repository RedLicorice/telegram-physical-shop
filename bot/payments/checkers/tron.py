import os
import logging
import aiohttp
from decimal import Decimal
from bot.payments.checkers.base import BaseChecker

logger = logging.getLogger(__name__)

TRC20_TOKENS = {
    'USDT-TRC20': {
        'contract': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
        'decimals': 6
    },
    'USDC-TRC20': {
        'contract': 'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8',  # This can vary, but typically TEkxi...
        'decimals': 6
    }
}

class TronChecker(BaseChecker):
    def __init__(self):
        self.api_key = os.getenv('TRONGRID_API_KEY', '')
        self.base_url = "https://api.trongrid.io/v1/accounts"

    async def check_payment(self, address: str, expected_amount: Decimal, currency: str, **kwargs) -> bool:
        """
        Check Tron payment (TRX or TRC20).
        Since Trongrid returns all assets in one call, we fetch the account and check the requested asset.
        """
        if currency not in ['TRX'] and currency not in TRC20_TOKENS:
            logger.error(f"Unsupported Tron currency: {currency}")
            return False

        headers = {}
        if self.api_key:
            headers['TRON-PRO-API-KEY'] = self.api_key

        try:
            url = f"{self.base_url}/{address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    # Trongrid sometimes returns 404 for newly generated unfunded accounts
                    if response.status == 404:
                        return False
                        
                    if response.status == 200:
                        data = await response.json()
                        if data.get('success', False) and data.get('data'):
                            account_info = data['data'][0]
                            
                            if currency == 'TRX':
                                sun_balance = account_info.get('balance', 0)
                                trx_balance = Decimal(sun_balance) / Decimal('1000000')
                                
                                logger.info(f"TRX Check for {address}: Found {trx_balance} TRX, expected {expected_amount}")
                                return trx_balance >= expected_amount
                                
                            else:
                                # Checking a TRC20 Token
                                target_contract = TRC20_TOKENS[currency]['contract']
                                token_decimals = TRC20_TOKENS[currency]['decimals']
                                
                                trc20_list = account_info.get('trc20', [])
                                token_raw_balance = Decimal('0')
                                
                                for mapping in trc20_list:
                                    if target_contract in mapping:
                                        token_raw_balance = Decimal(mapping[target_contract])
                                        break
                                
                                token_balance = token_raw_balance / Decimal(10 ** token_decimals)
                                logger.info(f"{currency} Check for {address}: Found {token_balance}, expected {expected_amount}")
                                return token_balance >= expected_amount
                        else:
                            # Not an error: account just doesn't exist on-chain yet (unfunded)
                            pass
                    else:
                        logger.warning(f"TronGrid API error for {address}: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Error checking {currency} balance for {address}: {e}")
            
        return False
