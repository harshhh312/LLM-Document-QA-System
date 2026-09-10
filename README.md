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
