import os
import logging
import aiohttp
from decimal import Decimal
from bot.payments.checkers.base import BaseChecker

from bot.config.env import EnvKeys

logger = logging.getLogger(__name__)

SPL_TOKENS = {
    'USDT-SPL': {
        'mint': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
        'decimals': 6
    },
    'USDC-SPL': {
        'mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'decimals': 6
    }
}

class SolanaChecker(BaseChecker):
    def __init__(self):
        # Allow custom RPC via environment variable
        env_rpc = os.getenv('SOLANA_RPC_URL')
        if env_rpc:
            self.rpc_url = env_rpc
        elif EnvKeys.USE_TESTNET:
            self.rpc_url = 'https://api.devnet.solana.com'
        else:
            self.rpc_url = 'https://api.mainnet-beta.solana.com'

    async def check_payment(self, address: str, expected_amount: Decimal, currency: str, **kwargs) -> bool:
        if currency == 'SOL':
            return await self._check_sol(address, expected_amount)
        elif currency in SPL_TOKENS:
            return await self._check_spl(address, expected_amount, currency)
        else:
            logger.error(f"Unsupported Solana currency: {currency}")
            return False

    async def _check_sol(self, address: str, expected_amount: Decimal) -> bool:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.rpc_url, json=payload) as response:
                    data = await response.json()
                    if 'result' in data:
                        lamports = data['result']['value']
                        sol_balance = Decimal(lamports) / Decimal('1000000000')
                        
                        logger.info(f"SOL Check for {address}: Found {sol_balance} SOL, expected {expected_amount}")
                        return sol_balance >= expected_amount
                    else:
                        logger.warning(f"Solana RPC error for {address}: {data}")
        except Exception as e:
            logger.error(f"Error checking SOL balance for {address}: {e}")
            
        return False

    async def _check_spl(self, address: str, expected_amount: Decimal, currency: str) -> bool:
        token_info = SPL_TOKENS[currency]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": token_info['mint']},
                {"encoding": "jsonParsed"}
            ]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.rpc_url, json=payload) as response:
                    data = await response.json()
                    if 'result' in data:
                        accounts = data['result']['value']
                        
                        total_token_balance = Decimal('0')
                        for acc in accounts:
                            try:
                                amount_str = acc['account']['data']['parsed']['info']['tokenAmount']['uiAmountString']
                                total_token_balance += Decimal(amount_str)
                            except KeyError:
                                continue
                                
                        logger.info(f"{currency} Check for {address}: Found {total_token_balance}, expected {expected_amount}")
                        return total_token_balance >= expected_amount
                    else:
                        logger.warning(f"Solana RPC error for {address} ({currency}): {data}")
        except Exception as e:
            logger.error(f"Error checking {currency} balance for {address}: {e}")
            
        return False
