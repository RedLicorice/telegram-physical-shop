import os
from pathlib import Path
from typing import List, Tuple, Optional


def _load_bip_utils():
    """Lazy-load bip_utils to avoid 8s+ import at startup."""
    from bip_utils import (
        Bip39MnemonicGenerator, Bip39SeedGenerator, Bip39WordsNum,
        Bip44, Bip44Coins, Bip44Changes,
        Bip49, Bip49Coins,
        Bip84, Bip84Coins
    )
    return {
        'Bip39MnemonicGenerator': Bip39MnemonicGenerator,
        'Bip39SeedGenerator': Bip39SeedGenerator,
        'Bip39WordsNum': Bip39WordsNum,
        'Bip44': Bip44, 'Bip44Coins': Bip44Coins, 'Bip44Changes': Bip44Changes,
        'Bip49': Bip49, 'Bip49Coins': Bip49Coins,
        'Bip84': Bip84, 'Bip84Coins': Bip84Coins,
    }


class WalletManager:
    """
    Manages BIP-based wallet generation and address derivation for multiple chains.
    """

    CHAIN_CONFIG = None  # Populated on first use

    @classmethod
    def _ensure_config(cls):
        if cls.CHAIN_CONFIG is not None:
            return
        bip = _load_bip_utils()
        cls.CHAIN_CONFIG = {
            "BTC": {"class": bip['Bip84'], "coin": bip['Bip84Coins'].BITCOIN},
            "ETH": {"class": bip['Bip44'], "coin": bip['Bip44Coins'].ETHEREUM},
            "LTC": {"class": bip['Bip84'], "coin": bip['Bip84Coins'].LITECOIN},
            "SOL": {"class": bip['Bip44'], "coin": bip['Bip44Coins'].SOLANA},
            "TRX": {"class": bip['Bip44'], "coin": bip['Bip44Coins'].TRON},
        }
        # Also store references we need in methods
        cls._bip = bip

    def __init__(self, wallets_dir: str = "config/wallets"):
        self.wallets_dir = Path(wallets_dir)
        self.wallets_dir.mkdir(parents=True, exist_ok=True)

    def get_public_file(self, chain: str) -> Path:
        return self.wallets_dir / f"{chain.lower()}.public.txt"

    def get_private_file(self, chain: str) -> Path:
        return self.wallets_dir / f"{chain.lower()}.private.txt"

    def generate_keypair(self, chain: str) -> Tuple[str, str, str]:
        """
        Generates a new mnemonic and derived public/private keys.

        Returns:
            Tuple[str, str, str]: (mnemonic, encoded_public_key, encoded_private_key)
        """
        self._ensure_config()
        chain = chain.upper()
        if chain not in self.CHAIN_CONFIG:
            raise ValueError(f"Unsupported chain: {chain}")

        bip = self._bip
        # 1. Generate 12-word mnemonic
        mnemonic = bip['Bip39MnemonicGenerator']().FromWordsNumber(bip['Bip39WordsNum'].WORDS_NUM_12)

        # 2. Generate seed
        seed_bytes = bip['Bip39SeedGenerator'](mnemonic).Generate()

        # 3. Create Bip object
        config = self.CHAIN_CONFIG[chain]
        bip_obj = config["class"].FromSeed(seed_bytes, config["coin"])
        
        # 4. Get Master Public/Private keys (Extended keys if supported)
        # BTC/ETH/LTC/TRX/SOL all use Account 0, Change 0 (Internal/External)
        # We derive Account 0 to get the XPUB that can derive addresses.
        account_0 = bip_obj.Purpose().Coin().Account(0)
        public_key = account_0.PublicKey().ToExtended()
        private_key = account_0.PrivateKey().ToExtended()

        # Save to files
        self._save_keys(chain, mnemonic, public_key, private_key)
        
        return str(mnemonic), public_key, private_key

    def import_wallet(self, chain: str, mnemonic: Optional[str] = None, public_key: Optional[str] = None):
        """
        Imports an existing mnemonic or public key (XPUB).
        """
        self._ensure_config()
        chain = chain.upper()
        if chain not in self.CHAIN_CONFIG:
            raise ValueError(f"Unsupported chain: {chain}")

        if not mnemonic and not public_key:
            raise ValueError("Either mnemonic or public_key must be provided.")

        config = self.CHAIN_CONFIG[chain]

        if mnemonic:
            # Validate mnemonic and derive keys
            seed_bytes = self._bip['Bip39SeedGenerator'](mnemonic).Generate()
            bip_obj = config["class"].FromSeed(seed_bytes, config["coin"])
            
            account_0 = bip_obj.Purpose().Coin().Account(0)
            derived_pub = account_0.PublicKey().ToExtended()
            derived_priv = account_0.PrivateKey().ToExtended()
            
            # If public_key was also provided, verify it matches
            if public_key and public_key != derived_pub:
                raise ValueError(f"Provided public key does not match mnemonic! Derived: {derived_pub}")
            
            self._save_keys(chain, mnemonic, derived_pub, derived_priv)
            return derived_pub
        else:
            # Public key only (can only be used for derivation, no private key stored)
            # Validate public key by attempting to load it
            try:
                config["class"].FromExtendedKey(public_key, config["coin"])
            except Exception as e:
                raise ValueError(f"Invalid public key for {chain}: {e}")

            public_path = self.get_public_file(chain)
            with open(public_path, "w") as f:
                f.write(public_key)
            
            # Remove private key file if it exists to avoid confusion
            private_path = self.get_private_file(chain)
            if private_path.exists():
                private_path.unlink()
                
            return public_key

    def _save_keys(self, chain: str, mnemonic: str, public_key: str, private_key: str):
        """Saves keys to the wallets directory."""
        chain = chain.lower()
        public_path = self.get_public_file(chain)
        private_path = self.get_private_file(chain)

        # Public key only
        with open(public_path, "w") as f:
            f.write(public_key)

        # Private key + Mnemonic (Secure this file!)
        with open(private_path, "w") as f:
            f.write(f"Mnemonic: {mnemonic}\n")
            f.write(f"Private Key: {private_key}\n")

    def derive_addresses(self, chain: str, start_index: int, count: int) -> List[str]:
        """
        Derives addresses from an extended public key found in config/wallets/.
        """
        self._ensure_config()
        chain = chain.upper()
        public_path = self.get_public_file(chain)

        if not public_path.exists():
            raise FileNotFoundError(f"Public key for {chain} not found at {public_path}. Please generate or add it.")

        with open(public_path, "r") as f:
            extended_pub_key = f.read().strip()

        config = self.CHAIN_CONFIG[chain]

        # Reconstruct Bip object from Extended Public Key
        bip_obj = config["class"].FromExtendedKey(extended_pub_key, config["coin"])

        addresses = []
        for i in range(start_index, start_index + count):
            child = bip_obj.Change(self._bip['Bip44Changes'].CHAIN_EXT).AddressIndex(i)
            addresses.append(child.PublicKey().ToAddress())
            
        return addresses

    def get_public_key(self, chain: str) -> Optional[str]:
        """Reads the public key from the file."""
        public_path = self.get_public_file(chain)
        if public_path.exists():
            with open(public_path, "r") as f:
                return f.read().strip()
        return None
