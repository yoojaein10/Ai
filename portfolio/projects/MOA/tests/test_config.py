from pydantic import SecretStr

from app.config import Settings
from app.database import build_database_url


def test_database_url_escapes_credentials() -> None:
    settings = Settings(
        mssql_server="db.example.local",
        mssql_db="A10Bridge",
        mssql_user="bridge_user",
        mssql_password=SecretStr("p@ss word"),
    )

    url = build_database_url(settings)

    assert url.drivername == "mssql+pyodbc"
    assert url.database == "A10Bridge"
    assert url.render_as_string(hide_password=True).find("p@ss word") == -1

