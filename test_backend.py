import sys
from pathlib import Path
import numpy as np

# Add parent directory to path so we can import app
sys.path.append(str(Path(__file__).resolve().parent))

from app.vector_store import SimpleVectorStore
from app.rag import RAGEngine

def test_text_splitting():
    print("Testing Text Splitter...")
    # Initialize engine
    vs = SimpleVectorStore()
    rag = RAGEngine(vs)
    
    # Simple document pages
    pages = [
        {
            "page": 1, 
            "text": "This is a document about NexusDoc AI. It is a premium RAG application.\n\n"
                    "Section 1: Setup.\n"
                    "To set it up, you need a Gemini API Key. You can get one from Google AI Studio.\n"
                    "Once you have the key, configure it in the web interface settings page."
        },
        {
            "page": 2,
            "text": "Section 2: Usage.\n"
            "Drag and drop documents to the upload area. The system will extract the text, "
            "chunk it, generate vector embeddings, and save them. You can then ask questions "
            "in the chat box and retrieve highly relevant citations from your files."
        }
    ]
    
    # Split with size 150 and overlap 20
    chunks = rag.split_text_to_chunks(pages, chunk_size=150, chunk_overlap=20)
    
    print(f" -> Generated {len(chunks)} chunks from 2 pages.")
    assert len(chunks) > 0, "Should generate chunks!"
    
    for i, c in enumerate(chunks):
        print(f"   Chunk {i+1} (Page {c['page']}): {repr(c['text'])}")
        assert len(c['text']) <= 160, "Chunk size exceeds maximum constraint!"
        assert "text" in c
        assert "page" in c
        assert "chunk_index" in c
    print("Text Splitter Test PASSED!\n")

def test_vector_store():
    print("Testing Vector Store & Cosine Similarity...")
    vs = SimpleVectorStore()
    # Clear existing chunks for testing
    vs.chunks = []
    
    # Add dummy chunks with 3-dimensional embeddings
    # query will be [1.0, 0.0, 0.0]
    # chunk 1: [0.9, 0.1, 0.0] (Very close)
    # chunk 2: [0.0, 1.0, 0.0] (Orthogonal - zero similarity)
    # chunk 3: [-0.9, 0.0, 0.0] (Opposite)
    
    dummy_chunks = [
        {
            "id": "1",
            "text": "NexusDoc AI is a RAG chatbot.",
            "doc_name": "nexus_doc.txt",
            "chunk_index": 0,
            "embedding": [0.9, 0.1, 0.0],
            "metadata": {"page": 1}
        },
        {
            "id": "2",
            "text": "Apples are delicious fruits.",
            "doc_name": "apples.txt",
            "chunk_index": 0,
            "embedding": [0.0, 1.0, 0.0],
            "metadata": {"page": 1}
        },
        {
            "id": "3",
            "text": "Deep cold space is empty.",
            "doc_name": "space.txt",
            "chunk_index": 0,
            "embedding": [-0.9, 0.0, 0.0],
            "metadata": {"page": 1}
        }
    ]
    
    vs.add_chunks(dummy_chunks)
    
    # Verify save & load
    vs.save()
    
    # Reload store
    vs2 = SimpleVectorStore()
    assert len(vs2.chunks) == 3, "Failed to persist chunks!"
    
    # Similarity Search
    query_emb = [1.0, 0.0, 0.0]
    results = vs2.similarity_search(query_emb, top_k=3)
    
    assert len(results) == 3
    
    # Verify order of similarity (chunk 1 > chunk 2 > chunk 3)
    print(" -> Search results (sorted by cosine similarity):")
    for r in results:
        print(f"   Doc: {r['doc_name']} | Text: {repr(r['text'])} | Similarity Score: {r['similarity']:.4f}")
        
    assert results[0]["doc_name"] == "nexus_doc.txt", "Best match should be nexus_doc.txt"
    assert results[1]["doc_name"] == "apples.txt", "Second match should be apples.txt"
    assert results[2]["doc_name"] == "space.txt", "Third match should be space.txt"
    
    # Cleanup dummy documents
    vs2.delete_document("nexus_doc.txt")
    vs2.delete_document("apples.txt")
    vs2.delete_document("space.txt")
    assert len(vs2.chunks) == 0, "Document deletion failed!"
    vs2.save()
    
    print("Vector Store Cosine Similarity Test PASSED!\n")

if __name__ == "__main__":
    print("=========================================")
    print("RUNNING BACKEND UNIT TESTS")
    print("=========================================\n")
    test_text_splitting()
    test_vector_store()
    print("All verification tests passed successfully!")
