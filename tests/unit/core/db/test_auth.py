import pytest

from core.db import auth as db_auth


@pytest.mark.parametrize(
    ("memory_cost", "expected_time_cost"),
    [
        (9215, 5),
        (12287, 4),
        (19455, 3),
        (47103, 2),
        (47104, 1),
    ],
)
def test_minimum_argon2id_time_cost_owasp_ladder_boundaries(memory_cost, expected_time_cost):
    assert db_auth._minimum_argon2id_time_cost(memory_cost) == expected_time_cost


@pytest.mark.parametrize(
    "params_text",
    [
        "m=19456,t=2,p",  # missing separator/value for one item
        "m=19456,t=2,x=1",  # unknown key
        "m=19456,t=bad,p=1",  # non-integer value
        "m=19456,t=2",  # missing required key
    ],
)
def test_parse_argon2id_params_rejects_malformed_inputs(params_text):
    assert db_auth._parse_argon2id_params(params_text) is None


def test_verify_argon2id_password_rejects_malformed_and_unhashable_inputs(monkeypatch):
    assert db_auth._verify_argon2id_password("pw", ["argon2id", "too-short"]) is False

    monkeypatch.setattr(
        db_auth,
        "_argon2id_hash",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad salt")),
    )
    assert (
        db_auth._verify_argon2id_password(
            "pw",
            [
                db_auth._ARGON2ID_ALGORITHM,
                f"v={db_auth._ARGON2ID_VERSION}",
                "m=19456,t=2,p=1",
                "not-hex",
                "digest",
            ],
        )
        is False
    )


@pytest.mark.parametrize(
    "parts",
    [
        ["not_pbkdf2", "600000", "salt", "digest"],
        [db_auth._PBKDF2_ALGORITHM, "not-an-int", "salt", "digest"],
        ["not_pbkdf2", "salt", "digest"],
        [db_auth._PBKDF2_ALGORITHM, "too", "many", "parts", "digest"],
    ],
)
def test_verify_pbkdf2_password_rejects_malformed_inputs(parts):
    assert db_auth._verify_pbkdf2_password("pw", parts) is False


def test_verify_pbkdf2_password_compares_four_part_digest(monkeypatch):
    monkeypatch.setattr(db_auth, "_pbkdf2_sha256", lambda *_args: "digest")

    assert (
        db_auth._verify_pbkdf2_password(
            "pw", [db_auth._PBKDF2_ALGORITHM, "600000", "salt", "digest"]
        )
        is True
    )
