# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

import asyncio
from pathlib import Path

from core.db import Database, _hash_password, _verify_password


class _Cfg:
    def __init__(self, tmp_path: Path):
        self.DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'extra.sqlite').as_posix()}"
        self.DB_POOL_SIZE = 2
        self.DB_SCHEMA_VERSION_TABLE = "schema_versions"
        self.DB_SCHEMA_TARGET_VERSION = 1
        self.BASE_DIR = tmp_path


def test_password_helpers_handle_valid_and_invalid_payloads():
    encoded = _hash_password("secret")
    assert encoded.startswith("pbkdf2_sha256$")
    assert _verify_password("secret", encoded) is True
    assert _verify_password("wrong", encoded) is False
    assert _verify_password("secret", "broken") is False
    assert _verify_password("secret", "sha1$salt$abcd") is False


def test_sqlite_user_auth_quota_and_session_flows(tmp_path: Path):
    db = Database(cfg=_Cfg(tmp_path))

    async def _run():
        await db.connect()
        await db.init_schema()

        user = await db.register_user("quota_user", "pw", role="admin")
        assert user.role == "admin"

        same_user = await db.ensure_user("quota_user", role="user")
        assert same_user.id == user.id

        assert await db.authenticate_user("quota_user", "pw") is not None
        assert await db.authenticate_user("quota_user", "bad") is None
        assert await db.authenticate_user("missing", "pw") is None

        token = await db.create_auth_token(user.id, ttl_days=0)
        assert token.user_id == user.id
        assert await db.get_user_by_token(token.token) is not None
        assert await db.get_user_by_token("not-a-token") is None

        await db.upsert_user_quota(user.id, daily_token_limit=500, daily_request_limit=10)
        await db.record_provider_usage_daily(user.id, "OpenAI", tokens_used=42, requests_inc=2)
        await db.record_provider_usage_daily(user.id, "OpenAI", tokens_used=8, requests_inc=1)
        status = await db.get_user_quota_status(user.id, "openai")
        assert status["tokens_used"] == 50
        assert status["requests_used"] == 3
        assert status["token_limit_exceeded"] is False
        assert status["request_limit_exceeded"] is False

        users = await db.list_users_with_quotas()
        assert users and users[0]["username"] == "quota_user"

        stats = await db.get_admin_stats()
        assert stats["total_users"] == 1
        assert stats["total_tokens_used"] == 50
        assert stats["total_api_requests"] == 3

        sess = await db.create_session(user.id, "first")
        assert await db.update_session_title(sess.id, "renamed") is True
        assert await db.update_session_title("missing", "x") is False

        msg = await db.add_message(sess.id, "user", "hello", tokens_used=5)
        assert msg.tokens_used == 5
        history = await db.get_session_messages(sess.id)
        assert len(history) == 1

        sessions = await db.list_sessions(user.id)
        assert len(sessions) == 1
        loaded = await db.load_session(sess.id, user_id=user.id)
        assert loaded is not None and loaded.title == "renamed"

        assert await db.delete_session(sess.id, user_id="someone-else") is False
        assert await db.delete_session(sess.id, user_id=user.id) is True
        assert await db.delete_session("missing") is False

        await db.close()

    asyncio.run(_run())