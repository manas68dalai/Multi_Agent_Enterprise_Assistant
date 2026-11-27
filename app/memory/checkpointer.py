from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver
from pymongo import MongoClient

from app.core.config import settings


@lru_cache
def get_checkpointer():
    """Short-term memory: conversation state per thread_id (durable in MongoDB)."""
    if settings.checkpointer.lower() == "mongo":
        from langgraph.checkpoint.mongodb import MongoDBSaver
        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
        saver = MongoDBSaver(client, settings.checkpoint_db)  
        if hasattr(saver, "setup"):                
            saver.setup()
        return saver
    return InMemorySaver()