import hashlib
import json

def test_checksum_deterministic():
    content = {"key": "value", "number": 42}
    c1 = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    c2 = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    assert c1 == c2

def test_checksum_changes_with_content():
    c1 = hashlib.sha256(json.dumps({"a": 1}, sort_keys=True).encode()).hexdigest()
    c2 = hashlib.sha256(json.dumps({"a": 2}, sort_keys=True).encode()).hexdigest()
    assert c1 != c2
