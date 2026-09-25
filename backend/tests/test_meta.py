"""Tests for GET /api/v1/meta."""

from ml.districts import DISTRICTS

EXPECTED_CROPS = {"wheat", "cotton", "rice", "sugarcane", "maize"}


def test_meta_returns_five_crops(client):
    response = client.get("/api/v1/meta")

    assert response.status_code == 200

    body = response.json()
    assert set(body["crops"]) == EXPECTED_CROPS
    assert len(body["crops"]) == 5
    assert "note" in body


def test_meta_district_count_matches_districts_py(client):
    """Doesn't hardcode the district count — asserts against the live
    DISTRICTS dict so this test stays correct as districts.py grows
    (see PROGRESS.md Phase 5.5, which took the count from 45 to 107)."""
    response = client.get("/api/v1/meta")

    assert response.status_code == 200

    body = response.json()
    assert len(body["districts"]) == len(DISTRICTS)
    assert len(set(body["districts"])) == len(DISTRICTS)  # all unique
    assert set(body["districts"]) == set(DISTRICTS.keys())

    # districts_by_province must regroup into the same districts
    by_province = body["districts_by_province"]
    all_grouped = [name for names in by_province.values() for name in names]
    assert sorted(all_grouped) == sorted(body["districts"])
    assert set(by_province.keys()) == {
        "Punjab",
        "Sindh",
        "Khyber Pakhtunkhwa",
        "Balochistan",
        "Capital/AJK/GB",
    }
