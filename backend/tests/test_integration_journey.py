"""Phase 11: one full end-to-end user journey through the real HTTP API,
exercising the endpoints from several phases together rather than each in
isolation — register, log in, create a field, run a prediction (weather is
the autouse FakeWeatherService, never a real HTTP call), see it in history,
record a real outcome against it, confirm performance tracking reflects the
new count, and confirm the drift endpoint responds.

Note: the brief for this phase asked for a "report endpoint returns bytes"
step too, but no report-generation endpoint exists in this codebase yet —
PROGRESS.md's Phase 12 ("Reports + Docs") is the phase that adds one. That
step is intentionally omitted here rather than invented; add it once
Phase 12 lands."""


def test_full_user_journey_register_through_drift(client):
    # 1. Register
    register_response = client.post(
        "/api/v1/auth/register",
        json={"username": "journeyuser", "password": "password123"},
    )
    assert register_response.status_code == 201, register_response.text
    refresh_token = register_response.json()["refresh_token"]

    # 2. Login (a second, independent session for the same user)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "journeyuser", "password": "password123"},
    )
    assert login_response.status_code == 200, login_response.text
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    # 2b. The refresh token from registration still works independently of login
    refresh_response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 200, refresh_response.text

    # 3. Create a field
    field_response = client.post(
        "/api/v1/fields",
        json={"name": "Journey Field", "district": "Lahore", "crop_type": "wheat"},
        headers=headers,
    )
    assert field_response.status_code == 201, field_response.text
    field_id = field_response.json()["id"]

    # 4. Predict (mocked weather via the autouse FakeWeatherService)
    predict_response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 28.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
            "field_id": field_id,
        },
        headers=headers,
    )
    assert predict_response.status_code == 200, predict_response.text
    recommendation_mm = predict_response.json()["irrigation_recommendation_mm"]

    # 5. History shows it
    history_response = client.get("/api/v1/history", headers=headers)
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["field_id"] == field_id
    prediction_id = history[0]["id"]

    # 6. Record the actual outcome
    actual_response = client.post(
        f"/api/v1/history/{prediction_id}/actual",
        json={"actual_irrigation_mm": recommendation_mm + 1.5, "note": "journey test"},
        headers=headers,
    )
    assert actual_response.status_code == 201, actual_response.text

    # 7. Performance reflects the new count
    performance_response = client.get("/api/v1/monitoring/performance")
    assert performance_response.status_code == 200
    performance = performance_response.json()
    assert performance["status"] == "ok"
    assert performance["count"] >= 1
    assert performance["rolling_mae"] is not None

    # 8. Drift endpoint responds (public, read-only — status may honestly be
    # "insufficient_data" with only one prediction logged; this journey only
    # asserts the endpoint itself works end-to-end, not a particular verdict)
    drift_response = client.get("/api/v1/monitoring/drift")
    assert drift_response.status_code == 200
    drift = drift_response.json()
    assert drift["status"] in ("insufficient_data", "stable", "warning", "significant_drift")
