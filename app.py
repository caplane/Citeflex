"""
CiteFlex Pro - Flask Application
Serves the web UI and provides citation API endpoints.

This version matches the frontend's expected endpoints:
- POST /upload - Upload document, extract endnotes/footnotes
- POST /search - Search for citation candidates (type-aware)
- POST /update - Update a specific note with new text
- POST /reset - Clear session state
- GET /download - Download the modified document

Also maintains the /api/* endpoints for programmatic access.
"""

import os
import re
import io
import uuid
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
from xml.etree import ElementTree as ET

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
# For production, consider using Redis or database storage

_sessions = {}


def get_session_data():
    """Get or create session data for current user."""
    session_id = session.get('session_id')
    if not session_id or session_id not in _sessions:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id
        _sessions[session_id] = {
            'doc_bytes': None,
            'endnotes': [],
            'footnotes': [],
            'updates': {},  # id -> new_html
            'filename': None,
        }
    return _sessions[session_id]


def clear_session_data():
    """Clear current session data."""
    session_id = session.get('session_id')
    if session_id and session_id in _sessions:
        del _sessions[session_id]
    session.pop('session_id', None)


# =============================================================================
# WORD DOCUMENT PROCESSING
# =============================================================================

# XML namespaces for docx
NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
}

# Register namespaces to preserve them on output
for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)
ET.register_namespace('', NAMESPACES['w'])


def extract_notes_from_docx(file_bytes):
    """
    Extract endnotes and footnotes from a .docx file.
    
    Returns:
        tuple: (endnotes_list, footnotes_list)
        Each list contains dicts with 'id', 'text', 'type'
    """
    endnotes = []
    footnotes = []
    
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as zf:
            # Extract endnotes
            if 'word/endnotes.xml' in zf.namelist():
                endnotes_xml = zf.read('word/endnotes.xml')
                endnotes = _parse_notes_xml(endnotes_xml, 'endnote')
            
            # Extract footnotes
            if 'word/footnotes.xml' in zf.namelist():
                footnotes_xml = zf.read('word/footnotes.xml')
                footnotes = _parse_notes_xml(footnotes_xml, 'footnote')
    
    except Exception as e:
        print(f"[Extract] Error reading document: {e}")
        raise
    
    return endnotes, footnotes


def _parse_notes_xml(xml_bytes, note_type):
    """Parse endnotes.xml or footnotes.xml and extract text."""
    notes = []
    
    try:
        root = ET.fromstring(xml_bytes)
        
        # Find all endnote or footnote elements
        tag = f'{{{NAMESPACES["w"]}}}{note_type}'
        for note_elem in root.findall(f'.//{tag}'):
            note_id = note_elem.get(f'{{{NAMESPACES["w"]}}}id')
            
            # Skip separator notes (id 0 and -1)
            if note_id in ['0', '-1']:
                continue
            
            # Extract all text from paragraphs
            text_parts = []
            for p in note_elem.findall(f'.//{{{NAMESPACES["w"]}}}p'):
                for t in p.findall(f'.//{{{NAMESPACES["w"]}}}t'):
                    if t.text:
                        text_parts.append(t.text)
            
            text = ''.join(text_parts).strip()
            
            if text:
                prefix = 'fn_' if note_type == 'footnote' else ''
                notes.append({
                    'id': f'{prefix}{note_id}',
                    'text': text,
                    'type': note_type
                })
    
    except Exception as e:
        print(f"[Parse] Error parsing {note_type}s: {e}")
    
    return notes


def update_notes_in_docx(file_bytes, updates, add_links=True):
    """
    Update notes in a .docx file with new text.
    
    Args:
        file_bytes: Original document bytes
        updates: Dict mapping note_id -> new_html
        add_links: Whether to make URLs clickable
        
    Returns:
        Modified document bytes
    """
    try:
        # Read the original document
        input_zip = zipfile.ZipFile(io.BytesIO(file_bytes), 'r')
        output_buffer = io.BytesIO()
        output_zip = zipfile.ZipFile(output_buffer, 'w', zipfile.ZIP_DEFLATED)
        
        for item in input_zip.namelist():
            data = input_zip.read(item)
            
            # Modify endnotes.xml
            if item == 'word/endnotes.xml':
                data = _update_notes_xml(data, updates, 'endnote', add_links)
            
            # Modify footnotes.xml
            elif item == 'word/footnotes.xml':
                data = _update_notes_xml(data, updates, 'footnote', add_links)
            
            output_zip.writestr(item, data)
        
        input_zip.close()
        output_zip.close()
        
        return output_buffer.getvalue()
    
    except Exception as e:
        print(f"[Update] Error updating document: {e}")
        raise


def _update_notes_xml(xml_bytes, updates, note_type, add_links=True):
    """Update notes in XML with new text."""
    try:
        root = ET.fromstring(xml_bytes)
        
        tag = f'{{{NAMESPACES["w"]}}}{note_type}'
        for note_elem in root.findall(f'.//{tag}'):
            note_id = note_elem.get(f'{{{NAMESPACES["w"]}}}id')
            
            # Check if we have an update for this note
            prefix = 'fn_' if note_type == 'footnote' else ''
            lookup_id = f'{prefix}{note_id}'
            
            if lookup_id in updates:
                new_text = updates[lookup_id]
                _replace_note_content(note_elem, new_text, add_links)
        
        return ET.tostring(root, encoding='unicode').encode('utf-8')
    
    except Exception as e:
        print(f"[UpdateXML] Error: {e}")
        return xml_bytes


def _replace_note_content(note_elem, new_text, add_links=True):
    """Replace the content of a note element with new text."""
    # Find the first paragraph (skip the reference marker paragraph if present)
    paragraphs = note_elem.findall(f'.//{{{NAMESPACES["w"]}}}p')
    
    if not paragraphs:
        return
    
    # Use the last paragraph for content (first often has just the reference number)
    target_p = paragraphs[-1] if len(paragraphs) > 1 else paragraphs[0]
    
    # Clear existing runs (but preserve paragraph properties)
    runs_to_remove = target_p.findall(f'{{{NAMESPACES["w"]}}}r')
    for r in runs_to_remove:
        target_p.remove(r)
    
    # Parse HTML-like formatting in new_text
    # Handle <i>...</i> for italics
    parts = _parse_formatted_text(new_text)
    
    for part in parts:
        run = ET.SubElement(target_p, f'{{{NAMESPACES["w"]}}}r')
        
        # Add run properties if needed (italic, bold, etc.)
        if part.get('italic') or part.get('bold'):
            rPr = ET.SubElement(run, f'{{{NAMESPACES["w"]}}}rPr')
            if part.get('italic'):
                ET.SubElement(rPr, f'{{{NAMESPACES["w"]}}}i')
            if part.get('bold'):
                ET.SubElement(rPr, f'{{{NAMESPACES["w"]}}}b')
        
        # Add the text
        t = ET.SubElement(run, f'{{{NAMESPACES["w"]}}}t')
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        t.text = part['text']


def _parse_formatted_text(html_text):
    """
    Parse HTML-like text into parts with formatting info.
    
    Handles:
    - <i>...</i> for italics
    - <em>...</em> for italics
    - <b>...</b> for bold
    - <strong>...</strong> for bold
    
    Returns list of dicts: [{'text': '...', 'italic': bool, 'bold': bool}, ...]
    """
    parts = []
    
    # Simple regex-based parsing
    pattern = r'<(i|em|b|strong)>(.*?)</\1>|([^<]+)'
    
    for match in re.finditer(pattern, html_text, re.DOTALL | re.IGNORECASE):
        tag = match.group(1)
        tagged_text = match.group(2)
        plain_text = match.group(3)
        
        if plain_text:
            # Plain text
            parts.append({'text': plain_text, 'italic': False, 'bold': False})
        elif tag and tagged_text:
            # Tagged text
            is_italic = tag.lower() in ['i', 'em']
            is_bold = tag.lower() in ['b', 'strong']
            parts.append({'text': tagged_text, 'italic': is_italic, 'bold': is_bold})
    
    # If no matches, return the whole text as plain
    if not parts:
        parts.append({'text': html_text, 'italic': False, 'bold': False})
    
    return parts


# =============================================================================
# TYPE-AWARE CITATION SEARCH
# =============================================================================

def search_citations(query, style='chicago', max_results=5):
    """
    Search for citation candidates - TYPE-AWARE routing.
    
    This is the key function that routes:
    - Legal queries → Legal engine only (not Crossref/Google Books)
    - Journal queries → Academic engines (not Google Books)
    - Book queries → Book engines
    
    Args:
        query: Raw citation text
        style: Citation style name
        max_results: Maximum candidates to return
        
    Returns:
        List of result dicts with 'formatted', 'source', 'type', 'confidence'
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
    
    # ==========================================================================
    # TYPE-AWARE ROUTING
    # ==========================================================================
    
    if citation_type == CitationType.LEGAL:
        # LEGAL: Only search legal engine
        metadata = search_legal(query)
        if metadata and metadata.has_minimum_data():
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.INTERVIEW:
        # INTERVIEW: Local extractor only
        metadata = extract_interview(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.NEWSPAPER:
        # NEWSPAPER: Local extractor
        metadata = extract_newspaper(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.GOVERNMENT:
        # GOVERNMENT: Local extractor
        metadata = extract_government(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'high'))
    
    elif citation_type == CitationType.URL:
        # URL: Local extractor
        metadata = extract_url(query)
        if metadata:
            results.append(_format_result(metadata, formatter, 'medium'))
    
    elif citation_type == CitationType.MEDICAL:
        # MEDICAL: PubMed + academic engines
        candidates = _search_medical_sources(query, max_results)
        for meta in candidates:
            results.append(_format_result(meta, formatter, 'high'))
    
    elif citation_type == CitationType.BOOK:
        # BOOK: Book engines only
        candidates = _search_book_sources(query, max_results)
        for meta in candidates:
            results.append(_format_result(meta, formatter, 'high'))
    
    else:
        # JOURNAL / UNKNOWN: Academic engines + Google CSE (NO Google Books)
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
# FRONTEND ROUTES (matches index.html expectations)
# =============================================================================

@app.route('/')
def index():
    """Serve the main UI."""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    """
    Upload a document and extract endnotes/footnotes.
    
    Frontend expects:
        Request: FormData with 'file'
        Response: { success: true, endnotes: [{id, text, type}, ...] }
    """
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
        
        # Extract notes
        endnotes, footnotes = extract_notes_from_docx(file_bytes)
        
        # Store in session
        session_data = get_session_data()
        session_data['doc_bytes'] = file_bytes
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
    """
    Search for citation candidates.
    
    Frontend expects:
        Request: { text: "...", style: "chicago" }
        Response: { results: [{formatted, source, type, confidence}, ...] }
    """
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
    """
    Update a specific note with new text.
    
    Frontend expects:
        Request: { id: "1", html: "<i>Citation</i>..." }
        Response: { success: true }
    """
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
    """
    Clear session state and start fresh.
    
    Frontend expects:
        Response: { success: true }
    """
    try:
        clear_session_data()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download', methods=['GET'])
def download():
    """
    Download the modified document with all updates applied.
    
    Frontend expects:
        Response: .docx file download
    """
    try:
        session_data = get_session_data()
        
        if not session_data.get('doc_bytes'):
            return jsonify({'success': False, 'error': 'No document uploaded'}), 400
        
        # Apply all updates to the document
        updated_bytes = update_notes_in_docx(
            session_data['doc_bytes'],
            session_data.get('updates', {}),
            add_links=True
        )
        
        # Generate filename
        original_name = session_data.get('filename', 'document.docx')
        base_name = os.path.splitext(original_name)[0]
        download_name = f'{base_name}_formatted.docx'
        
        return send_file(
            io.BytesIO(updated_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=download_name
        )
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# API ROUTES (for programmatic access - backwards compatibility)
# =============================================================================

@app.route('/api/cite', methods=['POST'])
def api_cite():
    """
    API endpoint for single citation lookup.
    
    Request JSON:
        { "query": "Loving v. Virginia", "style": "Chicago" }
    
    Response JSON:
        { "success": true, "citation": "...", "type": "legal", "metadata": {...} }
    """
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago')
        
        if not query:
            return jsonify({'success': False, 'error': 'No query provided'}), 400
        
        # Get single best result
        results = search_citations(query, style, max_results=1)
        
        if results:
            return jsonify({
                'success': True,
                'citation': results[0]['formatted'],
                'type': results[0]['type'],
                'metadata': results[0].get('metadata', {})
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No citation found',
                'query': query
            }), 404
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cite/candidates', methods=['POST'])
def api_cite_candidates():
    """
    API endpoint for multiple citation candidates.
    
    Request JSON:
        { "query": "Roe v Wade", "style": "Chicago", "max_results": 5 }
    
    Response JSON:
        { "success": true, "detected_type": "legal", "candidates": [...] }
    """
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago')
        max_results = data.get('max_results', 5)
        
        if not query:
            return jsonify({'success': False, 'error': 'No query provided'}), 400
        
        # Detect type
        detection = detect_type(query)
        
        # Get candidates
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
    """
    API endpoint for type detection only.
    
    Request JSON:
        { "query": "Roe v. Wade" }
    
    Response JSON:
        { "type": "legal", "confidence": 0.9 }
    """
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
    return jsonify({
        'styles': ['Chicago', 'Bluebook', 'OSCOLA', 'APA', 'MLA']
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '2.0',
        'timestamp': datetime.utcnow().isoformat()
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
