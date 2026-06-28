from core.identifiers import IdentifierService, VALID_PREFIXES

def test_validate_valid():
    svc = IdentifierService.__new__(IdentifierService)
    assert svc.validate("EVID-0001") is True
    assert svc.validate("DEC-0042") is True
    assert svc.validate("WP-9999") is True

def test_validate_invalid_prefix():
    svc = IdentifierService.__new__(IdentifierService)
    assert svc.validate("FOO-0001") is False

def test_validate_bad_format():
    svc = IdentifierService.__new__(IdentifierService)
    assert svc.validate("EVID-1") is False
    assert svc.validate("EVID") is False
    assert svc.validate("EVID-ABCD") is False

def test_valid_prefixes():
    assert "EVID" in VALID_PREFIXES
    assert "DEC" in VALID_PREFIXES
    assert "WP" in VALID_PREFIXES
    assert "ER" in VALID_PREFIXES
