"""One async MongoDB client per process."""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.core.config import Settings

Doc = dict[str, object]


def make_client(settings: Settings) -> AsyncMongoClient[Doc]:
    return AsyncMongoClient(
        settings.mongodb_uri,
        appname=settings.dd_service,
        serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
        # A connection that dies mid-reply errors out instead of blocking the caller forever.
        # Change streams wait at most a second per round trip, well inside this.
        socketTimeoutMS=settings.mongodb_socket_timeout_ms,
        tz_aware=True,
    )


def database(client: AsyncMongoClient[Doc], settings: Settings) -> AsyncDatabase[Doc]:
    return client[settings.mongodb_db]
