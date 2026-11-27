"""First-run setup. Safe to run on every start (idempotent):
wait for the databases, seed demo data if the database is empty, load the knowledge base if it is empty."""
import sys
import time
from pathlib import Path

from pymongo import MongoClient
from qdrant_client import QdrantClient

from app.core.config import settings


def wait_for(name: str, check, timeout: int = 120) -> None:
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        try:
            check()
            print(f"[bootstrap] {name} is ready", flush=True)
            return
        except Exception as e:                     
            last = e
            time.sleep(2)
    sys.exit(f"[bootstrap] {name} not reachable after {timeout}s: {last}")


def main() -> None:
    mongo = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
    qdrant = QdrantClient(url=settings.qdrant_url, check_compatibility=False)
    wait_for("MongoDB", lambda: mongo.admin.command("ping"))
    wait_for("Qdrant", lambda: qdrant.get_collections())

    if mongo[settings.mongo_db].customers.count_documents({}) == 0:
        from scripts.seed_mongo import seed
        seed()
    else:
        print("[bootstrap] demo data already present: skipping seed", flush=True)

    docs = settings.qdrant_docs_collection
    empty = (not qdrant.collection_exists(docs)) or qdrant.count(docs, exact=True).count == 0
    if empty:
        from app.rag.ingest import ingest_folder
        ingest_folder(Path("data/docs"))
    else:
        print("[bootstrap] knowledge base already loaded: skipping ingest", flush=True)

    from app.memory.qdrant_memory import ensure_collection
    ensure_collection()                            
    print("[bootstrap] done", flush=True)


if __name__ == "__main__":
    main()