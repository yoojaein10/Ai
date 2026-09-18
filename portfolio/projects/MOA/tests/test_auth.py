import base64
import hashlib
import hmac

from pydantic import SecretStr

from app.amaranth.auth import AmaranthSigner
from app.config import Settings


def test_signer_builds_documented_headers() -> None:
    settings = Settings(
        a10_base_url="https://example.invalid",
        a10_caller_name="bridge-test",
        a10_access_token=SecretStr("access-token"),
        a10_hash_key=SecretStr("hash-key"),
        a10_group_seq="group-1",
    )
    signer = AmaranthSigner(
        settings,
        clock=lambda: 1_700_000_000,
        transaction_id_factory=lambda: "a" * 30,
    )

    headers = signer.build_headers("/apiproxy/api16S08")

    message = "access-token" + ("a" * 30) + "1700000000" + "/apiproxy/api16S08"
    expected = base64.b64encode(
        hmac.new(b"hash-key", message.encode(), hashlib.sha256).digest()
    ).decode()
    assert headers == {
        "callerName": "bridge-test",
        "Authorization": "Bearer access-token",
        "transaction-id": "a" * 30,
        "timestamp": "1700000000",
        "groupSeq": "group-1",
        "wehago-sign": expected,
        "Content-Type": "application/json",
    }

