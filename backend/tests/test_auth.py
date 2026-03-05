from sqlmodel import Session, delete

from app.models.auth_session import AuthSession
from app.models.user_account import UserAccount


def _reset_auth_tables(session: Session) -> None:
    session.exec(delete(AuthSession))
    session.exec(delete(UserAccount))
    session.commit()


def test_bootstrap_admin_and_protect_private_routes(client, session: Session):
    _reset_auth_tables(session)
    # Before bootstrap, auth is not enforced yet.
    open_resp = client.get("/api/tournaments")
    assert open_resp.status_code == 200

    needed = client.get("/api/auth/bootstrap-needed")
    assert needed.status_code == 200
    assert needed.json()["bootstrap_needed"] is True

    created = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "admin", "password": "password123", "display_name": "Admin"},
    )
    assert created.status_code == 201
    assert created.json()["role"] == "admin"

    needed_after = client.get("/api/auth/bootstrap-needed")
    assert needed_after.status_code == 200
    assert needed_after.json()["bootstrap_needed"] is False

    # After bootstrap, private endpoints require auth.
    denied = client.get("/api/tournaments")
    assert denied.status_code == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    authed = client.get("/api/tournaments", headers=headers)
    assert authed.status_code == 200

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_admin_can_create_director_but_director_cannot_manage_users(client, session: Session):
    _reset_auth_tables(session)
    client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "admin", "password": "password123"},
    )
    admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create_director = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "director1",
            "password": "password123",
            "display_name": "Director One",
            "role": "director",
        },
    )
    assert create_director.status_code == 201
    assert create_director.json()["role"] == "director"

    director_login = client.post("/api/auth/login", json={"username": "director1", "password": "password123"})
    director_token = director_login.json()["access_token"]
    director_headers = {"Authorization": f"Bearer {director_token}"}

    denied = client.get("/api/auth/users", headers=director_headers)
    assert denied.status_code == 403


def test_admin_can_disable_user_and_cannot_disable_self(client, session: Session):
    _reset_auth_tables(session)
    client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "admin", "password": "password123"},
    )
    admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create_director = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"username": "director2", "password": "password123", "role": "director"},
    )
    assert create_director.status_code == 201
    director_id = create_director.json()["id"]

    disable = client.patch(
        f"/api/auth/users/{director_id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert disable.status_code == 200
    assert disable.json()["is_active"] is False

    denied_login = client.post("/api/auth/login", json={"username": "director2", "password": "password123"})
    assert denied_login.status_code == 401

    self_disable = client.patch(
        f"/api/auth/users/{admin_login.json()['user']['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert self_disable.status_code == 400

