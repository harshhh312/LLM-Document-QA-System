import os
import shutil
import logging
import traceback
import json
import re
import datetime
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

app = FastAPI(title="NexusDoc AI - RAG Chatbot")

# Ensure logs directory exists
log_dir = Path(os.path.join(os.path.dirname(__file__), "../logs"))
log_dir.mkdir(parents=True, exist_ok=True)
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
    # In production hide details, in debug mode show full exception
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

# Initialize vector store and RAG engine
vector_store = SimpleVectorStore()
rag_engine = RAGEngine(vector_store)

# Create folders inside data/ if they do not exist
UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

def check_ollama_status(base_url: str) -> bool:
    import urllib.request
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False

@app.api_route("/.well-known/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def well_known_route(path: str):
    # Silently handle Chrome DevTools and other well‑known path checks
    return Response(status_code=204)

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
        # Convert Pydantic object to clean dict
        data = {k: v for k, v in settings.model_dump().items() if v is not None}
        Config.save_settings(data)
        # Reload state in RAG engine if API key changed

        return {"status": "success", "message": "Settings updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents")
async def list_documents():
    return vector_store.get_active_documents()

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(filename).suffix.lower()
    if suffix not in [".pdf", ".txt", ".md", ".markdown"]:
        raise HTTPException(status_code=400, detail="Unsupported file format. Only PDF, TXT, and MD are supported.")

    # Save file locally
    temp_file_path = UPLOAD_DIR / filename
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size_bytes = temp_file_path.stat().st_size
        if file_size_bytes < 1024:
            file_size_str = f"{file_size_bytes} B"
        elif file_size_bytes < 1024 * 1024:
            file_size_str = f"{file_size_bytes / 1024:.1f} KB"
        else:
            file_size_str = f"{file_size_bytes / (1024 * 1024):.1f} MB"

        # Process and add document (progress tracked internally)
        result = rag_engine.process_and_add_document(temp_file_path, filename, file_size_str)
        
        # Trigger background summarization insights computation
        try:
            doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == filename]
            from app.summarizer import run_background_summarization
            run_background_summarization(filename, doc_chunks)
        except Exception as e:
            print(f"Background summarization failed to start: {e}")

        # Return detailed success message
        return {
            "status": "success",
            "message": f"Document '{filename}' uploaded and processed successfully. Chunks stored: {result['chunk_count']}.",
            "data": result,
            "progress": 100
        }
    except Exception as e:
        # Clean up temp file in case of error
        if temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/progress/{doc_name}")
async def get_document_progress(doc_name: str):
    """Retrieve processing progress (0-100) for a document.
    Returns 0 if not found or processing completed.
    """
    progress = processing_progress.get(doc_name, 0)
    return {"doc_name": doc_name, "progress": progress}

@app.delete("/api/documents/{doc_name}")
async def delete_document(doc_name: str):
    try:
        deleted_count = vector_store.delete_document(doc_name)
        
        # Delete summary cache
        try:
            from app.summarizer import delete_insights_cache
            delete_insights_cache(doc_name)
        except Exception as e:
            print(f"Failed to delete summary cache for '{doc_name}': {e}")
        
        # Delete file from local upload directory if it exists
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

class RegenerateRequest(BaseModel):
    focus: Optional[str] = None

@app.get("/api/documents/{doc_name}/summary")
async def get_document_summary(doc_name: str):
    """Generate or retrieve comprehensive document summary and statistics."""
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found in vector index.")
    try:
        from app.summarizer import get_cached_insights, query_llm_for_insights
        insights = get_cached_insights(doc_name)
        if not insights:
            insights = query_llm_for_insights(doc_name, doc_chunks)
        return insights
    except Exception as e:
        logger.error("Error in get_document_summary for %s: %s", doc_name, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{doc_name}/keywords")
async def get_document_keywords(doc_name: str):
    """Extract keywords with frequencies."""
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found in vector index.")
    try:
        from app.summarizer import get_cached_insights, query_llm_for_insights
        insights = get_cached_insights(doc_name)
        if not insights:
            insights = query_llm_for_insights(doc_name, doc_chunks)
        return {"keywords": insights.get("keywords", [])}
    except Exception as e:
        logger.error("Error in get_document_keywords for %s: %s", doc_name, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{doc_name}/entities")
async def get_document_entities(doc_name: str):
    """Extract named entities."""
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found in vector index.")
        
    try:
        from app.summarizer import get_cached_insights, query_llm_for_insights
        insights = get_cached_insights(doc_name)
        if not insights:
            insights = query_llm_for_insights(doc_name, doc_chunks)
        return insights.get("entities", {
            "people": [], "organizations": [], "dates": [], "locations": [], "monetary_values": []
        })
    except Exception as e:
        logger.error("Error in get_document_entities for %s: %s", doc_name, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/documents/{doc_name}/regenerate-summary")
async def regenerate_summary(doc_name: str, request: RegenerateRequest):
    """Regenerate summary with a custom focus area."""
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found in vector index.")
    try:
        from app.summarizer import query_llm_for_insights
        insights = query_llm_for_insights(doc_name, doc_chunks, focus_area=request.focus)
        return insights
    except Exception as e:
        logger.error("Error in regenerate_summary for %s: %s", doc_name, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(request: ChatRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    try:
        answer, sources = rag_engine.chat_query(
            query=request.query,
            chat_history=request.history
        )
        return {
            "answer": answer,
            "sources": sources
        }
    except Exception as e:
        logger.error("Error in chat endpoint: %s", traceback.format_exc())
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
    import re
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(file_path))
        # Try outlines first
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
                        dots = line.split()[0].count('.')
                        if dots >= 2:
                            lvl = 3
                        elif dots == 1:
                            lvl = 2
                        else:
                            lvl = 1
                        break
                
                # Check uppercase fallback
                if not is_heading and line.isupper() and len(line) > 5 and re.search(r'[A-Z]', line):
                    is_heading = True
                    lvl = 2
                
                if is_heading:
                    toc.append({
                        "title": line,
                        "page": page_num + 1,
                        "level": lvl
                    })
        # Filter duplicates & limit size
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
    """Extract TOC from document structure"""
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
    """Get full document structure for map view"""
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
    """Get text content for a specific page"""
    file_path = UPLOAD_DIR / doc_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
        
    suffix = file_path.suffix.lower()
    
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            if page_num < 1 or page_num > len(reader.pages):
                raise HTTPException(status_code=400, detail=f"Page number {page_num} out of bounds (1-{len(reader.pages)})")
            
            text = reader.pages[page_num - 1].extract_text() or ""
            return {
                "page": page_num,
                "total_pages": len(reader.pages),
                "text": text
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read PDF page: {str(e)}")
            
    elif suffix in [".txt", ".md", ".markdown"]:
        if page_num != 1:
            raise HTTPException(status_code=400, detail="Text/Markdown files only have page 1")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            return {
                "page": 1,
                "total_pages": 1,
                "text": text
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format")

# Bookmarks Endpoints
@app.get("/api/documents/{doc_name}/bookmarks")
async def get_bookmarks(doc_name: str):
    """Retrieve all bookmarks for a document"""
    all_bookmarks = load_json_file(BOOKMARKS_FILE)
    doc_bookmarks = [b for b in all_bookmarks if b.get("doc_name") == doc_name]
    return doc_bookmarks

@app.post("/api/documents/{doc_name}/bookmarks")
async def add_bookmark(doc_name: str, bookmark_data: dict):
    """Add a bookmark to a document"""
    import uuid
    import datetime
    
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
    """Remove a bookmark"""
    all_bookmarks = load_json_file(BOOKMARKS_FILE)
    updated = [b for b in all_bookmarks if not (b.get("id") == bookmark_id or (b.get("doc_name") == doc_name and str(b.get("page")) == bookmark_id))]
    save_json_file(BOOKMARKS_FILE, updated)
    return {"status": "success", "message": "Bookmark deleted"}

# Highlights Endpoints
@app.get("/api/documents/{doc_name}/highlights")
async def get_highlights(doc_name: str):
    """Retrieve all highlights for a document"""
    all_highlights = load_json_file(HIGHLIGHTS_FILE)
    doc_highlights = [h for h in all_highlights if h.get("doc_name") == doc_name]
    return doc_highlights

@app.post("/api/documents/{doc_name}/highlights")
async def add_highlight(doc_name: str, highlight_data: dict):
    """Add a highlight to a document"""
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
    """Remove a highlight"""
    all_highlights = load_json_file(HIGHLIGHTS_FILE)
    updated = [h for h in all_highlights if h.get("id") != highlight_id]
    save_json_file(HIGHLIGHTS_FILE, updated)
    return {"status": "success", "message": "Highlight deleted"}

# Serve Frontend static files
# Place standard files in local project 'static' dir
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return {"message": "NexusDoc AI server running. Frontend index.html not found yet."}
    return FileResponse(index_file)
