import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, Engine, QueuePool, event
from sqlalchemy.orm import declarative_base, sessionmaker, Query

from bot.database.dsn import dsn
from bot.utils import SingletonMeta


class Database(metaclass=SingletonMeta):
    BASE = declarative_base()

    def __init__(self):
        url = dsn()
        is_sqlite = url.startswith("sqlite")

        if is_sqlite:
            self.__engine: Engine = create_engine(
                url,
                echo=False,
                future=True,
                connect_args={"check_same_thread": False},
            )
            logging.info(f"SQLite database initialized: {url}")

            # Enable WAL mode and foreign keys for SQLite
            @event.listens_for(self.__engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            # Make with_for_update() a no-op on SQLite
            Query.with_for_update = lambda self, **kw: self
        else:
            self.__engine: Engine = create_engine(
                url,
                echo=False,
                pool_pre_ping=True,
                future=True,
                poolclass=QueuePool,
                pool_size=20,
                max_overflow=40,
                pool_timeout=30,
                pool_recycle=3600,
                connect_args={
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=30000"
                }
            )
            logging.info(f"Database pool initialized: size={20}, max_overflow={40}")

        self.__SessionLocal = sessionmaker(bind=self.__engine, autoflush=False, autocommit=False, future=True,
                                           expire_on_commit=False)

    @contextmanager
    def session(self):
        """Contextual session: guaranteed to close/rollback on error."""
        db = self.__SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @property
    def engine(self) -> Engine:
        return self.__engine
