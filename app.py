"""
CiteFlex Pro - Flask Application
Serves the web UI and provides citation API endpoints.

This version uses the working WordDocumentProcessor and LinkActivator classes
from the monolithic version for reliable document handling.
"""

import os
import re
import io
import uuid
import html
import zipfile
import tempfile
import shutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import xml.etree.ElementTree as ET

# Import CiteFlex components
from models import CitationMetadata, CitationType, CitationStyle
from detectors import detect_type
from extractors import extract_interview, extract_newspaper, extract_government, extract_url
from router import route_and_search, search_legal, search_all_sources
from formatters import get_formatter

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'citeflex-dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size


# =============================================================================
# IN-MEMORY SESSION STORAGE
# =============================================================================

_sessions = {}


def get_session_data():
    """Get or create session data for current user."""
    session_id = session.get('session_id')
    if not session_id or session_id not in _sessions:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id
        _sessions[session_id] = {
            'doc_processor': None,
            'endnotes': [],
            'footnotes': [],
            'updates': {},
            'filename': None,
        }
    return _sessions[session_id]


def clear_session_data():
    """Clear current session data."""
    session_id = session.get('session_id')
    if session_id and session_id in _sessions:
        # Cleanup doc processor temp files
        if _sessions[session_id].get('doc_processor'):
            try:
                _sessions[session_id]['doc_processor'].cleanup()
            except:
                pass
        del _sessions[session_id]
    session.pop('session_id', None)


# =============================================================================
# LINK ACTIVATOR (from monolithic version)
# =============================================================================

class LinkActivator:
    """
    Post-processing module that converts plain text URLs in Word documents
    into clickable hyperlinks. Processes document.xml, endnotes.xml, and footnotes.xml.
    """
    
    @staticmethod
    def process(docx_path, output_path=None):
        """
        Process a .docx file to make all URLs clickable.
        """
        if output_path is None:
            output_path = docx_path
        
        temp_dir = tempfile.mkdtemp()
        
        try:
            with zipfile.ZipFile(docx_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            target_files = ['word/document.xml', 'word/endnotes.xml', 'word/footnotes.xml']
            
            for xml_file in target_files:
                full_path = os.path.join(temp_dir, xml_file)
                if not os.path.exists(full_path):
                    continue

                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                def linkify_text_node(match):
                    text_content = match.group(2) 
                    url_match = re.search(r'(https?://[^\s<>"]+)', text_content)
                    
                    if url_match:
                        url = url_match.group(1)
                        clean_url = url.rstrip('.,;)')
                        trailing_punct = url[len(clean_url):]
                        safe_url = html.escape(clean_url)
                        
                        parts = text_content.split(url, 1)
                        pre = parts[0]
                        post = parts[1] if len(parts) > 1 else ""
                        
                        fld_begin = r'<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                        instr = f'<w:r><w:instrText xml:space="preserve"> HYPERLINK "{safe_url}" </w:instrText></w:r>'
                        fld_sep = r'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                        display = (
                            f'<w:r>'
                            f'<w:rPr><w:color w:val="0000FF"/><w:u w:val="single"/></w:rPr>'
                            f'<w:t>{clean_url}</w:t>'
                            f'</w:r>'
                        )
                        fld_end = r'<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                        
                        full_field_xml = f"{fld_begin}{instr}{fld_sep}{display}{fld_end}"
                        new_xml = f"{pre}</w:t></w:r>{full_field_xml}<w:r><w:t>{trailing_punct}{post}"
                        return f"{match.group(1)}{new_xml}{match.group(3)}"
                        
                    return match.group(0)

                run_pattern = r'(<w:r[^\>]*>)(.*?<w:t[^>]*>.*?<\/w:t>.*?)(<\/w:r>)'
                
                def process_run(run_match):
                    run_inner = run_match.group(2)
                    if 'HYPERLINK' in run_inner or 'w:instrText' in run_inner:
                        return run_match.group(0)
                    return re.sub(r'(<w:t[^>]*>)(.*?)(</w:t>)', linkify_text_node, run_match.group(0))

                new_content = re.sub(run_pattern, process_run, content, flags=re.DOTALL)
                
                if new_content != content:
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
            
            return True, "Hyperlinks activated successfully"

        except Exception as e:
            return False, str(e)
        finally:
            shutil.rmtree(temp_dir)


# =============================================================================
# WORD DOCUMENT PROCESSOR (from monolithic version - WORKING)
# =============================================================================

class WordDocumentProcessor:
    """
    Processes Word documents to read and write endnotes/footnotes.
    Preserves the main document body while allowing citation fixes.
    
    KEY: Uses temp directory extraction for reliable XML handling.
    """
    
    NS = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'xml': 'http://www.w3.org/XML/1998/namespace'
    }
    
    def __init__(self, file_bytes):
        """Initialize with file bytes."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Extract docx to temp directory
        with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as z:
            z.extractall(self.temp_dir)
    
    def get_endnotes(self):
        """Extract all endnotes from the document."""
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        if not os.path.exists(endnotes_path):
            return []
        
        try:
            tree = ET.parse(endnotes_path)
            root = tree.getroot()
            notes = []
            
            for endnote in root.findall('.//w:endnote', self.NS):
                note_id = endnote.get(f"{{{self.NS['w']}}}id")
                
                # Skip system endnotes (id 0 and -1)
                try:
                    if int(note_id) < 1:
                        continue
                except (ValueError, TypeError):
                    continue
                
                # Extract all text from this endnote
                text_parts = []
                for t in endnote.findall('.//w:t', self.NS):
                    if t.text:
                        text_parts.append(t.text)
                
                full_text = "".join(text_parts).strip()
                if full_text:
                    notes.append({'id': note_id, 'text': full_text, 'type': 'endnote'})
            
            return notes
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error reading endnotes: {e}")
            return []
    
    def get_footnotes(self):
        """Extract all footnotes from the document."""
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        if not os.path.exists(footnotes_path):
            return []
        
        try:
            tree = ET.parse(footnotes_path)
            root = tree.getroot()
            notes = []
            
            for footnote in root.findall('.//w:footnote', self.NS):
                note_id = footnote.get(f"{{{self.NS['w']}}}id")
                
                # Skip system footnotes (id 0 and -1)
                try:
                    if int(note_id) < 1:
                        continue
                except (ValueError, TypeError):
                    continue
                
                # Extract all text
                text_parts = []
                for t in footnote.findall('.//w:t', self.NS):
                    if t.text:
                        text_parts.append(t.text)
                
                full_text = "".join(text_parts).strip()
                if full_text:
                    notes.append({'id': f'fn_{note_id}', 'text': full_text, 'type': 'footnote'})
            
            return notes
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error reading footnotes: {e}")
            return []
    
    def write_endnote(self, note_id, new_content):
        """
        Replace an endnote's content with new formatted citation.
        Handles <i> tags for italics. PRESERVES the endnoteRef element.
        """
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        if not os.path.exists(endnotes_path):
            return False
        
        try:
            # Register namespace to preserve it
            ET.register_namespace('w', self.NS['w'])
            ET.register_namespace('xml', self.NS['xml'])
            
            tree = ET.parse(endnotes_path)
            root = tree.getroot()
            
            # Find the target endnote
            target = None
            for endnote in root.findall('.//w:endnote', self.NS):
                if endnote.get(f"{{{self.NS['w']}}}id") == str(note_id):
                    target = endnote
                    break
            
            if target is None:
                return False
            
            # Find or create paragraph
            para = target.find('.//w:p', self.NS)
            if para is None:
                para = ET.SubElement(target, f"{{{self.NS['w']}}}p")
            else:
                # FIXED: Preserve paragraph properties AND endnoteRef run
                preserved_pPr = None
                preserved_endnoteRef_run = None
                
                for child in list(para):
                    tag = child.tag.replace(f"{{{self.NS['w']}}}", "")
                    
                    # Preserve paragraph properties
                    if tag == 'pPr':
                        preserved_pPr = child
                        continue
                    
                    # Check if this run contains endnoteRef
                    if tag == 'r':
                        endnote_ref = child.find(f".//{{{self.NS['w']}}}endnoteRef")
                        if endnote_ref is not None:
                            preserved_endnoteRef_run = child
                            continue
                    
                    # Remove all other children
                    para.remove(child)
                
                # If no endnoteRef run was found, create one
                if preserved_endnoteRef_run is None:
                    ref_run = ET.Element(f"{{{self.NS['w']}}}r")
                    rPr = ET.SubElement(ref_run, f"{{{self.NS['w']}}}rPr")
                    rStyle = ET.SubElement(rPr, f"{{{self.NS['w']}}}rStyle")
                    rStyle.set(f"{{{self.NS['w']}}}val", "EndnoteReference")
                    ET.SubElement(ref_run, f"{{{self.NS['w']}}}endnoteRef")
                    
                    # Insert after pPr if it exists, otherwise at beginning
                    if preserved_pPr is not None:
                        idx = list(para).index(preserved_pPr) + 1
                        para.insert(idx, ref_run)
                    else:
                        para.insert(0, ref_run)
            
            # Parse content using regex to handle <i> tags
            parts = re.split(r'(<i>.*?</i>)', html.unescape(new_content))
            
            for part in parts:
                if not part:
                    continue
                    
                run = ET.SubElement(para, f"{{{self.NS['w']}}}r")
                
                # Check if this is italic text
                italic_match = re.match(r'<i>(.*?)</i>', part)
                if italic_match:
                    rPr = ET.SubElement(run, f"{{{self.NS['w']}}}rPr")
                    ET.SubElement(rPr, f"{{{self.NS['w']}}}i")
                    text_content = italic_match.group(1)
                else:
                    text_content = part
                
                t = ET.SubElement(run, f"{{{self.NS['w']}}}t")
                t.text = text_content
                t.set(f"{{{self.NS['xml']}}}space", "preserve")
            
            tree.write(endnotes_path, encoding='UTF-8', xml_declaration=True)
            return True
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error writing endnote: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def write_footnote(self, note_id, new_content):
        """
        Replace a footnote's content with new formatted citation.
        Handles <i> tags for italics. PRESERVES the footnoteRef element.
        """
        # Remove fn_ prefix if present
        if str(note_id).startswith('fn_'):
            note_id = str(note_id)[3:]
        
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        if not os.path.exists(footnotes_path):
            return False
        
        try:
            ET.register_namespace('w', self.NS['w'])
            ET.register_namespace('xml', self.NS['xml'])
            
            tree = ET.parse(footnotes_path)
            root = tree.getroot()
            
            target = None
            for footnote in root.findall('.//w:footnote', self.NS):
                if footnote.get(f"{{{self.NS['w']}}}id") == str(note_id):
                    target = footnote
                    break
            
            if target is None:
                return False
            
            para = target.find('.//w:p', self.NS)
            if para is None:
                para = ET.SubElement(target, f"{{{self.NS['w']}}}p")
            else:
                # FIXED: Preserve paragraph properties AND footnoteRef run
                preserved_pPr = None
                preserved_footnoteRef_run = None
                
                for child in list(para):
                    tag = child.tag.replace(f"{{{self.NS['w']}}}", "")
                    
                    # Preserve paragraph properties
                    if tag == 'pPr':
                        preserved_pPr = child
                        continue
                    
                    # Check if this run contains footnoteRef
                    if tag == 'r':
                        footnote_ref = child.find(f".//{{{self.NS['w']}}}footnoteRef")
                        if footnote_ref is not None:
                            preserved_footnoteRef_run = child
                            continue
                    
                    # Remove all other children
                    para.remove(child)
                
                # If no footnoteRef run was found, create one
                if preserved_footnoteRef_run is None:
                    ref_run = ET.Element(f"{{{self.NS['w']}}}r")
                    rPr = ET.SubElement(ref_run, f"{{{self.NS['w']}}}rPr")
                    rStyle = ET.SubElement(rPr, f"{{{self.NS['w']}}}rStyle")
                    rStyle.set(f"{{{self.NS['w']}}}val", "FootnoteReference")
                    ET.SubElement(ref_run, f"{{{self.NS['w']}}}footnoteRef")
                    
                    if preserved_pPr is not None:
                        idx = list(para).index(preserved_pPr) + 1
                        para.insert(idx, ref_run)
                    else:
                        para.insert(0, ref_run)
            
            # Parse content using regex to handle <i> tags
            parts = re.split(r'(<i>.*?</i>)', html.unescape(new_content))
            
            for part in parts:
                if not part:
                    continue
                    
                run = ET.SubElement(para, f"{{{self.NS['w']}}}r")
                
                italic_match = re.match(r'<i>(.*?)</i>', part)
                if italic_match:
                    rPr = ET.SubElement(run, f"{{{self.NS['w']}}}rPr")
                    ET.SubElement(rPr, f"{{{self.NS['w']}}}i")
                    text_content = italic_match.group(1)
                else:
                    text_content = part
                
                t = ET.SubElement(run, f"{{{self.NS['w']}}}t")
                t.text = text_content
                t.set(f"{{{self.NS['xml']}}}space", "preserve")
            
            tree.write(footnotes_path, encoding='UTF-8', xml_declaration=True)
            return True
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error writing footnote: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def save_to_buffer(self):
        """Save the modified document to a BytesIO buffer."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arcname)
        buffer.seek(0)
        return buffer
    
    def cleanup(self):
        """Remove temporary files."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.cleanup()
        except:
            pass


# =============================================================================
# TYPE-AWARE CITATION SEARCH
# =============================================================================

def search_citations(query, style='chicago', max_results=5):
    """
    Search for citation candidates - TYPE-AWARE routing.
    """
    results = []
    
    # Map style names
    style_map = {
        'chicago': 'Chicago Manual of Style',
        'bluebook': 'Bluebook',
        'oscola': 'OSCOLA',
        'apa': 'APA 7',
        'mla': 'MLA 9',
    }
    full_style = style_map.get(style.lower(), 'Chicago Manual of Style')
    
    # Detect citation type
    detection = detect_type(query)
    citation_type = detection.citation_type
    confidence = detection.confidence
    
    print(f"[Search] Query: '{query[:50]}...' → Type: {citation_type.name} ({confidence:.2f})")
    
    # Get formatter
    formatter = get_formatter(full_style)
    
    # TYPE-AWARE ROUTING
    if citation_type == CitationType.LEGAL:
        metadata = search_legal(query)
        if metadata and metadata.has_minimum_data():
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.INTERVIEW:
        metadata = extract_interview(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.NEWSPAPER:
        metadata = extract_newspaper(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.GOVERNMENT:
        metadata = extract_government(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.URL:
        metadata = extract_url(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'medium'))
    
    elif citation_type == CitationType.MEDICAL:
        candidates = _search_medical_sources(query, max_results)
        for meta in candidates:
            results.append(_format_result(meta, formatter, 'high'))
    
    elif citation_type == CitationType.BOOK:
        candidates = _search_book_sources(query, max_results)
        for meta in candidates:
            results.append(_format_result(meta, formatter, 'high'))
    
    else:
        # JOURNAL / UNKNOWN
        candidates = _search_journal_sources(query, max_results)
        for meta in candidates:
            conf = 'high' if meta.source_engine in ['Crossref', 'Google CSE'] else 'medium'
            results.append(_format_result(meta, formatter, conf))
    
    return results[:max_results]


def _format_result(metadata, formatter, confidence='medium'):
    """Format a metadata object into a result dict for the frontend."""
    try:
        formatted = formatter.format(metadata)
    except Exception as e:
        print(f"[Format] Error formatting: {e}")
        formatted = metadata.title or metadata.case_name or metadata.raw_source
    
    return {
        'formatted': formatted,
        'source': metadata.source_engine or 'Unknown',
        'type': metadata.citation_type.name.lower(),
        'confidence': confidence,
        'metadata': metadata.to_dict() if hasattr(metadata, 'to_dict') else {},
    }


def _search_journal_sources(query, limit=5):
    """Search academic sources for journal articles."""
    from engines import GoogleCSEEngine, CrossrefEngine, OpenAlexEngine, SemanticScholarEngine
    
    results = []
    seen = set()
    
    engines = [
        ('google_cse', GoogleCSEEngine),
        ('crossref', CrossrefEngine),
        ('openalex', OpenAlexEngine),
        ('semantic_scholar', SemanticScholarEngine),
    ]
    
    for name, EngineClass in engines:
        if len(results) >= limit:
            break
        try:
            engine = EngineClass()
            if hasattr(engine, 'search_multiple'):
                candidates = engine.search_multiple(query, limit=2)
            else:
                result = engine.search(query)
                candidates = [result] if result else []
            
            for meta in candidates:
                if meta and meta.has_minimum_data():
                    key = (meta.title or '').lower()[:50]
                    if key and key not in seen:
                        seen.add(key)
                        results.append(meta)
        except Exception as e:
            print(f"[Search] {name} error: {e}")
    
    return results[:limit]


def _search_book_sources(query, limit=5):
    """Search book sources."""
    from engines import GoogleBooksEngine, OpenLibraryEngine
    
    results = []
    seen = set()
    
    engines = [
        ('google_books', GoogleBooksEngine),
        ('open_library', OpenLibraryEngine),
    ]
    
    for name, EngineClass in engines:
        if len(results) >= limit:
            break
        try:
            engine = EngineClass()
            if hasattr(engine, 'search_multiple'):
                candidates = engine.search_multiple(query, limit=3)
            else:
                result = engine.search(query)
                candidates = [result] if result else []
            
            for meta in candidates:
                if meta and meta.has_minimum_data():
                    key = (meta.title or '').lower()[:50]
                    if key and key not in seen:
                        seen.add(key)
                        meta.citation_type = CitationType.BOOK
                        results.append(meta)
        except Exception as e:
            print(f"[Search] {name} error: {e}")
    
    return results[:limit]


def _search_medical_sources(query, limit=5):
    """Search medical/PubMed sources."""
    from engines import PubMedEngine, CrossrefEngine
    
    results = []
    seen = set()
    
    engines = [
        ('pubmed', PubMedEngine),
        ('crossref', CrossrefEngine),
    ]
    
    for name, EngineClass in engines:
        if len(results) >= limit:
            break
        try:
            engine = EngineClass()
            if hasattr(engine, 'search_multiple'):
                candidates = engine.search_multiple(query, limit=3)
            else:
                result = engine.search(query)
                candidates = [result] if result else []
            
            for meta in candidates:
                if meta and meta.has_minimum_data():
                    key = (meta.title or '').lower()[:50]
                    if key and key not in seen:
                        seen.add(key)
                        meta.citation_type = CitationType.MEDICAL
                        results.append(meta)
        except Exception as e:
            print(f"[Search] {name} error: {e}")
    
    return results[:limit]


# =============================================================================
# FRONTEND ROUTES
# =============================================================================

@app.route('/')
def index():
    """Serve the main UI."""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    """Upload a document and extract endnotes/footnotes."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.docx'):
            return jsonify({'success': False, 'error': 'Only .docx files are supported'}), 400
        
        # Read file bytes
        file_bytes = file.read()
        
        # Create document processor
        doc_processor = WordDocumentProcessor(file_bytes)
        
        # Extract notes
        endnotes = doc_processor.get_endnotes()
        footnotes = doc_processor.get_footnotes()
        
        # Store in session
        session_data = get_session_data()
        
        # Cleanup old processor if exists
        if session_data.get('doc_processor'):
            try:
                session_data['doc_processor'].cleanup()
            except:
                pass
        
        session_data['doc_processor'] = doc_processor
        session_data['endnotes'] = endnotes
        session_data['footnotes'] = footnotes
        session_data['updates'] = {}
        session_data['filename'] = secure_filename(file.filename)
        
        # Combine endnotes and footnotes for the frontend
        all_notes = endnotes + footnotes
        
        print(f"[Upload] Extracted {len(endnotes)} endnotes, {len(footnotes)} footnotes")
        
        return jsonify({
            'success': True,
            'endnotes': all_notes,
            'count': len(all_notes),
            'message': f'Found {len(endnotes)} endnotes and {len(footnotes)} footnotes'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/search', methods=['POST'])
def search():
    """Search for citation candidates."""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        style = data.get('style', 'chicago')
        
        if not text:
            return jsonify({'results': []})
        
        # Handle "ibid." specially
        if text.lower().strip() in ['ibid.', 'ibid', 'id.', 'id']:
            return jsonify({
                'results': [{
                    'formatted': 'ibid.',
                    'source': 'Short Form',
                    'type': 'reference',
                    'confidence': 'high'
                }]
            })
        
        # Type-aware search
        results = search_citations(text, style, max_results=5)
        
        return jsonify({'results': results})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'results': [], 'error': str(e)}), 500


@app.route('/update', methods=['POST'])
def update():
    """Update a specific note with new text."""
    try:
        data = request.get_json()
        note_id = data.get('id')
        new_html = data.get('html', '')
        
        if not note_id:
            return jsonify({'success': False, 'error': 'No note ID provided'}), 400
        
        # Store the update
        session_data = get_session_data()
        session_data['updates'][note_id] = new_html
        
        print(f"[Update] Note {note_id} → {new_html[:50]}...")
        
        return jsonify({'success': True})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/reset', methods=['POST'])
def reset():
    """Clear session state and start fresh."""
    try:
        clear_session_data()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download', methods=['GET'])
def download():
    """Download the modified document with all updates applied."""
    try:
        session_data = get_session_data()
        
        doc_processor = session_data.get('doc_processor')
        if not doc_processor:
            return jsonify({'success': False, 'error': 'No document uploaded'}), 400
        
        updates = session_data.get('updates', {})
        
        # Apply all updates to the document
        for note_id, new_html in updates.items():
            if note_id.startswith('fn_'):
                doc_processor.write_footnote(note_id, new_html)
            else:
                doc_processor.write_endnote(note_id, new_html)
        
        # Save to buffer
        output_buffer = doc_processor.save_to_buffer()
        
        # Activate hyperlinks
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
            tmp.write(output_buffer.getvalue())
            tmp_path = tmp.name
        
        success, msg = LinkActivator.process(tmp_path)
        print(f"[Download] LinkActivator: {success}, {msg}")
        
        with open(tmp_path, 'rb') as f:
            final_bytes = f.read()
        
        os.unlink(tmp_path)
        
        # Generate filename
        original_name = session_data.get('filename', 'document.docx')
        base_name = os.path.splitext(original_name)[0]
        download_name = f'{base_name}_formatted.docx'
        
        return send_file(
            io.BytesIO(final_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=download_name
        )
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# API ROUTES
# =============================================================================

@app.route('/api/cite', methods=['POST'])
def api_cite():
    """API endpoint for single citation lookup."""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago')
        
        if not query:
            return jsonify({'success': False, 'error': 'No query provided'}), 400
        
        results = search_citations(query, style, max_results=1)
        
        if results:
            return jsonify({
                'success': True,
                'citation': results[0]['formatted'],
                'type': results[0]['type'],
                'metadata': results[0].get('metadata', {})
            })
        else:
            return jsonify({'success': False, 'error': 'No citation found', 'query': query}), 404
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cite/candidates', methods=['POST'])
def api_cite_candidates():
    """API endpoint for multiple citation candidates."""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago')
        max_results = data.get('max_results', 5)
        
        if not query:
            return jsonify({'success': False, 'error': 'No query provided'}), 400
        
        detection = detect_type(query)
        results = search_citations(query, style, max_results)
        
        return jsonify({
            'success': True,
            'detected_type': detection.citation_type.name.lower(),
            'confidence': detection.confidence,
            'candidates': results
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/detect', methods=['POST'])
def api_detect():
    """API endpoint for type detection only."""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        
        if not query:
            return jsonify({'type': 'unknown', 'confidence': 0})
        
        detection = detect_type(query)
        
        return jsonify({
            'type': detection.citation_type.name.lower(),
            'confidence': detection.confidence
        })
    
    except Exception as e:
        return jsonify({'type': 'unknown', 'confidence': 0, 'error': str(e)})


@app.route('/api/styles', methods=['GET'])
def api_styles():
    """Return available citation styles."""
    return jsonify({'styles': ['Chicago', 'Bluebook', 'OSCOLA', 'APA', 'MLA']})


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '2.1',
        'timestamp': datetime.utcnow().isoformat()
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
