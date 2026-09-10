# LLM Document Question Answering System

A full-stack Retrieval-Augmented Generation (RAG) application that lets you upload documents (and even YouTube videos) and ask questions with context-aware answers.

Supports both **local LLMs via Ollama** and **Google Gemini**.

## Features

- Multi-format document support
  - PDF, DOCX, PPTX, Excel, Markdown, TXT, HTML
  - YouTube video transcripts
  - Image OCR + audio transcription (Whisper)
- Semantic search with custom vector store
- Document summarization
- Mind-map generation
- PDF viewer with highlighting & bookmarking
- Background processing with progress tracking
- Switchable LLM providers (Ollama / Gemini)

## Tech Stack

**Backend**
- FastAPI
- Custom RAG pipeline + vector store (NumPy cosine similarity)
- Ollama (local) / Google Gemini
- Multi-format parsers (pypdf, python-docx, python-pptx, pdfplumber, Whisper, etc.)

**Frontend**
- HTML, CSS, JavaScript
- Integrated PDF viewer

## Architecture
Upload → Document Processor → Chunking → Embeddings → Vector Store
↓
User Query → Embedding → Similarity Search → Context + LLM → Answer

## Quick Start

### Prerequisites
- Python 3.10+
- Ollama (recommended for local use) → https://ollama.com
- (Optional) Gemini API key

### Installation

git clone https://github.com/harshhh312/LLM-Document-QA-System.git

cd LLM-Document-QA-System

python -m venv venv

source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # then edit .env

**Run**
python run.py
Open → http://localhost:8000
**Project Structure**
textapp/
├── main.py                 # FastAPI app

├── config.py               # Settings & provider config

├── document_processor.py   # Multi-format extraction

├── rag.py                  # RAG engine

├── vector_store.py         # Custom vector store

├── summarizer.py

└── routers/                # Mind-map etc.
static/                     # Frontend
data/                       # Uploads & vector store (gitignored)

**Future Improvements**
.Replace custom store with FAISS / Chroma
.Add LangChain integration option
.Better evaluation metrics (retrieval accuracy)
.Docker support
.User authentication

**Author**
Harsh Chaudhari




