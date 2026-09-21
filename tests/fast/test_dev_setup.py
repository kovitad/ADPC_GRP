from sqlalchemy import create_engine, inspect

from grpcli.dev import initialize_local_environment


def test_local_environment_setup_is_idempotent(tmp_path) -> None:
    first = initialize_local_environment(tmp_path)
    session_secret = first.session_secret_file.read_text(encoding="utf-8")
    second = initialize_local_environment(tmp_path)

    assert first == second
    assert second.session_secret_file.read_text(encoding="utf-8") == session_secret
    database_url = second.database_url_file.read_text(encoding="utf-8").strip()
    engine = create_engine(database_url)
    try:
        assert {
            "hub",
            "app_user",
            "external_identity",
            "hub_membership",
            "audit_event",
        }.issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()
