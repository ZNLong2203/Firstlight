"""One async MongoDB client per process."""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.core.config import Settings

Doc = dict[str, object]


def make_client(settings: Settings) -> AsyncMongoClient[Doc]:
    return AsyncMongoClient(
        settings.mongodb_uri,
        appname=settings.dd_service,
        serverSelectionTimeoutMS=5000,
        tz_aware=True,
    )


def database(client: AsyncMongoClient[Doc], settings: Settings) -> AsyncDatabase[Doc]:
    return client[settings.mongodb_db]
