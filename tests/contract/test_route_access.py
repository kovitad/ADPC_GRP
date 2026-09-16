import pytest

from api.main import app


@pytest.mark.contract
def test_every_documented_operation_declares_access_class() -> None:
    schema = app.openapi()
    missing: list[str] = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if operation.get("x-grp-access") not in {"public", "protected", "internal"}:
                missing.append(f"{method.upper()} {path}")

    assert missing == []
