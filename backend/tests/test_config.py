from app.config import database_url


def test_literal_password_and_environment_priority(tmp_path, monkeypatch):
    for key in ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD'):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / '.env'
    config.write_text('PGPASSWORD="a#b%@:/$word"\nPGDATABASE=sample\nPGPORT=5433', encoding='utf-8')
    url = database_url(config)
    assert url.password == 'a#b%@:/$word'
    assert url.port == 5433
    monkeypatch.setenv('PGDATABASE', 'override')
    assert database_url(config).database == 'override'
    assert 'a#b' not in str(url)
