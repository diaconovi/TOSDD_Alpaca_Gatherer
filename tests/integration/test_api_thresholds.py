"""``GET /api/v1/thresholds`` returns exactly the values of the thresholds file."""

from tests.conftest import TEST_THRESHOLDS, AppFactory


async def test_thresholds_equal_the_file(app_factory: AppFactory) -> None:
    async with app_factory() as (_, client):
        response = await client.get("/api/v1/thresholds")
    assert response.status_code == 200
    assert response.json() == TEST_THRESHOLDS
