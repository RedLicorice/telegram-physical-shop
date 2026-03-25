import logging
import threading
import time
from pathlib import Path
from typing import Optional, Dict

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from bot.payments.crypto import CHAIN_FILES, load_crypto_addresses_from_file

logger = logging.getLogger(__name__)


class CryptoAddressFileHandler(FileSystemEventHandler):
    """
    Handler for file system events on crypto address text files.
    Implements debouncing to prevent multiple rapid reloads.
    """

    def __init__(self, watch_files: Dict[str, Path], debounce_seconds: float = 2.0):
        super().__init__()
        self.watch_files = watch_files  # map of chain -> Path
        self.debounce_seconds = debounce_seconds
        
        # Debounce tracking per chain
        self.last_reload_time = {chain: 0.0 for chain in watch_files}
        self._reload_lock = threading.Lock()

        logger.info(f"CryptoAddressFileHandler initialized for watching {len(watch_files)} files.")

    def on_modified(self, event):
        if event.is_directory:
            return

        event_path = Path(event.src_path).resolve()
        
        # Find which chain this file belongs to
        matched_chain = None
        for chain, fpath in self.watch_files.items():
            if event_path == fpath.resolve():
                matched_chain = chain
                break
                
        if not matched_chain:
            return

        current_time = time.time()
        with self._reload_lock:
            time_since_last_reload = current_time - self.last_reload_time[matched_chain]

            if time_since_last_reload < self.debounce_seconds:
                logger.debug(
                    f"Debouncing file change event for {matched_chain} (last reload was "
                    f"{time_since_last_reload:.1f}s ago, minimum is {self.debounce_seconds}s)"
                )
                return

            self.last_reload_time[matched_chain] = current_time

        self._reload_addresses(matched_chain, event_path.name)

    def _reload_addresses(self, chain: str, file_name: str):
        try:
            logger.info(f"📥 Detected change in {file_name}, reloading {chain} addresses...")

            loaded_count = load_crypto_addresses_from_file(chain)

            if loaded_count > 0:
                logger.info(f"✅ Successfully loaded {loaded_count} new {chain} address(es)")
            else:
                logger.info(f"ℹ️  No new {chain} addresses to load")

        except Exception as e:
            logger.error(f"❌ Error reloading {chain} addresses: {e}", exc_info=True)


class CryptoAddressFileWatcher:
    """
    File system watcher for multiple crypto address files.
    """

    def __init__(self, debounce_seconds: float = 2.0):
        self.watch_files = CHAIN_FILES
        # All files are assumed to be in the root directory (same as bot_cli.py)
        # Using the parent directory of the first file (or current working directory)
        self.watch_directory = Path('.').resolve()
        self.debounce_seconds = debounce_seconds

        self.observer: Optional[Observer] = None
        self.event_handler: Optional[CryptoAddressFileHandler] = None

        self._started = False
        self._start_lock = threading.Lock()

        logger.info(f"CryptoAddressFileWatcher created for {len(self.watch_files)} files")

    def start(self):
        with self._start_lock:
            if self._started:
                logger.warning("File watcher is already running")
                return False

            self.event_handler = CryptoAddressFileHandler(
                self.watch_files,
                self.debounce_seconds
            )
            self.observer = Observer()

            self.observer.schedule(
                self.event_handler,
                str(self.watch_directory),
                recursive=False
            )

            self.observer.start()
            self._started = True

            logger.info(f"🔍 File watcher started for crypto addresses (debounce: {self.debounce_seconds}s)")
            return True

    def stop(self, timeout: float = 5.0):
        with self._start_lock:
            if not self._started:
                logger.warning("File watcher is not running")
                return False

            if self.observer:
                logger.info("Stopping file watcher...")
                self.observer.stop()
                self.observer.join(timeout=timeout)

                if self.observer.is_alive():
                    logger.warning(
                        f"File watcher thread did not stop within {timeout}s timeout"
                    )
                else:
                    logger.info("✅ File watcher stopped successfully")

                self.observer = None

            self.event_handler = None
            self._started = False
            return True

    def is_running(self) -> bool:
        return self._started and self.observer is not None and self.observer.is_alive()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


# Global singleton instance
_watcher_instance: Optional[CryptoAddressFileWatcher] = None
_watcher_lock = threading.Lock()


def get_file_watcher() -> CryptoAddressFileWatcher:
    global _watcher_instance
    with _watcher_lock:
        if _watcher_instance is None:
            _watcher_instance = CryptoAddressFileWatcher()
        return _watcher_instance


def start_file_watcher() -> bool:
    watcher = get_file_watcher()
    return watcher.start()


def stop_file_watcher(timeout: float = 5.0) -> bool:
    global _watcher_instance
    with _watcher_lock:
        if _watcher_instance is not None:
            result = _watcher_instance.stop(timeout)
            _watcher_instance = None
            return result
        return False
