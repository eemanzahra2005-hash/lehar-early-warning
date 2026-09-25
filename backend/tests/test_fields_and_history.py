"""Tests for /api/v1/fields (auth required) and /api/v1/history."""

from datetime import date


def test_fields_require_auth(client):
    response = client.get("/api/v1/fields")

    assert response.status_code == 401


def test_create_field_predict_and_history_roundtrip(client, register_user):
    token = register_user(username="farmer1")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/v1/fields",
        json={"name": "North Plot", "district": "Multan", "crop_type": "cotton"},
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    field_id = create_response.json()["id"]

    predict_response = client.post(
        "/api/v1/predict",
        json={
            "district": "Multan",
            "crop_type": "cotton",
            "soil_moisture_pct": 22.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
            "field_id": field_id,
        },
        headers=headers,
    )
    assert predict_response.status_code == 200, predict_response.text

    history_response = client.get("/api/v1/history", headers=headers)
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["field_id"] == field_id
    assert history[0]["district"] == "Multan"
    assert history[0]["risk_score"] is not None
    assert history[0]["risk_band"] in ("LOW", "MODERATE", "HIGH")
    assert history[0]["risk_score"] == predict_response.json()["risk"]["score"]


def test_field_create_rejects_unknown_district(client, register_user):
    token = register_user(username="farmer2")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/fields",
        json={"name": "Bad Plot", "district": "Atlantis", "crop_type": "wheat"},
        headers=headers,
    )

    assert response.status_code == 400


def test_user_cannot_delete_another_users_field(client, register_user):
    token_a = register_user(username="userA")
    token_b = register_user(username="userB")

    create_response = client.post(
        "/api/v1/fields",
        json={"name": "A's Field", "district": "Lahore", "crop_type": "wheat"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    field_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/fields/{field_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert delete_response.status_code == 404


def test_list_fields_never_includes_another_users_fields(client, register_user):
    """Ownership boundary (Phase 11): user A's field list must contain only
    their own fields, never a field belonging to user B — even when B has
    fields and A doesn't yet."""
    token_a = register_user(username="listFieldsA")
    token_b = register_user(username="listFieldsB")

    client.post(
        "/api/v1/fields",
        json={"name": "B's Field 1", "district": "Lahore", "crop_type": "wheat"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    client.post(
        "/api/v1/fields",
        json={"name": "B's Field 2", "district": "Multan", "crop_type": "cotton"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    a_field = client.post(
        "/api/v1/fields",
        json={"name": "A's Field", "district": "Lahore", "crop_type": "wheat"},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()

    a_list = client.get("/api/v1/fields", headers={"Authorization": f"Bearer {token_a}"}).json()

    assert len(a_list) == 1
    assert a_list[0]["id"] == a_field["id"]
    assert a_list[0]["name"] == "A's Field"


def test_owner_can_delete_their_own_field(client, register_user):
    token = register_user(username="userC")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/v1/fields",
        json={"name": "C's Field", "district": "Lahore", "crop_type": "wheat"},
        headers=headers,
    )
    field_id = create_response.json()["id"]

    delete_response = client.delete(f"/api/v1/fields/{field_id}", headers=headers)

    assert delete_response.status_code == 204


def test_history_requires_auth(client):
    response = client.get("/api/v1/history")

    assert response.status_code == 401


def test_history_never_includes_another_users_predictions(client, register_user):
    """Ownership boundary (Phase 11): GET /history is scoped to the caller's
    own predictions only, even when another user has predictions logged."""
    token_a = register_user(username="historyA")
    token_b = register_user(username="historyB")

    client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
        },
        headers={"Authorization": f"Bearer {token_b}"},
    )

    a_history = client.get("/api/v1/history", headers={"Authorization": f"Bearer {token_a}"}).json()

    assert a_history == []


def test_history_field_id_filter_cannot_leak_another_users_field(client, register_user):
    """Passing another user's real field_id as a filter must never return
    that user's predictions — the query already ANDs field_id with the
    caller's own user_id (see routers/history.py), so this should come back
    empty rather than erroring or leaking."""
    token_a = register_user(username="historyFieldA")
    token_b = register_user(username="historyFieldB")

    b_field = client.post(
        "/api/v1/fields",
        json={"name": "B's Field", "district": "Lahore", "crop_type": "wheat"},
        headers={"Authorization": f"Bearer {token_b}"},
    ).json()
    client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
            "field_id": b_field["id"],
        },
        headers={"Authorization": f"Bearer {token_b}"},
    )

    leaked = client.get(
        "/api/v1/history",
        params={"field_id": b_field["id"]},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert leaked.status_code == 200
    assert leaked.json() == []


def test_history_filters_by_from_and_to_date(client, register_user):
    token = register_user(username="farmer3")
    headers = {"Authorization": f"Bearer {token}"}

    predict_response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
        },
        headers=headers,
    )
    assert predict_response.status_code == 200, predict_response.text
    created_date = date.today()

    # The prediction just made falls inside [today, today] and outside a
    # window entirely in the past.
    in_range = client.get(
        "/api/v1/history",
        params={"from": str(created_date), "to": str(created_date)},
        headers=headers,
    )
    assert in_range.status_code == 200
    assert len(in_range.json()) == 1

    out_of_range = client.get(
        "/api/v1/history",
        params={"from": "2000-01-01", "to": "2000-01-02"},
        headers=headers,
    )
    assert out_of_range.status_code == 200
    assert out_of_range.json() == []


# --- POST /api/v1/history/{id}/actual (Phase 10) --------------------------


def _make_prediction(client, headers) -> int:
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    history = client.get("/api/v1/history", headers=headers).json()
    return history[0]["id"]


def test_record_actual_requires_auth(client, register_user):
    token = register_user(username="actualuser1")
    prediction_id = _make_prediction(client, {"Authorization": f"Bearer {token}"})

    response = client.post(
        f"/api/v1/history/{prediction_id}/actual", json={"actual_irrigation_mm": 12.0}
    )

    assert response.status_code == 401


def test_record_actual_404_for_someone_elses_prediction(client, register_user):
    token_a = register_user(username="actualowner")
    token_b = register_user(username="actualintruder")
    prediction_id = _make_prediction(client, {"Authorization": f"Bearer {token_a}"})

    response = client.post(
        f"/api/v1/history/{prediction_id}/actual",
        json={"actual_irrigation_mm": 12.0},
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert response.status_code == 404


def test_record_actual_rejects_out_of_bounds_value(client, register_user):
    token = register_user(username="actualuser2")
    headers = {"Authorization": f"Bearer {token}"}
    prediction_id = _make_prediction(client, headers)

    response = client.post(
        f"/api/v1/history/{prediction_id}/actual",
        json={"actual_irrigation_mm": 250.0},
        headers=headers,
    )

    assert response.status_code == 422


def test_record_actual_success_then_duplicate_is_409(client, register_user):
    token = register_user(username="actualuser3")
    headers = {"Authorization": f"Bearer {token}"}
    prediction_id = _make_prediction(client, headers)

    first = client.post(
        f"/api/v1/history/{prediction_id}/actual",
        json={"actual_irrigation_mm": 12.5, "note": "measured with a flow meter"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["actual"]["actual_irrigation_mm"] == 12.5
    assert first.json()["actual"]["note"] == "measured with a flow meter"

    # The recorded value shows up on subsequent history reads too.
    history = client.get("/api/v1/history", headers=headers).json()
    assert history[0]["actual"]["actual_irrigation_mm"] == 12.5

    second = client.post(
        f"/api/v1/history/{prediction_id}/actual",
        json={"actual_irrigation_mm": 9.0},
        headers=headers,
    )
    assert second.status_code == 409
