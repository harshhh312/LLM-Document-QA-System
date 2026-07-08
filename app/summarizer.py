import re
import json
import urllib.request
import threading
from pathlib import Path
from app.config import Config

# Stopwords list for keyword frequency analysis
STOPWORDS = {
    "the", "and", "a", "of", "to", "in", "is", "that", "it", "on", "for", "with", "this", "as", "are", "by", "an", "be", "was", "were", 
    "from", "at", "or", "have", "has", "had", "but", "not", "they", "their", "will", "would", "which", "about", "there", "more", "can", 
    "also", "into", "than", "other", "some", "them", "these", "its", "then", "only", "such", "over", "very", "when", "your", "been", 
    "through", "during", "who", "whom", "whose", "which", "what", "where", "how", "why", "we", "our", "us", "you", "he", "she", "him", 
    "her", "his", "hers", "i", "me", "my", "myself", "yourself", "themselves", "ourselves", "itself", "about", "above", "below", "up",
    "down", "here", "there", "all", "any", "both", "each", "few", "more", "most", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "s", "t", "can", "will", "just", "should", "now"
}

# Directory for summary caches
CACHE_DIR = Path("data/summaries")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def count_syllables(word: str) -> int:
    """Heuristic function to count syllables in a word."""
    word = word.lower().strip()
    if not word:
        return 0
    
    # Syllables vowel-group counting heuristic
    vowels = "aeiouy"
    count = 0
    prev_is_vowel = False
    
    for char in word:
        is_vowel = char in vowels
        if is_vowel and not prev_is_vowel:
            count += 1
        prev_is_vowel = is_vowel
        
    # Subtract silent 'e' at the end of word (approximation)
    if word.endswith('e') and not word.endswith('le'):
        count -= 1
        
    if count <= 0:
        count = 1
        
    return count

def estimate_sentences(text: str) -> int:
    """Helper to split sentences using punctuation and whitespace."""
    sentences = re.split(r'[.!?]+(?:\s+|$)', text)
    sentences = [s for s in sentences if s.strip()]
    return max(1, len(sentences))

def detect_language(text: str) -> str:
    """Determines the language based on common functional stopword intersections."""
    words = set(re.findall(r'\b[a-z]{2,10}\b', text.lower()))
    if not words:
        return "English"
        
    lang_markers = {
        "English": {"the", "and", "with", "from", "this", "that", "for", "have", "you"},
        "Spanish": {"el", "la", "los", "las", "con", "para", "como", "este", "del", "una"},
        "French": {"le", "la", "les", "avec", "pour", "dans", "est", "une", "des", "qui"},
        "German": {"der", "die", "das", "und", "mit", "von", "auf", "ist", "eine", "den"},
        "Italian": {"il", "la", "i", "gli", "con", "per", "come", "questo", "del", "una"},
    }
    
    best_lang = "English"
    max_matches = 0
    for lang, markers in lang_markers.items():
        matches = len(words.intersection(markers))
        if matches > max_matches:
            max_matches = matches
            best_lang = lang
            
    return best_lang

def calculate_readability(text: str) -> dict:
    """Calculates Flesch Reading Ease score and returns reading stats."""
    words = re.findall(r'\b[a-zA-Z]+\b', text)
    word_count = len(words)
    char_count = len(text)
    
    if word_count == 0:
        return {
            "ease_score": 100.0,
            "readability_label": "Very Easy",
            "word_count": 0,
            "char_count": char_count,
            "sentence_count": 0,
            "reading_time_min": 1
        }
        
    sentence_count = estimate_sentences(text)
    
    # Count syllables
    syllable_count = sum(count_syllables(w) for w in words)
    
    # Flesch Reading Ease Formula
    # 206.835 - 1.015 * (total_words / total_sentences) - 84.6 * (total_syllables / total_words)
    avg_sentence_length = word_count / sentence_count
    avg_syllables_per_word = syllable_count / word_count
    
    ease_score = 206.835 - (1.015 * avg_sentence_length) - (84.6 * avg_syllables_per_word)
    # Clamp ease score between 0 and 100
    ease_score = max(0.0, min(100.0, ease_score))
    
    # Determine label
    if ease_score >= 90.0:
        label = "Very Easy (5th grade)"
    elif ease_score >= 80.0:
        label = "Easy (6th grade)"
    elif ease_score >= 70.0:
        label = "Fairly Easy (7th grade)"
    elif ease_score >= 60.0:
        label = "Standard (8th-9th grade)"
    elif ease_score >= 50.0:
        label = "Fairly Difficult (High School)"
    elif ease_score >= 30.0:
        label = "Difficult (College)"
    else:
        label = "Very Difficult (College Graduate)"
        
    # Reading time (assume 200 words per minute average)
    reading_time = max(1, int(round(word_count / 200)))
    
    return {
        "ease_score": round(ease_score, 1),
        "readability_label": label,
        "word_count": word_count,
        "char_count": char_count,
        "sentence_count": sentence_count,
        "reading_time_min": reading_time
    }

def extract_keywords_algo(text: str) -> list:
    """Algorithmically extracts top keywords with counts, ignoring stopwords."""
    words = re.findall(r'\b[a-zA-Z]{4,15}\b', text.lower())
    freq = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
            
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [{"word": word, "count": count} for word, count in sorted_words[:15]]

def get_representative_text(chunks: list, max_chars: int = 12000) -> str:
    """Collects text samples from the start, middle, and end of the document to fit within context."""
    # Ensure chunks are sorted in logical index order
    sorted_chunks = sorted(chunks, key=lambda x: x.get("chunk_index", 0))
    if not sorted_chunks:
        return ""
        
    full_text = " ".join([c["text"] for c in sorted_chunks])
    if len(full_text) <= max_chars:
        return full_text
        
    num_chunks = len(sorted_chunks)
    sampled_indices = []
    
    # Beginning
    sampled_indices.extend(range(min(2, num_chunks)))
    # Middle
    if num_chunks > 4:
        mid = num_chunks // 2
        sampled_indices.extend([mid - 1, mid])
    # End
    if num_chunks > 6:
        sampled_indices.extend([num_chunks - 2, num_chunks - 1])
        
    sampled_indices = sorted(list(set(sampled_indices)))
    sampled_text = " ... ".join([sorted_chunks[i]["text"] for i in sampled_indices])
    
    return sampled_text[:max_chars]

def get_cache_path(doc_name: str) -> Path:
    """Gets the path to the summary cache for a document."""
    # Sanitize name to prevent path traversal
    safe_name = re.sub(r'[^a-zA-Z0-9_\.-]', '_', doc_name)
    return CACHE_DIR / f"{safe_name}.json"

def get_cached_insights(doc_name: str) -> dict:
    """Loads dashboard insights from local JSON cache if exists."""
    cache_path = get_cache_path(doc_name)
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading summary cache for '{doc_name}': {e}")
    return {}

def save_insights_cache(doc_name: str, data: dict):
    """Saves dashboard insights to local JSON cache."""
    cache_path = get_cache_path(doc_name)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving summary cache for '{doc_name}': {e}")

def delete_insights_cache(doc_name: str):
    """Removes a document's cache file."""
    cache_path = get_cache_path(doc_name)
    if cache_path.exists():
        try:
            cache_path.unlink()
        except Exception as e:
            print(f"Error deleting summary cache for '{doc_name}': {e}")

def generate_fallback_dashboard_data(doc_name: str, text_stats: dict, focus_area: str = None) -> dict:
    """Generates an elegant fallback if LLM request fails or times out."""
    summary_text = (
        f"This is an automatically generated insights dashboard fallback for the document '{doc_name}'. "
        "The local LLM was either busy or failed to return a valid JSON structure within the expected time. "
        "Basic file analytics are computed below.\n\n"
    )
    if focus_area:
        summary_text += f"Focus request: '{focus_area}' was received but could not be processed by the LLM."
        
    return {
        "summary": summary_text,
        "key_points": [
            {"point": "Calculated document readability indicators programmatically.", "score": "High", "page": 1},
            {"point": "Calculated word, character, and sentence counts.", "score": "Medium", "page": 1},
            {"point": "Ready for chat questions. Use the chat window to ask details about this document.", "score": "High", "page": 1}
        ],
        "topics": [
            {"topic": "Document Content", "percentage": 100, "mentions": text_stats.get("sentence_count", 5), "keywords": ["document", "text", "file"]}
        ],
        "entities": {
            "people": [],
            "organizations": [],
            "dates": [],
            "locations": [],
            "monetary_values": []
        },
        "sentiment": {
            "overall": "Neutral",
            "score": 0.0,
            "tones": ["Objective"],
            "sections": [
                {"section": "Full Document", "sentiment": "Neutral", "reason": "No text anomalies detected."}
            ]
        }
    }

def query_llm_for_insights(doc_name: str, chunks: list, focus_area: str = None) -> dict:
    """Calls Ollama to generate structured JSON document insights."""
    # 1. Compute stats programmatically (never fails)
    sorted_chunks = sorted(chunks, key=lambda x: x.get("chunk_index", 0))
    full_text = " ".join([c["text"] for c in sorted_chunks])
    
    text_stats = calculate_readability(full_text)
    language = detect_language(full_text)
    keywords = extract_keywords_algo(full_text)
    
    # Find total pages
    max_page = 1
    for c in chunks:
        page = c.get("metadata", {}).get("page", 1)
        if page > max_page:
            max_page = page
            
    # Gather document date and file size from first chunk
    added_at = "Unknown"
    file_size = "Unknown"
    if chunks:
        meta = chunks[0].get("metadata", {})
        added_at = meta.get("added_at", "Unknown")
        file_size = meta.get("file_size", "Unknown")
        
    doc_stats = {
        "total_pages": max_page,
        "total_words": text_stats["word_count"],
        "total_characters": text_stats["char_count"],
        "reading_time_min": text_stats["reading_time_min"],
        "readability_score": text_stats["ease_score"],
        "readability_label": text_stats["readability_label"],
        "language": language,
        "file_size": file_size,
        "added_at": added_at
    }
    
    # 2. Query Ollama for Executive Summary and semantic metadata
    settings = Config.get_settings()
    base_url = settings.get("ollama_base_url", "http://localhost:11434")
    chat_model = settings.get("ollama_chat_model", "llama3")
    
    representative_text = get_representative_text(chunks)
    
    focus_prompt = ""
    if focus_area:
        focus_prompt = f"Please generate the executive summary focusing specifically on: '{focus_area}'.\n"

    system_prompt = (
        "You are an expert document analysis system. Your goal is to analyze the provided text and return "
        "a JSON object with key insights. You must return ONLY valid JSON. Do not write any markdown codeblocks "
        "like ```json, any introductory explanation, or trailing text. Just return the JSON object."
    )
    
    user_prompt = f"""{focus_prompt}Analyze the following document text and return a JSON object containing:
1. "summary": A 3 to 5 paragraph summary of the document's purpose, main topic, key arguments, and conclusions. Make it rich, professional, and well-written.
2. "key_points": A list of 5 to 10 dicts, each with "point" (the actual content), "score" ("High" | "Medium" | "Low"), and "page" (the estimated page number it appears on, e.g. 1).
3. "topics": A list of 3 to 5 dicts, each with "topic" (topic name), "percentage" (an integer percentage, e.g. 40), "mentions" (an integer, e.g. 12), and "keywords" (a list of 3-5 keywords).
4. "entities": An object with:
   - "people": list of dicts with "name" and "mentions"
   - "organizations": list of dicts with "name" and "mentions"
   - "dates": list of dicts with "name" and "mentions"
   - "locations": list of dicts with "name" and "mentions"
   - "monetary_values": list of dicts with "name" and "mentions"
5. "sentiment": An object with:
   - "overall": "Positive" | "Negative" | "Neutral"
   - "score": a float from -1.0 to 1.0 (indicating the overall tone polarity)
   - "tones": list of 2-3 emotional tone words (e.g., "Confident", "Cautious", "Objective", "Critical")
   - "sections": list of dicts with "section" (name of section), "sentiment" ("Positive" | "Neutral" | "Negative"), and "reason" (short sentence).

Document Content:
{representative_text}
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    url = f"{base_url.rstrip('/')}/api/chat"
    data = json.dumps({
        "model": chat_model,
        "messages": messages,
        "options": {
            "temperature": 0.2
        },
        "stream": False,
        "format": "json"
    }).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    parsed_llm = None
    try:
        # Check if Ollama service is reachable
        with urllib.request.urlopen(req, timeout=75) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data["message"]["content"].strip()
            
            # Remove potential markdown block wrappers
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\n', '', content)
                content = re.sub(r'\n```$', '', content)
                content = content.strip()
                
            parsed_llm = json.loads(content)
    except Exception as e:
        print(f"Ollama dashboard LLM query failed for document '{doc_name}': {e}")
        
    # If LLM failed, build fallback data
    if not parsed_llm:
        parsed_llm = generate_fallback_dashboard_data(doc_name, text_stats, focus_area)
        
    # 3. Combine programmatically computed values and LLM insights
    final_insights = {
        "doc_name": doc_name,
        "statistics": doc_stats,
        "keywords": keywords,
        "summary": parsed_llm.get("summary", ""),
        "key_points": parsed_llm.get("key_points", []),
        "topics": parsed_llm.get("topics", []),
        "entities": parsed_llm.get("entities", {
            "people": [], "organizations": [], "dates": [], "locations": [], "monetary_values": []
        }),
        "sentiment": parsed_llm.get("sentiment", {
            "overall": "Neutral", "score": 0.0, "tones": ["Objective"], "sections": []
        })
    }
    
    # Save cache
    save_insights_cache(doc_name, final_insights)
    return final_insights

def run_background_summarization(doc_name: str, chunks: list):
    """Triggers LLM insights generation in the background so it is cached early."""
    def run():
        try:
            print(f"Triggering background insights caching for '{doc_name}'...")
            query_llm_for_insights(doc_name, chunks)
            print(f"Background insights caching complete for '{doc_name}'!")
        except Exception as e:
            print(f"Error in background summarization for '{doc_name}': {e}")
            
    threading.Thread(target=run, daemon=True).start()
