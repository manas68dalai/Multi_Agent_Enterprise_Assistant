from functools import lru_cache
from pymongo import MongoClient
from qdrant_client import QdrantClient
from app.core.config import settings

@lru_cache
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, check_compatibility=False)

@lru_cache
def get_mongo_db():
    return MongoClient(settings.mongo_uri, tz_aware=True)[settings.mongo_db]