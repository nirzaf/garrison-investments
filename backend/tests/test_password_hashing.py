from app.utils.security import hash_password, verify_password


def test_new_password_hashes_can_be_verified() -> None:
    password = "fixture-only-example"
    password_hash = hash_password(password)

    assert verify_password(password, password_hash)
    assert not verify_password("different-fixture", password_hash)


def test_existing_passlib_bcrypt_hashes_can_be_verified() -> None:
    # Created with Passlib 1.7.4 using a synthetic password and test-only cost.
    legacy_hash = "$2b$04$Vs4P8kEGNhraLla7Ba4GeOKum3lUDgptRD5xD3ic4PkTPvXBut2Gy"

    assert verify_password("fixture-only-example", legacy_hash)
    assert not verify_password("fixture-only-example\x00", legacy_hash)
