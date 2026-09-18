import hashlib

from app.services.auth import password_hash_candidates, verify_password_hash


def test_password_hash_candidates_include_plain_sha256():
    candidates = password_hash_candidates("4210", "secret1!")
    assert hashlib.sha256(b"secret1!").hexdigest() in candidates


def test_password_hash_candidates_cover_case_and_id_salt_variants():
    candidates = password_hash_candidates("4210", "Abc")
    expected = {
        hashlib.sha256(b"Abc").hexdigest(),
        hashlib.sha256(b"ABC").hexdigest(),
        hashlib.sha256(b"abc").hexdigest(),
        hashlib.sha256(b"4210Abc").hexdigest(),
        hashlib.sha256(b"Abc4210").hexdigest(),
    }
    assert expected.issubset(set(candidates))
    assert len(candidates) == len(set(candidates))  # 중복 제거


def test_verify_password_hash_matches_stored_hex_case_insensitive():
    stored = hashlib.sha256(b"pw123").hexdigest().upper()
    assert verify_password_hash("4210", "pw123", stored) is True
    assert verify_password_hash("4210", "wrong", stored) is False


def test_verify_password_hash_accepts_legacy_plaintext():
    # 일부 계정(1건)은 평문 저장 — 그대로 비교
    assert verify_password_hash("4210", "old-pass-13", "old-pass-13") is True
    assert verify_password_hash("4210", "nope", "old-pass-13") is False
