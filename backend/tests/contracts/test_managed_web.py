"""Managed installation preserves the browser cookie/origin contract."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("origin", ["http://192.168.2.40:8000", "http://192.168.2.50:8000", "http://gjallar.home:8000"])
def test_bootstrap_external_web_origin_login_cookie_and_logout(monkeypatch, origin):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'client' / 'src'))
    from gjallar_client.bootstrap import compose_config
    from app.auth.users import create_user
    from app.main import app

    manifest = dict(version=3, id='test-install', image='test-image', postgres_image='test-pg', volume='test-volume', port=8000, bind_address='0.0.0.0')
    environment = compose_config(manifest)['services']['gjallar']['environment']
    for key in ('GJALLAR_ALLOWED_ORIGINS', 'GJALLAR_ALLOW_SAME_ORIGIN', 'GJALLAR_SESSION_COOKIE_SECURE', 'GJALLAR_SESSION_COOKIE_SAMESITE'):
        monkeypatch.setenv(key, environment[key])
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    create_user(username='web-reader', password='test-password', role='viewer')
    with TestClient(app, base_url=origin) as server:
        login = server.post('/api/v1/auth/login', headers={'Origin': origin}, json={'username': 'web-reader', 'password': 'test-password'})
        assert login.status_code == 200
        cookie = login.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=lax' in cookie and 'secure' not in cookie
        assert server.get('/api/v1/auth/me').json()['data']['user']['username'] == 'web-reader'
        denied = server.post('/api/v1/auth/logout', headers={'Origin': 'http://192.168.2.51:8000'})
        assert denied.status_code == 403 and denied.json()['detail']['code'] == 'FORBIDDEN_ORIGIN'
        assert server.get('/api/v1/auth/me').json()['data']['user']['username'] == 'web-reader'
        assert server.post('/api/v1/auth/logout', headers={'Origin': origin}).status_code == 200
        assert server.get('/api/v1/nodes').status_code == 401
