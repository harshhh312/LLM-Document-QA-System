import os
import json
import logging
import traceback
from pathlib import Path
from typing import Dict, Any, Optional

from app.config import Config

logger = logging.getLogger(__name__)

MINDMAPS_DIR = Path("data/mindmaps")
MINDMAPS_DIR.mkdir(parents=True, exist_ok=True)

class MindMapGenerator:
    def __init__(self):
        pass

    def get_cache_path(self, doc_name: str) -> Path:
        return MINDMAPS_DIR / f"{doc_name}.json"

    def _call_ollama(self, prompt: str) -> str:
        import urllib.request
        settings = Config.get_settings()
        base_url = settings.get("ollama_base_url", "http://localhost:11434")
        chat_model = settings.get("ollama_chat_model", "llama3")
        temperature = 0.1 # Low temperature for more deterministic JSON

        url = f"{base_url.rstrip('/')}/api/chat"
        messages = [
            {"role": "system", "content": "You are a specialized AI that extracts document structures. You must ONLY return a valid JSON object. No explanation, no markdown formatting blocks outside the JSON."},
            {"role": "user", "content": prompt}
        ]
        
        data = json.dumps({
            "model": chat_model,
            "messages": messages,
            "options": {
                "temperature": temperature
            },
            "format": "json",
            "stream": False
        }).encode("utf-8")
        
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if "message" in res_data and "content" in res_data["message"]:
                return res_data["message"]["content"]
            else:
                raise ValueError(f"Ollama chat response missing message content: {res_data}")

    def generate_mindmap(self, doc_name: str, content: str, focus: Optional[str] = None) -> Dict[str, Any]:
        """Generates a mind map from document content, truncating if necessary."""
        # Truncate content to roughly 6000 words to avoid context limits
        truncated_content = " ".join(content.split()[:6000])
        
        focus_prompt = f"Focus the structure primarily around: {focus}." if focus else ""
        
        prompt = f"""Analyze the following document and extract its hierarchical structure as a mind map. {focus_prompt}
Document: {truncated_content}

Return JSON with exactly this structure:
{{
  "nodes": [
    {{"id": "root", "label": "Document Title", "type": "root", "page": 1}},
    {{"id": "node1", "label": "Topic 1", "type": "topic", "page": 1}}
  ],
  "edges": [
    {{"source": "root", "target": "node1"}}
  ]
}}
Allowed types for nodes are: "root", "topic", "subtopic", "concept". 
Extract up to 30 most important nodes. Ensure every node (except root) has an edge connecting it to a parent.
"""
        
        try:
            response_text = self._call_ollama(prompt)
            # Try to parse the JSON
            # Sometimes LLMs wrap it in markdown even if format='json' is set
            if response_text.strip().startswith('```json'):
                response_text = response_text.strip()[7:]
                if response_text.endswith('```'):
                    response_text = response_text[:-3]
                    
            mindmap_data = json.loads(response_text)
            
            # Basic validation
            if "nodes" not in mindmap_data or "edges" not in mindmap_data:
                raise ValueError("Generated JSON missing 'nodes' or 'edges'")
                
            # Add doc_name to result
            mindmap_data["doc_name"] = doc_name
            
            # Save to cache
            cache_path = self.get_cache_path(doc_name)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(mindmap_data, f, ensure_ascii=False, indent=2)
                
            return mindmap_data
            
        except Exception as e:
            logger.error("Failed to generate mindmap for %s: %s", doc_name, traceback.format_exc())
            raise e

    def get_cached_mindmap(self, doc_name: str) -> Optional[Dict[str, Any]]:
        cache_path = self.get_cache_path(doc_name)
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Error reading cached mindmap for %s: %s", doc_name, e)
                return None
        return None

    def delete_cache(self, doc_name: str):
        cache_path = self.get_cache_path(doc_name)
        if cache_path.exists():
            try:
                cache_path.unlink()
            except Exception as e:
                logger.error("Error deleting cached mindmap for %s: %s", doc_name, e)
