from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from .config import database_url


@lru_cache
def get_engine():
    return create_engine(database_url(), pool_pre_ping=True, hide_parameters=True,
                         connect_args={'connect_timeout': 5, 'options': '-c statement_timeout=5000'})


def get_session():
    with Session(get_engine()) as session:
        yield session
