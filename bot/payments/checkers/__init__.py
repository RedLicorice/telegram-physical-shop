from bot.payments.checkers.bitcoin import BitcoinChecker
from bot.payments.checkers.litecoin import LitecoinChecker
from bot.payments.checkers.ethereum import EthereumChecker
from bot.payments.checkers.solana import SolanaChecker
from bot.payments.checkers.tron import TronChecker

# Map currencies to their respective checker instances
# Using a factory or singleton approach.

class PaymentCheckerFactory:
    _checkers = {}
    
    @classmethod
    def get_checker(cls, currency: str):
        if currency == 'BTC':
            if 'BTC' not in cls._checkers:
                cls._checkers['BTC'] = BitcoinChecker()
            return cls._checkers['BTC']
            
        elif currency == 'LTC':
            if 'LTC' not in cls._checkers:
                cls._checkers['LTC'] = LitecoinChecker()
            return cls._checkers['LTC']
            
        elif currency in ['ETH', 'USDT-ERC20', 'USDC-ERC20']:
            if 'ETH_FAMILY' not in cls._checkers:
                cls._checkers['ETH_FAMILY'] = EthereumChecker()
            return cls._checkers['ETH_FAMILY']
            
        elif currency in ['SOL', 'USDT-SPL', 'USDC-SPL']:
            if 'SOL_FAMILY' not in cls._checkers:
                cls._checkers['SOL_FAMILY'] = SolanaChecker()
            return cls._checkers['SOL_FAMILY']
            
        elif currency in ['TRX', 'USDT-TRC20', 'USDC-TRC20']:
            if 'TRX_FAMILY' not in cls._checkers:
                cls._checkers['TRX_FAMILY'] = TronChecker()
            return cls._checkers['TRX_FAMILY']
            
        return None
