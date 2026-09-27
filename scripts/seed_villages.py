import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db.engine import get_async_session
from src.db.models import Village


async def seed_villages():
    """Populate the database with a few test villages."""

    mock_villages = [
        {
            "name": "Test Village (1m Contours)",
            "state": "Chhattisgarh",
            "district": "Bastar",
            "latitude": 19.1,
            "longitude": 82.0,
            "kml_path": "tests/fixtures/contours_1m.kml",
        },
        {
            "name": "Test Village (2m Contours)",
            "state": "Chhattisgarh",
            "district": "Bastar",
            "latitude": 19.2,
            "longitude": 82.1,
            "kml_path": "tests/fixtures/contours_2m.kml",
        },
        {
            "name": "Test Village (Broken XML)",
            "state": "Chhattisgarh",
            "district": "Bastar",
            "latitude": 19.3,
            "longitude": 82.2,
            "kml_path": "tests/fixtures/broken.xml",
        },
    ]

    async with get_async_session() as session:
        # Check if they exist first
        from sqlmodel import select

        existing = await session.execute(select(Village))
        if existing.scalars().first():
            print("Villages already seeded.")
            return

        for v_data in mock_villages:
            village = Village(**v_data)
            session.add(village)

        await session.commit()
        print(f"Successfully seeded {len(mock_villages)} villages.")


if __name__ == "__main__":
    from src.config import settings

    if not settings.database_url:
        print("DATABASE_URL not set. Skipping seeding.")
        sys.exit(0)

    asyncio.run(seed_villages())
