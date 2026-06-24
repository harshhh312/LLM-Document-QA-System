import threading
import time
import datetime
import uuid
import pathlib
from typing import Dict, List, Any, Tuple
from pathlib import Path

# Global dictionary to store processing progress for documents
processing_progress: Dict[str, int] = {}


from pypdf import PdfReader
import subprocess

def ensure_ollama_model(model_name: str):
    """Check if an Ollama model is present locally; pull it if missing."""
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, check=True)
        if model_name not in result.stdout:
            print(f"Pulling Ollama model '{model_name}'...")
            subprocess.run(['ollama', 'pull', model_name], check=True)
            print(f"Model '{model_name}' downloaded successfully.")
    except Exception as e:
        raise RuntimeError(f"Failed to ensure Ollama model '{model_name}': {e}")
from app.vector_store import SimpleVectorStore
from app.config import Config

class RAGEngine:
    def __init__(self, vector_store: SimpleVectorStore):
        self.vector_store = vector_store



    def extract_text(self, file_path: Path) -> List[Dict[str, Any]]:
        """Extracts text from files, keeping track of page numbers when possible.
        Returns a list of dicts: [{"page": int, "text": str}]
        """
        suffix = file_path.suffix.lower()
        pages = []
        
        if suffix == ".pdf":
            try:
                reader = PdfReader(str(file_path))
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append({"page": i + 1, "text": text})
            except Exception as e:
                raise ValueError(f"Failed to parse PDF: {str(e)}")
        elif suffix in [".txt", ".md", ".markdown"]:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if text.strip():
                    pages.append({"page": 1, "text": text})
            except Exception as e:
                raise ValueError(f"Failed to parse text file: {str(e)}")
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
            
        return pages

    def split_text_to_chunks(self, pages: List[Dict[str, Any]], chunk_size: int, chunk_overlap: int) -> List[Dict[str, Any]]:
        """Splits page text into small chunks with overlap, maintaining page number metadata."""
        chunks = []
        chunk_idx = 0
        separators = ["\n\n", "\n", " ", ""]

        for page_data in pages:
            page_num = page_data["page"]
            text = page_data["text"]
            text_len = len(text)
            start = 0

            while start < text_len:
                end = start + chunk_size
                if end >= text_len:
                    chunk_text = text[start:]
                    if chunk_text.strip():
                        chunks.append({
                            "text": chunk_text.strip(),
                            "page": page_num,
                            "chunk_index": chunk_idx
                        })
                        chunk_idx += 1
                    break

                # Back off backward from end to find separator for smart splitting
                found_split = False
                for sep in separators[:-1]:
                    # Search for separator in overlap zone
                    pos = text.rfind(sep, start + chunk_overlap, end)
                    if pos != -1:
                        chunk_text = text[start:pos + len(sep)]
                        if chunk_text.strip():
                            chunks.append({
                                "text": chunk_text.strip(),
                                "page": page_num,
                                "chunk_index": chunk_idx
                            })
                            chunk_idx += 1
                        start = pos + len(sep) - chunk_overlap
                        found_split = True
                        break

                if not found_split:
                    chunk_text = text[start:end]
                    if chunk_text.strip():
                        chunks.append({
                            "text": chunk_text.strip(),
                            "page": page_num,
                            "chunk_index": chunk_idx
                        })
                        chunk_idx += 1
                    start = end - chunk_overlap

        return chunks

    def _get_ollama_embeddings(self, base_url: str, model: str, texts: List[str]) -> List[List[float]]:
        import urllib.request
        import json
        
        base_url = base_url.rstrip("/")
        
        # 1. Try batch /api/embed first
        try:
            url = f"{base_url}/api/embed"
            data = json.dumps({"model": model, "input": texts}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if "embeddings" in res_data:
                    return res_data["embeddings"]
        except Exception:
            pass

        # 2. Fallback to /api/embeddings sequentially
        embeddings = []
        url = f"{base_url}/api/embeddings"
        for text in texts:
            try:
                data = json.dumps({"model": model, "prompt": text}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    if "embedding" in res_data:
                        embeddings.append(res_data["embedding"])
                    else:
                        raise ValueError(f"Ollama embedding response missing 'embedding' field: {res_data}")
            except Exception as e:
                raise ValueError(f"Ollama embedding request failed for '{text[:20]}...': {str(e)}")
        
        return embeddings

    def _call_ollama_chat(self, base_url: str, model: str, messages: List[Dict[str, str]], temperature: float) -> str:
        import urllib.request
        import json
        
        url = f"{base_url.rstrip('/')}/api/chat"
        data = json.dumps({
            "model": model,
            "messages": messages,
            "options": {
                "temperature": temperature
            },
            "stream": False
        }).encode("utf-8")
        
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if "message" in res_data and "content" in res_data["message"]:
                    return res_data["message"]["content"]
                else:
                    raise ValueError(f"Ollama chat response missing message content: {res_data}")
        except Exception as e:
            raise ValueError(f"Ollama chat API call failed: {str(e)}")

    def process_and_add_document(self, file_path: Path, doc_name: str, file_size: str) -> Dict[str, Any]:
        """Parses document, splits it, embeds it, and stores chunks in the Vector Store."""
        # 1. Extract Pages
        pages = self.extract_text(file_path)
        if not pages:
            raise ValueError("Document has no text content.")
        processing_progress[doc_name] = 20  # PDF parsing done

        # 2. Split into Chunks
        settings = Config.get_settings()
        # Use Ollama settings directly
        base_url = settings.get("ollama_base_url", "http://localhost:11434")
        emb_model = settings.get("ollama_embedding_model", "nomic-embed-text")        
        chunk_size = settings["chunk_size"]
        chunk_overlap = settings["chunk_overlap"]
        # Generate raw chunks from pages
        raw_chunks = self.split_text_to_chunks(pages, chunk_size, chunk_overlap)
        if not raw_chunks:
            raise ValueError("No text chunks could be created.")
        processing_progress[doc_name] = 40  # Text extraction and chunking done

        # 3. Generate Embeddings
        processed_chunks = []
        added_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        # Ensure embedding model is available
        ensure_ollama_model(emb_model)
        # Ollama embeddings
        batch_size = 50
        total = len(raw_chunks)
        for i in range(0, total, batch_size):
            batch = raw_chunks[i:i+batch_size]
            texts = [c["text"] for c in batch]
            try:
                embeddings = self._get_ollama_embeddings(base_url, emb_model, texts)
                for idx, emb in enumerate(embeddings):
                    original_chunk = batch[idx]
                    processed_chunks.append({
                        "id": str(uuid.uuid4()),
                        "text": original_chunk["text"],
                        "doc_name": doc_name,
                        "chunk_index": original_chunk["chunk_index"],
                        "embedding": emb,
                        "metadata": {
                            "page": original_chunk["page"],
                            "file_size": file_size,
                            "added_at": added_at
                        }
                    })
                # Update progress after each batch
                progress = 60 + int((i + batch_size) / total * 30)
                processing_progress[doc_name] = min(progress, 90)
            except Exception as e:
                raise ValueError(f"Ollama embedding API failed: {str(e)}. Make sure Ollama is running and the model '{emb_model}' is pulled.")

        # 4. Save to Vector Store
        self.vector_store.add_chunks(processed_chunks)
        processing_progress[doc_name] = 100

        # Clean up progress entry after short delay
        def _clear_progress():
            time.sleep(5)
            processing_progress.pop(doc_name, None)
        threading.Thread(target=_clear_progress, daemon=True).start()

        return {
            "doc_name": doc_name,
            "chunk_count": len(processed_chunks),
            "file_size": file_size,
            "added_at": added_at
        }

    def chat_query(self, query: str, chat_history: List[Dict[str, str]] = None) -> Tuple[str, List[Dict[str, Any]]]:
        """Queries the vector store for context and calls LLM (Gemini or Ollama) for an answer."""
        settings = Config.get_settings()
        temperature = settings["temperature"]

        # 1. Embed user query
        # Ollama embedding for query
        base_url = settings.get("ollama_base_url", "http://localhost:11434")
        emb_model = settings.get("ollama_embedding_model", "nomic-embed-text")
        try:
            # Ensure embedding model is available
            ensure_ollama_model(emb_model)
            embeddings = self._get_ollama_embeddings(base_url, emb_model, [query])
            query_embedding = embeddings[0]
        except Exception as e:
            raise ValueError(f"Embedding query failed with Ollama: {str(e)}. Ensure Ollama is running and model '{emb_model}' is available.")

        # 2. Search similarity in Vector Store
        retrieved_chunks = self.vector_store.similarity_search(query_embedding, top_k=5)
        
        # 3. Build context string
        context_str = ""
        if retrieved_chunks:
            for idx, chunk in enumerate(retrieved_chunks):
                context_str += f"[Source {idx+1}] File: {chunk['doc_name']}, Page: {chunk['metadata'].get('page', 1)}\n"
                context_str += f"Content: {chunk['text']}\n\n"
        else:
            context_str = "No relevant documents have been uploaded or found for this query. Advise the user to upload documents."

        # 4. Prepare prompt & calling LLM
        # Ollama chat completion
        chat_model = settings.get("ollama_chat_model", "llama3.2")
        base_url = settings.get("ollama_base_url", "http://localhost:11434")
        
        system_prompt = """You are a professional AI Assistant specializing in document QA. \nAnswer the User Query using the provided context from the user's uploaded documents.\n\nGuidelines:\n1. Try to be very specific and factual. Rely primarily on the provided document context.\n2. If the answer is in the context, synthesize a clear, helpful response. Cite the file name and page number of your sources (e.g., \"According to [filename.pdf] (Page X)...\").\n3. If the answer cannot be found in the context but is a general question or related, answer it using your general knowledge, but clearly state: \"[General Knowledge Notice] This answer is based on general knowledge, as the uploaded documents do not contain this information.\"\n4. If there are no uploaded documents, politely inform the user they can upload documents via the panel on the left."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"--- DOCUMENT CONTEXT START ---\n{context_str}\n--- DOCUMENT CONTEXT END ---"}
        ]
        
        if chat_history:
            for msg in chat_history[-6:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": query})
        
        try:
            # Ensure chat model is available
            ensure_ollama_model(chat_model)
            answer = self._call_ollama_chat(base_url, chat_model, messages, temperature)
        except Exception as e:
            raise ValueError(f"Ollama chat completion failed: {str(e)}. Ensure Ollama is running and model '{chat_model}' is pulled.")
                
        return answer, retrieved_chunks
