import os
import re
from pathlib import Path
from typing import Dict, Any

# PDF
import pdfplumber

# Word
import docx

# PowerPoint
from pptx import Presentation

# Excel
import openpyxl
import pandas as pd

# Markdown
import markdown
from mistletoe import Document
from mistletoe.markdown_renderer import MarkdownRenderer

# Web
import requests
from bs4 import BeautifulSoup
import trafilatura

# YouTube - Using yt-dlp for reliable transcripts
import yt_dlp

# OCR
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe' 
from PIL import Image

# Legacy formats (textract)
import textract


class DocumentProcessor:
    """Universal document processor (PDF, DOCX, PPTX, XLSX, MD, TXT, URLs, YouTube, Images)."""

    SUPPORTED_EXTENSIONS = {
        '.pdf': 'PDF Document',
        '.docx': 'Word Document',
        '.doc': 'Word Document (Legacy)',
        '.pptx': 'PowerPoint Presentation',
        '.ppt': 'PowerPoint Presentation (Legacy)',
        '.xlsx': 'Excel Spreadsheet',
        '.xls': 'Excel Spreadsheet (Legacy)',
        '.md': 'Markdown File',
        '.txt': 'Text File',
        '.url': 'Web URL',
        '.youtube': 'YouTube Video',
        '.jpg': 'Image (OCR)',
        '.jpeg': 'Image (OCR)',
        '.png': 'Image (OCR)',
        '.bmp': 'Image (OCR)',
        '.tiff': 'Image (OCR)',
    }

    AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}

    def process_document(self, file_path: str, file_name: str, file_ext: str) -> Dict[str, Any]:
        if file_ext in self.AUDIO_EXTENSIONS:
            raise ValueError(
                f"Audio format '{file_ext}' is not currently supported. "
                "Please try another format (PDF, DOCX, PPTX, XLSX, MD, TXT, URL, YouTube, Image)."
            )

        processor = getattr(self, f'_process_{file_ext[1:]}', None)
        if processor is None:
            raise ValueError(f"Unsupported format: {file_ext}")

        result = processor(file_path, file_name)
        result['file_name'] = file_name
        result['file_ext'] = file_ext
        result['file_size'] = os.path.getsize(file_path)
        return result

    # ---------- PDF ----------
    def _process_pdf(self, file_path: str, file_name: str) -> Dict[str, Any]:
        text = ""
        metadata = {}
        with pdfplumber.open(file_path) as pdf:
            metadata['pages'] = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
        return {
            'content': text,
            'metadata': metadata,
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    # ---------- Word (.docx) ----------
    def _process_docx(self, file_path: str, file_name: str) -> Dict[str, Any]:
        doc = docx.Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        return {
            'content': text,
            'metadata': {'paragraphs': len(paragraphs), 'tables': len(doc.tables)},
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    # ---------- Word (.doc) legacy ----------
    def _process_doc(self, file_path: str, file_name: str) -> Dict[str, Any]:
        try:
            text = textract.process(file_path).decode('utf-8')
            return {
                'content': text,
                'metadata': {'format': 'legacy_doc'},
                'preview': text[:500] + "..." if len(text) > 500 else text,
                'word_count': len(text.split())
            }
        except Exception:
            raise Exception("Legacy .doc parsing failed. Please convert to .docx.")

    # ---------- PowerPoint (.pptx) ----------
    def _process_pptx(self, file_path: str, file_name: str) -> Dict[str, Any]:
        prs = Presentation(file_path)
        slides_content = []
        for slide in prs.slides:
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_text.append(shape.text)
                if hasattr(shape, "table"):
                    for row in shape.table.rows:
                        row_text = [cell.text for cell in row.cells if cell.text.strip()]
                        if row_text:
                            slide_text.append(" | ".join(row_text))
            slides_content.append("\n".join(slide_text))
        text = "\n\n".join(slides_content)
        return {
            'content': text,
            'metadata': {'slides': len(slides_content)},
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    # ---------- PowerPoint (.ppt) legacy ----------
    def _process_ppt(self, file_path: str, file_name: str) -> Dict[str, Any]:
        try:
            text = textract.process(file_path).decode('utf-8')
            return {
                'content': text,
                'metadata': {'format': 'legacy_ppt'},
                'preview': text[:500] + "..." if len(text) > 500 else text,
                'word_count': len(text.split())
            }
        except:
            raise Exception("Legacy .ppt parsing failed. Please convert to .pptx.")

    # ---------- Excel (.xlsx) ----------
    def _process_xlsx(self, file_path: str, file_name: str) -> Dict[str, Any]:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        all_text = []
        sheet_summaries = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            data = []
            for row in ws.iter_rows(values_only=True):
                row_data = [str(cell) if cell is not None else "" for cell in row]
                if any(row_data):
                    data.append(row_data)
            if data:
                df = pd.DataFrame(data[1:], columns=data[0] if data else None)
                sheet_summaries.append({
                    'name': sheet_name,
                    'rows': len(data),
                    'columns': len(data[0]) if data else 0,
                })
                text_sheet = df.to_string(index=False)
                all_text.append(f"Sheet: {sheet_name}\n{text_sheet}")
        text = "\n\n".join(all_text)
        return {
            'content': text,
            'metadata': {'sheets': len(wb.sheetnames), 'sheet_summaries': sheet_summaries},
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    # ---------- Excel (.xls) legacy ----------
    def _process_xls(self, file_path: str, file_name: str) -> Dict[str, Any]:
        try:
            import xlrd
            wb = xlrd.open_workbook(file_path)
            all_text = []
            for sheet in wb.sheets():
                text_parts = [f"Sheet: {sheet.name}"]
                for row in range(sheet.nrows):
                    row_data = [str(sheet.cell_value(row, col)) for col in range(sheet.ncols)]
                    text_parts.append(" | ".join(row_data))
                all_text.append("\n".join(text_parts))
            text = "\n\n".join(all_text)
            return {
                'content': text,
                'metadata': {'sheets': len(wb.sheets())},
                'preview': text[:500] + "..." if len(text) > 500 else text,
                'word_count': len(text.split())
            }
        except:
            raise Exception("Legacy .xls parsing failed. Please convert to .xlsx.")

    # ---------- Markdown ----------
    def _process_md(self, file_path: str, file_name: str) -> Dict[str, Any]:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        doc = Document(content)
        text = MarkdownRenderer().render(doc)
        return {
            'content': text,
            'metadata': {'lines': len(content.split('\n'))},
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    # ---------- Plain Text ----------
    def _process_txt(self, file_path: str, file_name: str) -> Dict[str, Any]:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        return {
            'content': text,
            'metadata': {'lines': len(text.split('\n'))},
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    # ---------- Web URL ----------
    def process_url(self, url: str) -> Dict[str, Any]:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        content = trafilatura.extract(resp.text, include_links=True, include_images=False)
        if not content:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()
            content = soup.get_text(separator='\n', strip=True)

        title = BeautifulSoup(resp.text, 'html.parser').title
        title = title.string if title else "Web Page"

        return {
            'content': content,
            'metadata': {'url': url, 'title': title, 'source': 'web'},
            'preview': content[:500] + "..." if len(content) > 500 else content,
            'word_count': len(content.split())
        }

    # ---------- YouTube (USING yt-dlp - RELIABLE) ----------
    def process_youtube(self, url: str) -> Dict[str, Any]:
        patterns = [r'youtube\.com/watch\?v=([^&]+)', r'youtu\.be/([^?]+)']
        video_id = None
        for pat in patterns:
            match = re.search(pat, url)
            if match:
                video_id = match.group(1)
                break
        if not video_id:
            video_id = url

        try:
            ydl_opts = {
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['en'],
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                subtitles = info.get('subtitles', {})
                auto_subs = info.get('automatic_captions', {})
                
                subtitle_data = None
                if 'en' in subtitles:
                    subtitle_data = subtitles['en']
                elif 'en' in auto_subs:
                    subtitle_data = auto_subs['en']
                elif subtitles:
                    subtitle_data = list(subtitles.values())[0]
                elif auto_subs:
                    subtitle_data = list(auto_subs.values())[0]
                else:
                    raise Exception("No subtitles available for this video")
                
                sub_url = subtitle_data[0]['url']
                sub_response = requests.get(sub_url, headers={'User-Agent': 'Mozilla/5.0'})
                sub_response.raise_for_status()
                
                raw_text = sub_response.text
                
                # Attempt to parse as JSON (YouTube JSON3 format)
                parsed_json = False
                try:
                    import json
                    data = json.loads(raw_text)
                    if "events" in data:
                        text_parts = []
                        for event in data["events"]:
                            for seg in event.get("segs", []):
                                if "utf8" in seg:
                                    text_parts.append(seg["utf8"].replace('\n', ' ').strip())
                        full_text = " ".join([t for t in text_parts if t])
                        parsed_json = True
                except Exception:
                    pass

                if not parsed_json:
                    lines = raw_text.split('\n')
                    text_parts = []
                    
                    for line in lines:
                        if not line.strip():
                            continue
                        if re.match(r'^\d+$', line.strip()):
                            continue
                        if '-->' in line:
                            continue
                        if line.strip().startswith('WEBVTT'):
                            continue
                        if line.strip().startswith('Kind:'):
                            continue
                        if line.strip().startswith('Language:'):
                            continue
                        if line.strip().startswith('NOTE'):
                            continue
                        clean_line = re.sub(r'<[^>]+>', '', line)
                        clean_line = clean_line.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                        if clean_line.strip():
                            text_parts.append(clean_line.strip())
                    
                    full_text = " ".join(text_parts)
                
                if not full_text:
                    text_parts = []
                    for line in lines:
                        line = re.sub(r'<[^>]+>', '', line)
                        if line.strip() and not re.match(r'^\d+$', line.strip()) and '-->' not in line:
                            text_parts.append(line.strip())
                    full_text = " ".join(text_parts)

                title = info.get('title', 'YouTube Video')
                
                return {
                    'content': full_text,
                    'metadata': {'video_id': video_id, 'title': title},
                    'preview': full_text[:500] + "..." if len(full_text) > 500 else full_text,
                    'word_count': len(full_text.split())
                }
                
        except Exception as e:
            raise Exception(f"YouTube transcript fetch failed: {str(e)}")

    # ---------- Images (OCR) ----------
    def _process_image(self, file_path: str, file_name: str) -> Dict[str, Any]:
        img = Image.open(file_path).convert('L')
        try:
            text = pytesseract.image_to_string(img)
        except Exception as e:
            raise Exception(f"OCR failed. Ensure Tesseract is installed. Error: {e}")
        return {
            'content': text,
            'metadata': {'width': img.width, 'height': img.height, 'format': img.format},
            'preview': text[:500] + "..." if len(text) > 500 else text,
            'word_count': len(text.split())
        }

    def _process_jpg(self, file_path: str, file_name: str):
        return self._process_image(file_path, file_name)

    def _process_jpeg(self, file_path: str, file_name: str):
        return self._process_image(file_path, file_name)

    def _process_png(self, file_path: str, file_name: str):
        return self._process_image(file_path, file_name)

    def _process_bmp(self, file_path: str, file_name: str):
        return self._process_image(file_path, file_name)

    def _process_tiff(self, file_path: str, file_name: str):
        return self._process_image(file_path, file_name)