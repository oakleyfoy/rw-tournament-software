from datetime import date


def test_tournament_can_move_to_past_and_restore(client):
    create_resp = client.post(
        "/api/tournaments",
        json={
            "name": "Archive Flow Open",
            "location": "Austin",
            "timezone": "America/Chicago",
            "start_date": "2026-06-10",
            "end_date": "2026-06-12",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    tid = created["id"]
    assert created["is_archived"] is False

    archive_resp = client.put(
        f"/api/tournaments/{tid}",
        json={"is_archived": True},
    )
    assert archive_resp.status_code == 200, archive_resp.text
    archived = archive_resp.json()
    assert archived["is_archived"] is True
    assert archived["start_date"] == str(date(2026, 6, 10))
    assert archived["end_date"] == str(date(2026, 6, 12))

    list_resp = client.get("/api/tournaments")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    row = next(r for r in rows if r["id"] == tid)
    assert row["is_archived"] is True

    restore_resp = client.put(
        f"/api/tournaments/{tid}",
        json={"is_archived": False},
    )
    assert restore_resp.status_code == 200, restore_resp.text
    restored = restore_resp.json()
    assert restored["is_archived"] is False
