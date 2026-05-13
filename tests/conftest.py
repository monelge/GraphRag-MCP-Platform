import asyncio
import os
from collections.abc import Generator

import pytest


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Async testler için event loop üretir."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_db_url() -> str:
    """Test veritabanı bağlantı adresini döndürür."""
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/graphmcp_test")


@pytest.fixture
def test_neo4j_uri() -> str:
    """Test Neo4j bağlantı adresini döndürür."""
    return os.getenv("NEO4J_URI", "bolt://localhost:7687")
