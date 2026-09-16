"""Section 15.3: every malformed or misaddressed SERVIR login is refused."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from api.oidc import IdentityProviderError, ServirSigIdentityProvider
from api.settings import Settings

ISSUER = "https://identity.example.test"
RESOURCE = "https://servirplatform.sig-gis.com/mcp"
CLIENT_ID = "grp-client"
NONCE = "expected-nonce"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "sig-user-123",
        "nonce": NONCE,
        "email": "expert@example.test",
        "email_verified": True,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _exchange(tmp_path, id_token: str, userinfo: dict | None = None):
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True)
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(
                200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}
            )
        if path == "/.well-known/openid-configuration":
            document = {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
            if userinfo is not None:
                document["userinfo_endpoint"] = f"{ISSUER}/userinfo"
            return httpx.Response(200, json=document)
        if path == "/token":
            return httpx.Response(200, json={"id_token": id_token, "access_token": "token"})
        if path == "/jwks":
            return httpx.Response(200, json={"keys": [public_jwk]})
        if path == "/userinfo" and userinfo is not None:
            return httpx.Response(200, json=userinfo)
        return httpx.Response(404)

    settings = Settings(
        _env_file=None,
        grp_env="dev",
        sig_mcp_base_url=RESOURCE,
        servir_auth_issuer=ISSUER,
        servir_auth_client_id=CLIENT_ID,
        servir_auth_client_secret_file=tmp_path / "missing-secret",
        servir_auth_redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = ServirSigIdentityProvider(settings, client=client)
            return await provider.exchange_callback("code", NONCE, "verifier")

    return asyncio.run(run())


def _token(claims: dict[str, object], key=SIGNING_KEY, kid: str = "test-key") -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def test_valid_login_is_accepted(tmp_path) -> None:
    identity = _exchange(tmp_path, _token(_claims()))

    assert getattr(identity, "identity", identity).subject == "sig-user-123"


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param(_claims(aud="sig-mcp-client"), id="addressed-to-another-app"),
        pytest.param(_claims(iss="https://attacker.example.test"), id="wrong-issuer"),
        pytest.param(_claims(nonce="replayed-nonce"), id="wrong-nonce"),
        pytest.param(
            _claims(
                iat=int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
                exp=int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
            ),
            id="expired",
        ),
        pytest.param(_claims(nonce=None), id="missing-nonce"),
    ],
)
def test_misaddressed_or_stale_login_is_denied(tmp_path, claims) -> None:
    with pytest.raises(IdentityProviderError):
        _exchange(tmp_path, _token(claims))


def test_login_signed_by_unknown_key_is_denied(tmp_path) -> None:
    with pytest.raises(IdentityProviderError):
        _exchange(tmp_path, _token(_claims(), key=FOREIGN_KEY))


def test_login_with_unlisted_key_id_is_denied(tmp_path) -> None:
    with pytest.raises(IdentityProviderError):
        _exchange(tmp_path, _token(_claims(), kid="other-key"))


def test_unverified_email_is_denied(tmp_path) -> None:
    with pytest.raises(IdentityProviderError):
        _exchange(tmp_path, _token(_claims(email_verified=False)))


def test_userinfo_for_a_different_subject_is_denied(tmp_path) -> None:
    token = _token(_claims(email=None, email_verified=None))
    with pytest.raises(IdentityProviderError):
        _exchange(
            tmp_path,
            token,
            userinfo={"sub": "someone-else", "email": "x@example.test", "email_verified": True},
        )
