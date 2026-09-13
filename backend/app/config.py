"""Read the root .env literally; nonempty environment variables take priority."""
import os
from pathlib import Path
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[2]


def database_url(env_file: Path = ROOT / '.env') -> URL:
    config = dict(PGHOST='127.0.0.1', PGPORT='5432', PGDATABASE='simulate_alipay', PGUSER='postgres', PGPASSWORD='')
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            key, separator, value = line.partition('=')
            key = key.strip()
            if separator and key in config:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                config[key] = value
    for key in config:
        config[key] = os.environ.get(key) or config[key]
    if any(not config[key].strip() for key in ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER')):
        raise ValueError('PostgreSQL connection fields must not be empty')
    port = int(config['PGPORT'])
    if not 1 <= port <= 65535:
        raise ValueError('PGPORT must be between 1 and 65535')
    return URL.create('postgresql+psycopg', username=config['PGUSER'], password=config['PGPASSWORD'],
                      host=config['PGHOST'], port=port, database=config['PGDATABASE'])
