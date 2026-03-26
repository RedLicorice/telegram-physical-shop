import os
import logging
import aiohttp
from decimal import Decimal
from bot.payments.checkers.base import BaseChecker

from bot.config.env import EnvKeys

logger = logging.getLogger(__name__)

# Constants for ERC20 Tokens (Decimals and Contract Addresses)
# Note: These are mainnet addresses. Testnet equivalents may vary.
ERC20_TOKENS = {
    'USDT-ERC20': {
        'contract': '0xdac17f958d2ee523a2206206994597c13d831ec7',
        'decimals': 6
    },
    'USDC-ERC20': {
        'contract': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
        'decimals': 6
    }
}

class EthereumChecker(BaseChecker):
    def __init__(self):
        self.api_key = os.getenv('ETHERSCAN_API_KEY', '')
        if EnvKeys.USE_TESTNET:
            # Using Sepolia as the default testnet
            self.base_url = "https://api-sepolia.etherscan.io/api"
        else:
            self.base_url = "https://api.etherscan.io/api"

    async def check_payment(self, address: str, expected_amount: Decimal, currency: str, **kwargs) -> bool:
        if currency == 'ETH':
            return await self._check_eth(address, expected_amount)
        elif currency in ERC20_TOKENS:
            return await self._check_erc20(address, expected_amount, currency)
        else:
            logger.error(f"Unsupported Ethereum currency: {currency}")
            return False

    async def _check_eth(self, address: str, expected_amount: Decimal) -> bool:
        params = {
            'module': 'account',
            'action': 'balance',
            'address': address,
            'tag': 'latest',
            'apikey': self.api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params) as response:
                    data = await response.json()
                    if data.get('status') == '1':
                        wei_balance = Decimal(data['result'])
                        eth_balance = wei_balance / Decimal('1000000000000000000')
                        
                        logger.info(f"ETH Check for {address}: Found {eth_balance} ETH, expected {expected_amount}")
                        return eth_balance >= expected_amount
                    else:
                        logger.warning(f"Etherscan ETH API error for {address}: {data.get('message')}")
        except Exception as e:
            logger.error(f"Error checking ETH balance for {address}: {e}")
            
        return False

    async def _check_erc20(self, address: str, expected_amount: Decimal, currency: str) -> bool:
        token_info = ERC20_TOKENS[currency]
        params = {
            'module': 'account',
            'action': 'tokenbalance',
            'contractaddress': token_info['contract'],
            'address': address,
            'tag': 'latest',
            'apikey': self.api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params) as response:
                    data = await response.json()
                    if data.get('status') == '1':
                        raw_balance = Decimal(data['result'])
                        decimals = token_info['decimals']
                        token_balance = raw_balance / Decimal(10 ** decimals)
                        
                        logger.info(f"{currency} Check for {address}: Found {token_balance}, expected {expected_amount}")
                        return token_balance >= expected_amount
                    elif data.get('message') == 'OK' and data.get('result') == '0':
                        # Valid response but zero balance
                        return False
                    else:
                        logger.warning(f"Etherscan ERC20 API error for {address} ({currency}): {data.get('message')}")
        except Exception as e:
            logger.error(f"Error checking {currency} balance for {address}: {e}")
            
        return False
