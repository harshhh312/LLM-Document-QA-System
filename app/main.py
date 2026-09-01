import os
import shutil
import logging
import traceback
import json
import re
import datetime
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import Config
from app.vector_store import SimpleVectorStore
from app.rag import RAGEngine, processing_progress
from app.document_processor import DocumentProcessor

# ============================================================
# APP INITIALIZATION
# ============================================================

app = FastAPI(title="NexusDoc AI - RAG Chatbot")

# Ensure logs directory exists
log_dir = Path(os.path.join(os.path.dirname(__file__), "../logs"))
log_dir.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    filename=os.path.join(log_dir, "app.log"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", traceback.format_exc())
    if getattr(app, "debug", False):
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# INITIALIZE COMPONENTS
# ============================================================

# Initialize vector store and RAG engine
vector_store = SimpleVectorStore()
rag_engine = RAGEngine(vector_store)

# Initialize document processor
processor = DocumentProcessor()

# Add mindmap router
try:
    from app.routers import mindmap
    app.include_router(mindmap.router)
except Exception as e:
    logger.error("Failed to include mindmap router: %s", e)

# Create folders
UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Supported formats
ALLOWED_EXTENSIONS = {
    '.pdf', '.docx', '.doc', '.pptx', '.ppt',
    '.xlsx', '.xls', '.md', '.txt',
    '.jpg', '.jpeg', '.png', '.bmp', '.tiff'
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def sanitize_filename(filename: str) -> str:
    r"""
    Remove characters invalid for Windows/Unix filenames.
    Windows forbids: < > : " / \ | ? *
    """
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    # Limit length to 100 characters
    if len(sanitized) > 100:
        sanitized = sanitized[:100]
    return sanitized

def check_ollama_status(base_url: str) -> bool:
    import urllib.request
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False

# ============================================================
# PYDANTIC MODELS
# ============================================================

class SettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    temperature: Optional[float] = None
    chat_model: Optional[str] = None
    llm_provider: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_chat_model: Optional[str] = None
    ollama_embedding_model: Optional[str] = None

class ChatRequest(BaseModel):
    query: str
    history: Optional[List[Dict[str, str]]] = []
    doc_name: Optional[str] = None

class URLPayload(BaseModel):
    url: str
    type: str = "url"  # "url" or "youtube"

class RegenerateRequest(BaseModel):
    focus: Optional[str] = None

# ============================================================
# WELL-KNOWN ROUTE (Chrome DevTools)
# ============================================================

@app.api_route("/.well-known/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def well_known_route(path: str):
    return Response(status_code=204)

# ============================================================
# STATUS & CONFIG ENDPOINTS
# ============================================================

@app.get("/api/status")
async def get_status():
    settings = Config.get_settings()
    provider = settings.get("llm_provider", "gemini")
    
    provider_ready = False
    if provider == "gemini":
        provider_ready = bool(Config.get_api_key())
    else:
        import asyncio
        ollama_url = settings.get("ollama_base_url", "http://localhost:11434")
        provider_ready = await asyncio.to_thread(check_ollama_status, ollama_url)

    active_docs = vector_store.get_active_documents()
    return {
        "status": "healthy",
        "api_key_configured": bool(Config.get_api_key()),
        "provider": provider,
        "provider_ready": provider_ready,
        "document_count": len(active_docs),
        "total_chunks": len(vector_store.chunks)
    }

@app.get("/api/config")
async def get_config():
    return Config.get_settings()

@app.post("/api/config")
async def update_config(settings: SettingsUpdate):
    try:
        data = {k: v for k, v in settings.model_dump().items() if v is not None}
        Config.save_settings(data)
        return {"status": "success", "message": "Settings updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# DOCUMENT ENDPOINTS
# ============================================================

@app.get("/api/documents")
async def list_documents():
    return vector_store.get_active_documents()

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and process any supported document format."""
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Save original file temporarily
    temp_file_path = UPLOAD_DIR / filename
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        # 1. Extract text using DocumentProcessor
        result = processor.process_document(str(temp_file_path), filename, ext)
        extracted_text = result['content']
        file_size_bytes = temp_file_path.stat().st_size
        if file_size_bytes < 1024:
            file_size_str = f"{file_size_bytes} B"
        elif file_size_bytes < 1024 * 1024:
            file_size_str = f"{file_size_bytes / 1024:.1f} KB"
        else:
            file_size_str = f"{file_size_bytes / (1024 * 1024):.1f} MB"
        
        # 2. Save extracted text as a temporary .txt file for RAG engine
        txt_filename = Path(filename).stem + ".txt"
        txt_path = UPLOAD_DIR / txt_filename
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(extracted_text)
        
        # 3. Process with RAG engine using the .txt file
        rag_result = rag_engine.process_and_add_document(txt_path, filename, file_size_str)
        
        # 4. Clean up the temporary .txt file
        if txt_path.exists():
            txt_path.unlink()
        
        # 5. Trigger background summarization
        try:
            doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == filename]
            from app.summarizer import run_background_summarization
            run_background_summarization(filename, doc_chunks)
            
            import threading
            def bg_mindmap():
                try:
                    from app.routers.mindmap import generator, get_document_full_text
                    content = get_document_full_text(filename)
                    generator.generate_mindmap(filename, content)
                except Exception as e:
                    logger.error(f"Background mindmap generation failed: {e}")
            threading.Thread(target=bg_mindmap, daemon=True).start()
        except Exception as e:
            logger.warning(f"Background tasks failed: {e}")
        
        return {
            "status": "success",
            "message": f"Document '{filename}' processed successfully. Chunks stored: {rag_result['chunk_count']}.",
            "data": rag_result,
            "file_type": ext,
            "word_count": result.get('word_count', 0),
            "preview": result.get('preview', '')
        }
        
    except Exception as e:
        # Clean up on error
        if temp_file_path.exists():
            temp_file_path.unlink()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.post("/api/documents/url")
async def process_url(payload: URLPayload):
    """Process a URL or YouTube link."""
    try:
        if payload.type == "youtube":
            result = processor.process_youtube(payload.url)
            print(f"[DEBUG] YouTube transcript (first 200 chars): {result['content'][:200]}")
        else:
            result = processor.process_url(payload.url)
            print(f"[DEBUG] URL content (first 200 chars): {result['content'][:200]}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Generate a sanitized document name
    title = result['metadata'].get('title', 'Untitled')
    safe_title = sanitize_filename(title)
    doc_name = f"{safe_title}_{int(time.time())}"
    file_size_str = f"{len(result['content']) / 1024:.1f} KB (text)"
    
    # Save extracted text as a temporary .txt file
    txt_filename = f"{doc_name}.txt"
    txt_path = UPLOAD_DIR / txt_filename
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(result['content'])
    
    # Process with RAG engine
    rag_result = rag_engine.process_and_add_document(txt_path, doc_name, file_size_str)
    
    # Clean up temp file
    if txt_path.exists():
        txt_path.unlink()
    
    return {
        "success": True,
        "doc_id": rag_result.get("doc_id", doc_name),
        "title": title,
        "word_count": result.get('word_count', 0),
        "preview": result.get('preview', '')
    }

@app.get("/api/documents/progress/{doc_name}")
async def get_document_progress(doc_name: str):
    progress = processing_progress.get(doc_name, 0)
    return {"doc_name": doc_name, "progress": progress}

@app.delete("/api/documents/{doc_name}")
async def delete_document(doc_name: str):
    try:
        deleted_count = vector_store.delete_document(doc_name)
        
        try:
            from app.summarizer import delete_insights_cache
            delete_insights_cache(doc_name)
            from app.routers.mindmap import generator
            generator.delete_cache(doc_name)
        except Exception as e:
            print(f"Failed to delete caches: {e}")
        
        local_file = UPLOAD_DIR / doc_name
        if local_file.exists():
            local_file.unlink()
            
        return {
            "status": "success", 
            "deleted_chunks": deleted_count,
            "message": f"Document '{doc_name}' deleted successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# SUMMARY & INSIGHTS ENDPOINTS
# ============================================================

@app.get("/api/documents/{doc_name}/summary")
async def get_document_summary(doc_name: str):
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found.")
    try:
        from app.summarizer import get_cached_insights, query_llm_for_insights
        insights = get_cached_insights(doc_name)
        if not insights:
            insights = query_llm_for_insights(doc_name, doc_chunks)
        return insights
    except Exception as e:
        logger.error("Error in get_document_summary: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{doc_name}/keywords")
async def get_document_keywords(doc_name: str):
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found.")
    try:
        from app.summarizer import get_cached_insights, query_llm_for_insights
        insights = get_cached_insights(doc_name)
        if not insights:
            insights = query_llm_for_insights(doc_name, doc_chunks)
        return {"keywords": insights.get("keywords", [])}
    except Exception as e:
        logger.error("Error in get_document_keywords: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{doc_name}/entities")
async def get_document_entities(doc_name: str):
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found.")
    try:
        from app.summarizer import get_cached_insights, query_llm_for_insights
        insights = get_cached_insights(doc_name)
        if not insights:
            insights = query_llm_for_insights(doc_name, doc_chunks)
        return insights.get("entities", {
            "people": [], "organizations": [], "dates": [], "locations": [], "monetary_values": []
        })
    except Exception as e:
        logger.error("Error in get_document_entities: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/documents/{doc_name}/regenerate-summary")
async def regenerate_summary(doc_name: str, request: RegenerateRequest):
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found.")
    try:
        from app.summarizer import query_llm_for_insights
        insights = query_llm_for_insights(doc_name, doc_chunks, focus_area=request.focus)
        return insights
    except Exception as e:
        logger.error("Error in regenerate_summary: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# CHAT ENDPOINT
# ============================================================

@app.post("/api/chat")
async def chat(request: ChatRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        answer, sources = rag_engine.chat_query(
            query=request.query,
            chat_history=request.history,
            doc_name=request.doc_name
        )
        return {"answer": answer, "sources": sources}
    except Exception as e:
        logger.error("Error in chat endpoint: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/test-retrieval")
async def test_retrieval(query: str, doc_name: Optional[str] = None):
    try:
        settings = Config.get_settings()
        base_url = settings.get("ollama_base_url", "http://localhost:11434")
        emb_model = settings.get("ollama_embedding_model", "nomic-embed-text")
        
        from app.rag import ensure_ollama_model
        ensure_ollama_model(emb_model)
        
        embeddings = rag_engine._get_ollama_embeddings(base_url, emb_model, [query])
        query_embedding = embeddings[0]
        
        retrieved_chunks = vector_store.similarity_search(query_embedding, top_k=7, doc_name=doc_name, query=query)
        return {"query": query, "doc_name": doc_name, "results": retrieved_chunks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# INTERACTIVE DOCUMENT EXPLORATION ENDPOINTS
# ============================================================

BOOKMARKS_FILE = Path("data/bookmarks.json")
HIGHLIGHTS_FILE = Path("data/highlights.json")

def load_json_file(file_path: Path) -> list:
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_json_file(file_path: Path, data: list):
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {file_path}: {e}")

def extract_pdf_toc(file_path: Path) -> list:
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(file_path))
        outline = reader.outline
        if outline:
            def parse_outline_nodes(nodes, lvl=1):
                res = []
                for item in nodes:
                    if isinstance(item, list):
                        res.extend(parse_outline_nodes(item, lvl + 1))
                    else:
                        try:
                            title = getattr(item, "title", None)
                            page_idx = reader.get_destination_page_number(item)
                            if title and page_idx is not None:
                                res.append({
                                    "title": title,
                                    "page": page_idx + 1,
                                    "level": lvl
                                })
                        except Exception:
                            pass
                return res
            toc = parse_outline_nodes(outline)
            if toc:
                return toc
    except Exception as e:
        print(f"Error extracting outlines: {e}")
        
    # Heuristic heading fallback
    try:
        reader = PdfReader(str(file_path))
        toc = []
        patterns = [
            r'^(?:Chapter|CHAPTER|Section|SECTION)\s+([0-9A-Z]+|\b[IVXLCDM]+\b)',
            r'^([0-9]+\.[0-9]*\.*)\s+([A-Z][a-zA-Z\s\-\:]+)',
            r'^([IVXLCDM]+)\.\s+([A-Z][a-zA-Z\s\-\:]+)'
        ]
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text:
                continue
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if not (4 <= len(line) <= 80):
                    continue
                is_heading = False
                lvl = 1
                for pat in patterns:
                    if re.match(pat, line):
                        is_heading = True
                        dots = line.split()[0].count('.') if line.split() else 0
                        if dots >= 2:
                            lvl = 3
                        elif dots == 1:
                            lvl = 2
                        else:
                            lvl = 1
                        break
                if not is_heading and line.isupper() and len(line) > 5 and re.search(r'[A-Z]', line):
                    is_heading = True
                    lvl = 2
                if is_heading:
                    toc.append({
                        "title": line,
                        "page": page_num + 1,
                        "level": lvl
                    })
        seen = set()
        unique_toc = []
        for h in toc:
            key = (h["title"].lower(), h["page"])
            if key not in seen:
                seen.add(key)
                unique_toc.append(h)
        if len(unique_toc) > 60:
            unique_toc = [h for h in unique_toc if h["level"] == 1]
        return unique_toc[:100]
    except Exception as e:
        print(f"Error generating fallback TOC: {e}")
        return []

def build_hierarchical_tree(headings: list) -> list:
    root = []
    stack = []
    for h in headings:
        node = {
            "title": h["title"],
            "page": h["page"],
            "level": h["level"],
            "children": []
        }
        while stack and stack[-1]["level"] >= h["level"]:
            stack.pop()
        if not stack:
            root.append(node)
        else:
            stack[-1]["children"].append(node)
        stack.append(node)
    return root

@app.get("/api/documents/{doc_name}/toc")
async def get_table_of_contents(doc_name: str):
    file_path = UPLOAD_DIR / doc_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    if file_path.suffix.lower() not in [".pdf"]:
        return {"sections": [{"title": doc_name, "page": 1, "level": 1}]}
    sections = extract_pdf_toc(file_path)
    if not sections:
        sections = [{"title": "Document Start", "page": 1, "level": 1}]
    return {"sections": sections}

@app.get("/api/documents/{doc_name}/structure")
async def get_document_structure(doc_name: str):
    file_path = UPLOAD_DIR / doc_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    if file_path.suffix.lower() not in [".pdf"]:
        return {
            "doc_name": doc_name,
            "total_pages": 1,
            "structure": [{"title": doc_name, "page": 1, "level": 1, "children": []}]
        }
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        total_pages = len(reader.pages)
    except:
        total_pages = 1
    sections = extract_pdf_toc(file_path)
    tree = build_hierarchical_tree(sections)
    if not tree:
        tree = [{"title": "Document Start", "page": 1, "level": 1, "children": []}]
    return {
        "doc_name": doc_name,
        "total_pages": total_pages,
        "structure": tree
    }

@app.get("/api/documents/{doc_name}/page/{page_num}")
async def get_page_content(doc_name: str, page_num: int):
    file_path = UPLOAD_DIR / doc_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            if page_num < 1 or page_num > len(reader.pages):
                raise HTTPException(status_code=400, detail=f"Page {page_num} out of bounds (1-{len(reader.pages)})")
            text = reader.pages[page_num - 1].extract_text() or ""
            return {"page": page_num, "total_pages": len(reader.pages), "text": text}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read PDF page: {str(e)}")
    elif suffix in [".txt", ".md", ".markdown"]:
        if page_num != 1:
            raise HTTPException(status_code=400, detail="Text/Markdown files only have page 1")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            return {"page": 1, "total_pages": 1, "text": text}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format")

# ============================================================
# BOOKMARKS ENDPOINTS
# ============================================================

@app.get("/api/documents/{doc_name}/bookmarks")
async def get_bookmarks(doc_name: str):
    all_bookmarks = load_json_file(BOOKMARKS_FILE)
    return [b for b in all_bookmarks if b.get("doc_name") == doc_name]

@app.post("/api/documents/{doc_name}/bookmarks")
async def add_bookmark(doc_name: str, bookmark_data: dict):
    import uuid
    all_bookmarks = load_json_file(BOOKMARKS_FILE)
    new_bookmark = {
        "id": bookmark_data.get("id") or str(uuid.uuid4()),
        "doc_name": doc_name,
        "page": bookmark_data.get("page", 1),
        "title": bookmark_data.get("title", f"Page {bookmark_data.get('page', 1)}"),
        "snippet": bookmark_data.get("snippet", ""),
        "created_at": bookmark_data.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    all_bookmarks = [b for b in all_bookmarks if not (b.get("doc_name") == doc_name and b.get("page") == new_bookmark["page"])]
    all_bookmarks.append(new_bookmark)
    save_json_file(BOOKMARKS_FILE, all_bookmarks)
    return new_bookmark

@app.delete("/api/documents/{doc_name}/bookmarks/{bookmark_id}")
async def delete_bookmark(doc_name: str, bookmark_id: str):
    all_bookmarks = load_json_file(BOOKMARKS_FILE)
    updated = [b for b in all_bookmarks if not (b.get("id") == bookmark_id or (b.get("doc_name") == doc_name and str(b.get("page")) == bookmark_id))]
    save_json_file(BOOKMARKS_FILE, updated)
    return {"status": "success", "message": "Bookmark deleted"}

# ============================================================
# HIGHLIGHTS ENDPOINTS
# ============================================================

@app.get("/api/documents/{doc_name}/highlights")
async def get_highlights(doc_name: str):
    all_highlights = load_json_file(HIGHLIGHTS_FILE)
    return [h for h in all_highlights if h.get("doc_name") == doc_name]

@app.post("/api/documents/{doc_name}/highlights")
async def add_highlight(doc_name: str, highlight_data: dict):
    import uuid
    all_highlights = load_json_file(HIGHLIGHTS_FILE)
    new_highlight = {
        "id": highlight_data.get("id") or str(uuid.uuid4()),
        "doc_name": doc_name,
        "page": highlight_data.get("page", 1),
        "text": highlight_data.get("text", ""),
        "color": highlight_data.get("color", "yellow"),
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    all_highlights.append(new_highlight)
    save_json_file(HIGHLIGHTS_FILE, all_highlights)
    return new_highlight

@app.delete("/api/documents/{doc_name}/highlights/{highlight_id}")
async def delete_highlight(doc_name: str, highlight_id: str):
    all_highlights = load_json_file(HIGHLIGHTS_FILE)
    updated = [h for h in all_highlights if h.get("id") != highlight_id]
    save_json_file(HIGHLIGHTS_FILE, updated)
    return {"status": "success", "message": "Highlight deleted"}

# ============================================================
# SERVE FRONTEND
# ============================================================

static_dir = Path("static")
static_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return {"message": "NexusDoc AI server running. Frontend index.html not found yet."}
    return FileResponse(index_file)