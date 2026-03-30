import threading
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from bot.database.main import Database
from bot.database.models.main import CryptoAddress
from bot.export.custom_logging import log_bitcoin_address_assigned

# Mapping of chains to their respective address files
CHAIN_FILES = {
    'BTC': Path("config/btc_addresses.txt"),
    'ETH': Path("config/eth_addresses.txt"),
    'LTC': Path("config/ltc_addresses.txt"),
    'SOL': Path("config/sol_addresses.txt"),
    'TRX': Path("config/trx_addresses.txt"),
}

# A lock per chain for thread-safe file operations
_file_locks = {chain: threading.Lock() for chain in CHAIN_FILES}


def get_chain_file(chain: str) -> Path:
    if chain not in CHAIN_FILES:
        raise ValueError(f"Unknown chain: {chain}")
    return CHAIN_FILES[chain]


def get_chain_lock(chain: str) -> threading.Lock:
    if chain not in _file_locks:
        _file_locks[chain] = threading.Lock()
    return _file_locks[chain]


def load_crypto_addresses_from_file(chain: str) -> int:
    """
    Load crypto addresses from text file into the database for the given chain.
    """
    file_path = get_chain_file(chain)
    lock = get_chain_lock(chain)

    if not file_path.exists():
        file_path.touch()
        return 0

    with lock:
        with open(file_path, 'r') as f:
            addresses = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith('#')
            ]

    if not addresses:
        return 0

    loaded_count = 0
    with Database().session() as session:
        for address in addresses:
            existing = session.query(CryptoAddress).filter_by(chain=chain, address=address).first()
            if not existing:
                crypto_addr = CryptoAddress(chain=chain, address=address)
                session.add(crypto_addr)
                loaded_count += 1

        session.commit()

    return loaded_count


def get_available_crypto_address(chain: str) -> Optional[str]:
    """
    Get an available (unused) crypto address for the given chain.
    """
    with Database().session() as session:
        crypto_addr = session.query(CryptoAddress).filter_by(chain=chain, is_used=False).first()
        if crypto_addr:
            return crypto_addr.address
    return None


def mark_crypto_address_used(chain: str, address: str, user_id: int, user_username: str,
                             order_id: int, session=None, order_code: str = None) -> bool:
    """
    Mark a crypto address as used and remove it from the specific file.
    """
    if session:
        crypto_addr = session.query(CryptoAddress).filter_by(chain=chain, address=address).first()
        if not crypto_addr:
            return False

        crypto_addr.is_used = True
        crypto_addr.used_by = user_id
        crypto_addr.used_at = datetime.now()
        crypto_addr.order_id = order_id
    else:
        with Database().session() as db_session:
            crypto_addr = db_session.query(CryptoAddress).filter_by(chain=chain, address=address).first()
            if not crypto_addr:
                return False

            crypto_addr.is_used = True
            crypto_addr.used_by = user_id
            crypto_addr.used_at = datetime.now()
            crypto_addr.order_id = order_id
            db_session.commit()

    remove_crypto_address_from_file(chain, address)

    # Reusing the bitcoin logging function as a generic crypto logging
    # In the future we might want a log_crypto_address_assigned
    log_bitcoin_address_assigned(address, order_id, user_id, user_username, order_code=order_code)

    return True


def remove_crypto_address_from_file(chain: str, address: str):
    """
    Remove a crypto address from the respective text file.
    """
    file_path = get_chain_file(chain)
    lock = get_chain_lock(chain)

    if not file_path.exists():
        return

    with lock:
        with open(file_path, 'r') as f:
            lines = [line.rstrip('\n') for line in f]

        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped != address:
                filtered_lines.append(line)

        with open(file_path, 'w') as f:
            for line in filtered_lines:
                f.write(f"{line}\n")


def add_crypto_address(chain: str, address: str) -> bool:
    """
    Add a new crypto address to the database and file.
    """
    with Database().session() as session:
        existing = session.query(CryptoAddress).filter_by(chain=chain, address=address).first()
        if existing:
            return False

        crypto_addr = CryptoAddress(chain=chain, address=address)
        session.add(crypto_addr)
        session.commit()

    file_path = get_chain_file(chain)
    lock = get_chain_lock(chain)

    with lock:
        with open(file_path, 'a') as f:
            f.write(f"{address}\n")

    return True


def add_crypto_addresses_bulk(chain: str, addresses: List[str]) -> int:
    added_count = 0

    with Database().session() as session:
        for address in addresses:
            existing = session.query(CryptoAddress).filter_by(chain=chain, address=address).first()
            if not existing:
                crypto_addr = CryptoAddress(chain=chain, address=address)
                session.add(crypto_addr)
                added_count += 1

        session.commit()

    if added_count > 0:
        file_path = get_chain_file(chain)
        lock = get_chain_lock(chain)
        with lock:
            with open(file_path, 'a') as f:
                for address in addresses:
                    f.write(f"{address}\n")

    return added_count


def get_crypto_address_stats(chain: str) -> dict:
    with Database().session() as session:
        total = session.query(CryptoAddress).filter_by(chain=chain).count()
        used = session.query(CryptoAddress).filter_by(chain=chain, is_used=True).count()
        available = total - used

        return {
            'total': total,
            'used': used,
            'available': available
        }
