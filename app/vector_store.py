import json
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
from app.config import Config

class SimpleVectorStore:
    def __init__(self):
        self.store_path = Config.get_vector_store_path()
        self.chunks: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        """Loads vectors and metadata from the JSON persistence file."""
        if not self.store_path.exists():
            self.chunks = []
            return
        
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.chunks = data.get("chunks", [])
        except Exception as e:
            print(f"Error loading vector store: {e}")
            self.chunks = []

    def save(self):
        """Saves current chunks (with vectors) to the JSON persistence file."""
        try:
            # Create parent dirs if they don't exist
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump({"chunks": self.chunks}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving vector store: {e}")

    def add_chunks(self, new_chunks: List[Dict[str, Any]]):
        """Adds a list of chunks and saves the store.
        Each chunk should be:
        {
            "id": str,
            "text": str,
            "doc_name": str,
            "chunk_index": int,
            "embedding": List[float],
            "metadata": dict
        }
        """
        self.chunks.extend(new_chunks)
        self.save()

    def delete_document(self, doc_name: str) -> int:
        """Deletes all chunks associated with a document name. Returns count of deleted chunks."""
        initial_count = len(self.chunks)
        self.chunks = [chunk for chunk in self.chunks if chunk["doc_name"] != doc_name]
        deleted_count = initial_count - len(self.chunks)
        if deleted_count > 0:
            self.save()
        return deleted_count

    def get_active_documents(self) -> List[Dict[str, Any]]:
        """Returns metadata about loaded documents."""
        docs = {}
        for chunk in self.chunks:
            doc_name = chunk["doc_name"]
            if doc_name not in docs:
                docs[doc_name] = {
                    "doc_name": doc_name,
                    "chunk_count": 0,
                    "file_size": chunk.get("metadata", {}).get("file_size", "Unknown"),
                    "added_at": chunk.get("metadata", {}).get("added_at", "")
                }
            docs[doc_name]["chunk_count"] += 1
        return list(docs.values())

    def similarity_search(self, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Calculates cosine similarity and returns top_k matching chunks."""
        if not self.chunks:
            return []

        # Extract embeddings
        embeddings = [chunk["embedding"] for chunk in self.chunks]
        
        # Convert to numpy arrays for fast calculation
        emb_matrix = np.array(embeddings, dtype=np.float32)
        q_vec = np.array(query_embedding, dtype=np.float32)

        # Compute cosine similarity
        # cosine_sim = dot(A, B) / (||A|| * ||B||)
        dot_products = np.dot(emb_matrix, q_vec)
        matrix_norms = np.linalg.norm(emb_matrix, axis=1)
        query_norm = np.linalg.norm(q_vec)

        # Avoid division by zero
        norms = matrix_norms * query_norm
        norms[norms == 0] = 1e-10

        similarities = dot_products / norms

        # Get top_k indices sorted descending
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            chunk_copy = self.chunks[idx].copy()
            # Remove embedding from returned results to save network bandwidth
            if "embedding" in chunk_copy:
                del chunk_copy["embedding"]
            chunk_copy["similarity"] = score
            results.append(chunk_copy)

        return results
