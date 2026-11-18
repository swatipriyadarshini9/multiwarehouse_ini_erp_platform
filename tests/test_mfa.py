from app.services.mfa import new_totp_secret, provisioning_uri, verify_totp


def test_totp_roundtrip():
    secret = new_totp_secret()
    import pyotp

    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "000000")


def test_provisioning_uri_contains_issuer():
    uri = provisioning_uri("JBSWY3DPEHPK3PXP", "opsadmin")
    assert "OpenSource" in uri
    assert "otpauth://" in uri