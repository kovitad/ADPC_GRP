from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from api.settings import Settings
from core.db import read_secret
from core.identity import VerifiedIdentity

ALLOWED_SIGNING_ALGORITHMS = {"RS256", "ES256"}


class IdentityProviderError(RuntimeError):
    """A safe, detail-free identity-provider failure."""


@dataclass(frozen=True)
class OidcMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    signing_algorithms: tuple[str, ...]
    token_auth_method: str


class HumanIdentityProvider(Protocol):
    async def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str: ...

    async def exchange_callback(
        self, code: str, nonce: str, code_verifier: str
    ) -> VerifiedIdentity: ...


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class ServirSigIdentityProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.servir_auth_issuer:
            raise IdentityProviderError("SERVIR issuer is not configured")
        if not settings.servir_auth_client_id:
            raise IdentityProviderError("SERVIR client ID is not configured")
        if not settings.servir_auth_redirect_uri:
            raise IdentityProviderError("SERVIR redirect URI is not configured")
        self.allow_insecure_localhost = settings.grp_env == "dev"
        self.issuer = self._validate_endpoint(settings.servir_auth_issuer).rstrip("/")
        self.client_id = settings.servir_auth_client_id
        self.client_secret = read_secret(settings.servir_auth_client_secret_file)
        self.redirect_uri = self._validate_endpoint(settings.servir_auth_redirect_uri)
        self.client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)
        self._owns_client = client is None

    def _validate_endpoint(self, value: str) -> str:
        parsed = urlparse(value)
        if not parsed.hostname or parsed.username or parsed.password:
            raise IdentityProviderError("Identity endpoint URL is invalid")
        local_http = (
            self.allow_insecure_localhost
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
        )
        if parsed.scheme != "https" and not local_http:
            raise IdentityProviderError("Identity endpoint must use HTTPS")
        return value

    async def _metadata(self) -> OidcMetadata:
        try:
            response = await self.client.get(
                f"{self.issuer}/.well-known/openid-configuration",
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            document = response.json()
            issuer = str(document["issuer"]).rstrip("/")
            if not hmac.compare_digest(issuer, self.issuer):
                raise IdentityProviderError("Identity issuer mismatch")
            algorithms = tuple(
                algorithm
                for algorithm in document.get("id_token_signing_alg_values_supported", [])
                if algorithm in ALLOWED_SIGNING_ALGORITHMS
            )
            if not algorithms:
                raise IdentityProviderError("No approved ID-token signing algorithm")
            auth_methods = document.get(
                "token_endpoint_auth_methods_supported", ["client_secret_basic"]
            )
            token_auth_method = next(
                (
                    method
                    for method in ("client_secret_basic", "client_secret_post")
                    if method in auth_methods
                ),
                None,
            )
            if token_auth_method is None:
                raise IdentityProviderError("No approved token endpoint authentication method")
            return OidcMetadata(
                issuer=issuer,
                authorization_endpoint=self._validate_endpoint(
                    str(document["authorization_endpoint"])
                ),
                token_endpoint=self._validate_endpoint(str(document["token_endpoint"])),
                jwks_uri=self._validate_endpoint(str(document["jwks_uri"])),
                signing_algorithms=algorithms,
                token_auth_method=token_auth_method,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise IdentityProviderError("SERVIR sign-in metadata is unavailable") from error

    async def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        metadata = await self._metadata()
        parameters = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata.authorization_endpoint}?{parameters}"

    async def exchange_callback(
        self, code: str, nonce: str, code_verifier: str
    ) -> VerifiedIdentity:
        metadata = await self._metadata()
        try:
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
            }
            token_auth: tuple[str, str] | None = (self.client_id, self.client_secret)
            if metadata.token_auth_method == "client_secret_post":
                token_data.update(
                    {"client_id": self.client_id, "client_secret": self.client_secret}
                )
                token_auth = None
            token_response = await self.client.post(
                metadata.token_endpoint,
                data=token_data,
                auth=token_auth,
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            id_token = str(token_response.json()["id_token"])

            jwks_response = await self.client.get(
                metadata.jwks_uri, headers={"Accept": "application/json"}
            )
            jwks_response.raise_for_status()
            key_set = jwt.PyJWKSet.from_dict(jwks_response.json())
            header = jwt.get_unverified_header(id_token)
            algorithm = str(header.get("alg", ""))
            if algorithm not in metadata.signing_algorithms:
                raise IdentityProviderError("ID-token algorithm is not approved")
            key_id = str(header.get("kid", ""))
            signing_key = next((key.key for key in key_set.keys if key.key_id == key_id), None)
            if signing_key is None:
                raise IdentityProviderError("ID-token signing key is unknown")
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=[algorithm],
                audience=self.client_id,
                issuer=metadata.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce", "email"]},
                leeway=30,
            )
            if not hmac.compare_digest(str(claims["nonce"]), nonce):
                raise IdentityProviderError("ID-token nonce mismatch")
            if claims.get("email_verified") is not True:
                raise IdentityProviderError("SERVIR email is not verified")
            email = str(claims["email"]).strip().lower()
            if len(email) > 320 or email.count("@") != 1:
                raise IdentityProviderError("SERVIR email claim is invalid")
            return VerifiedIdentity(
                issuer=str(claims["iss"]),
                subject=str(claims["sub"]),
                verified_email=email,
                display_name=str(claims["name"]) if claims.get("name") else None,
            )
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            raise IdentityProviderError("SERVIR sign-in could not be verified") from error

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
