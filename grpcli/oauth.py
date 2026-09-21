from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Never

from api.oidc import IdentityProviderError, register_public_client, write_client_id


def fail(message: str) -> Never:
    raise SystemExit(f"ERROR: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GRP OAuth client setup")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register-client")
    register.add_argument(
        "--resource", default="https://servirplatform.sig-gis.com/mcp"
    )
    register.add_argument("--redirect-uri", required=True)
    register.add_argument("--client-name", default="ADPC GRP")
    register.add_argument("--issuer")
    register.add_argument(
        "--output-file", type=Path, default=Path(".local/servir_auth_client_id")
    )
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    output_file: Path = arguments.output_file
    if output_file.is_file() and output_file.read_text(encoding="utf-8").strip():
        print(f"OAuth client already configured in {output_file}; no change")
        return
    try:
        registration = asyncio.run(
            register_public_client(
                resource=arguments.resource,
                redirect_uri=arguments.redirect_uri,
                client_name=arguments.client_name,
                issuer=arguments.issuer,
            )
        )
        write_client_id(output_file, registration.client_id)
    except (IdentityProviderError, OSError) as error:
        fail(str(error))
    print(f"Registered public PKCE client for {registration.issuer} in {output_file}")


if __name__ == "__main__":
    main()
