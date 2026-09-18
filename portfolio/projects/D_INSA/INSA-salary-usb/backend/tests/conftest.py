import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.models import Role, User, UserRole
from app.db.session import get_apw_db, get_db
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

    def override_get_apw_db():
        # 테스트는 외부 APW DB에 붙지 않는다. 좌석 매핑은 monkeypatch로 흉내낸다.
        yield None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_apw_db] = override_get_apw_db
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


@pytest.fixture
def system_admin_user(db_session):
    role = Role(code="SYSTEM_ADMIN", name="시스템 관리자")
    db_session.add(role)
    db_session.flush()

    user = User(
        login_id="sysadmin",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def system_admin_headers(system_admin_user):
    token = create_access_token(
        str(system_admin_user.id), extra={"roles": ["SYSTEM_ADMIN"]}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def plain_user(db_session):
    role = Role(code="EMPLOYEE", name="일반 직원")
    db_session.add(role)
    db_session.flush()

    user = User(
        login_id="employee",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def plain_headers(plain_user):
    token = create_access_token(str(plain_user.id), extra={"roles": ["EMPLOYEE"]})
    return {"Authorization": f"Bearer {token}"}
