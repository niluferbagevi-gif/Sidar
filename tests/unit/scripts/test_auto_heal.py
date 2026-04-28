from scripts.auto_heal import _parse_approval_value


def test_parse_approval_value_accepts_short_and_tr_aliases() -> None:
    assert _parse_approval_value("e") is True
    assert _parse_approval_value("evet") is True
    assert _parse_approval_value("h") is False
    assert _parse_approval_value("hayır") is False


def test_parse_approval_value_accepts_en_boolean_aliases() -> None:
    assert _parse_approval_value("yes") is True
    assert _parse_approval_value("true") is True
    assert _parse_approval_value("1") is True
    assert _parse_approval_value("no") is False
    assert _parse_approval_value("false") is False
    assert _parse_approval_value("0") is False


def test_parse_approval_value_returns_none_for_unknown() -> None:
    assert _parse_approval_value(None) is None
    assert _parse_approval_value("") is None
    assert _parse_approval_value("maybe") is None
