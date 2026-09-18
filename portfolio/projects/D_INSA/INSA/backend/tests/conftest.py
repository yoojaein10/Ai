import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.models import Role, User, UserRole
from app.db.session import get_db
from app.main import app


@pytest.fixture(scope="session")
def engine():
    """Use in-memory SQLite for tests."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine


@pytest.fixture
def db_session(engine):
    """Each test runs in a transaction that gets rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    # Begin a nested transaction (savepoint)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        nonlocal nested
        if transaction.nested and not transaction._parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db_session):
    role = Role(code="HR_ADMIN", name="인사 담당자")
    db_session.add(role)
    db_session.flush()

    user = User(
        login_id="admin",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    user_role = UserRole(user_id=user.id, role_id=role.id)
    db_session.add(user_role)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_token(admin_user):
    return create_access_token(str(admin_user.id), extra={"roles": ["HR_ADMIN"]})


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
