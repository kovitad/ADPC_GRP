import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from api.oidc import ServirSigIdentityProvider
from api.settings import Settings


@pytest.mark.parametrize("auth_method", ["client_secret_basic", "client_secret_post"])
def test_oidc_authorization_and_verified_callback(tmp_path, auth_method: str) -> None:
    issuer = "https://identity.example.test"
    client_id = "grp-client"
    nonce = "expected-nonce"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    now = datetime.now(UTC)
    id_token = jwt.encode(
        {
            "iss": issuer,
            "aud": client_id,
            "sub": "sig-user-123",
            "nonce": nonce,
            "email": "Expert@Example.test",
            "email_verified": True,
            "name": "Example Expert",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": f"{issuer}/authorize",
                    "token_endpoint": f"{issuer}/token",
                    "jwks_uri": f"{issuer}/jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "token_endpoint_auth_methods_supported": [auth_method],
                },
            )
        if request.url.path == "/token":
            form = parse_qs(request.content.decode("utf-8"))
            if auth_method == "client_secret_basic":
                assert request.headers["authorization"].startswith("Basic ")
                assert "client_secret" not in form
            else:
                assert "authorization" not in request.headers
                assert form["client_id"] == [client_id]
                assert form["client_secret"] == ["test-client-secret"]
            return httpx.Response(200, json={"id_token": id_token})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    secret_file = tmp_path / "oidc-secret"
    secret_file.write_text("test-client-secret", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        servir_auth_issuer=issuer,
        servir_auth_client_id=client_id,
        servir_auth_client_secret_file=secret_file,
        servir_auth_redirect_uri="https://grp.example.test/api/v1/auth/callback",
    )

    async def verify_flow() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = ServirSigIdentityProvider(settings, client=client)
            authorization_url = await provider.authorization_url("state-123", nonce, "challenge")
            parameters = parse_qs(urlparse(authorization_url).query)
            assert parameters["state"] == ["state-123"]
            assert parameters["nonce"] == [nonce]
            assert parameters["code_challenge_method"] == ["S256"]

            identity = await provider.exchange_callback("code-123", nonce, "verifier")
            assert identity.subject == "sig-user-123"
            assert identity.verified_email == "expert@example.test"
            assert identity.display_name == "Example Expert"

    asyncio.run(verify_flow())
