import hashlib
import math
import re
from pathlib import Path

from app.agents.training.schemas import KnowledgeReference
from app.agents.training.settings import TrainingSettings

PROFILE = "local-test-hash-v1"
MATERIALS = Path(__file__).parent / "fixtures" / "python_backend_test_materials.md"


def embed(text: str) -> list[float]:
    """Deterministic test vectors, explicitly NOT a semantic embedding model."""
    normalized = text.lower()
    tokens = re.findall(r"[a-z_][a-z_0-9]*|[\u4e00-\u9fff]", normalized)
    features = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    vector = [0.0] * 256
    for token in features:
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:2], "big") % len(vector)
        vector[index] += 1 if digest[2] & 1 else -1
    norm = math.sqrt(sum(value * value for value in vector)) or 1
    return [value / norm for value in vector]


class TrainingKnowledge:
    def __init__(self, settings: TrainingSettings):
        import chromadb
        from chromadb.config import Settings

        self.settings = settings
        self.client = chromadb.PersistentClient(
            path=str(settings.chroma_path), settings=Settings(anonymized_telemetry=False)
        )

    def seed(self) -> int:
        collection = self.client.get_or_create_collection(
            self.settings.chroma_collection,
            metadata={"embedding_profile": PROFILE, "synthetic": True, "schema_version": 1},
            embedding_function=None,
        )
        self._validate(collection)
        source = MATERIALS.read_text(encoding="utf-8")
        for section in source.split("\n## ")[1:]:
            title, body = section.split("\n", 1)
            document = title + "\n" + body.strip()
            digest = hashlib.sha256(document.encode()).hexdigest()
            collection.upsert(
                ids=[digest],
                embeddings=[embed(document)],
                documents=[document],
                metadatas=[
                    {
                        "source": "synthetic:python_backend_test_materials.md#" + title,
                        "content_sha256": digest,
                        "embedding_profile": PROFILE,
                        "schema_version": 1,
                        "synthetic": True,
                    }
                ],
            )
        return collection.count()

    @staticmethod
    def _validate(collection) -> None:
        if (collection.metadata or {}).get("embedding_profile") != PROFILE:
            raise RuntimeError("Refusing to use a collection with a different embedding profile")

    def search(self, query: str, limit: int = 3) -> list[KnowledgeReference]:
        collection = self.client.get_collection(
            self.settings.chroma_collection, embedding_function=None
        )
        self._validate(collection)
        count = collection.count()
        if not count:
            raise RuntimeError("Seed the local test materials first")
        result = collection.query(
            query_embeddings=[embed(query)],
            n_results=min(limit, count),
            include=["documents", "metadatas"],
        )
        references = []
        for document, metadata in zip(result["documents"][0], result["metadatas"][0]):
            if hashlib.sha256(document.encode()).hexdigest() != metadata["content_sha256"]:
                raise RuntimeError("Knowledge content hash mismatch")
            references.append(
                KnowledgeReference(
                    source=metadata["source"],
                    excerpt=document,
                    content_sha256=metadata["content_sha256"],
                )
            )
        return references

    def status(self) -> dict:
        collection = self.client.get_collection(
            self.settings.chroma_collection, embedding_function=None
        )
        self._validate(collection)
        return {"documents": collection.count(), "embedding_profile": PROFILE, "synthetic": True}

print(12)
