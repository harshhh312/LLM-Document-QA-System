import logging
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.mindmap_generator import MindMapGenerator
from app.main import vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["MindMap"])
generator = MindMapGenerator()

class RegenerateMindMapRequest(BaseModel):
    focus: Optional[str] = None

def get_document_full_text(doc_name: str) -> str:
    doc_chunks = [c for c in vector_store.chunks if c["doc_name"] == doc_name]
    if not doc_chunks:
        raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found in vector index.")
    
    # Sort chunks by page/index to assemble text sequentially
    doc_chunks.sort(key=lambda x: (x.get("metadata", {}).get("page", 0), x.get("chunk_index", 0)))
    return "\n".join([c["text"] for c in doc_chunks])

@router.get("/{doc_name}/mindmap")
async def get_mindmap(doc_name: str):
    """Get the cached mind map, or generate it if it doesn't exist."""
    cached = generator.get_cached_mindmap(doc_name)
    if cached:
        return cached
        
    # Generate on the fly if not cached
    try:
        content = get_document_full_text(doc_name)
        return generator.generate_mindmap(doc_name, content)
    except Exception as e:
        logger.error("Error in get_mindmap: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{doc_name}/mindmap/regenerate")
async def regenerate_mindmap(doc_name: str, request: RegenerateMindMapRequest):
    """Force regenerate the mind map, optionally with a focus."""
    try:
        content = get_document_full_text(doc_name)
        return generator.generate_mindmap(doc_name, content, focus=request.focus)
    except Exception as e:
        logger.error("Error in regenerate_mindmap: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
