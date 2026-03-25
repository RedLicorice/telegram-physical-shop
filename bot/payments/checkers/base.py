from abc import ABC, abstractmethod
from typing import Optional
from decimal import Decimal


class BaseChecker(ABC):
    """
    Base interface for cryptocurrency payment checkers.
    """

    @abstractmethod
    async def check_payment(self, address: str, expected_amount: Decimal, currency: str, **kwargs) -> bool:
        """
        Check if the expected amount has been received on the given address.
        
        :param address: Cryptocurrency address to check.
        :param expected_amount: The exact expected amount formatted as Decimal.
        :param currency: The currency string (e.g., 'BTC', 'ETH', 'USDT-ERC20').
        :return: True if the exact or greater amount was received, False otherwise.
        """
        pass
