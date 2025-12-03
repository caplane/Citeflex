"""
CiteFlex Pro - Flask Application (Thin Wrapper)

This version properly imports from existing modules:
- document_processor.py: WordDocumentProcessor, LinkActivator, CitationHistory
- router.py: search_all_sources, get_citation
- detectors.py: detect_type
- formatters/: get_formatter
"""

import os
import io
import uuid
import tempfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename

# =============================================================================
# IMPORTS FROM EXISTING MODULES
# =============================================================================

from models import CitationMetadata, CitationType, CitationStyle
from detectors import detect_type
from router import search_all_sources, get_citation
from formatters import get_formatter
from document_processor import (
    WordDocumentProcessor,
    LinkActivator,
    CitationHistory,
    is_ibid,
    extract_ibid_page,
)

# =============================================================================
# FLASK APP SETUP
# =============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'citeflex-dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max


# =============================================================================
# SESSION STORAGE
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
            'citation_history': CitationHistory(),  # For ibid/short form tracking
        }
    return _sessions[session_id]


def clear_session_data():
    """Clear current session data."""
    session_id = session.get('session_id')
    if session_id and session_id in _sessions:
        if _sessions[session_id].get('doc_processor'):
            try:
                _sessions[session_id]['doc_processor'].cleanup()
            except:
                pass
        del _sessions[session_id]
    session.pop('session_id', None)


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
        
        # Create document processor (from document_processor.py)
        doc_processor = WordDocumentProcessor(io.BytesIO(file_bytes))
        
        # Extract notes
        endnotes = doc_processor.get_endnotes()
        footnotes = doc_processor.get_footnotes()
        
        # Add type indicator to footnotes
        for fn in footnotes:
            fn['type'] = 'footnote'
        for en in endnotes:
            en['type'] = 'endnote'
        
        # Store in session
        session_data = get_session_data()
        
        # Cleanup old processor
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
        session_data['citation_history'] = CitationHistory()  # Fresh history
        
        # Combine for frontend
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
    Uses router.search_all_sources() for TYPE-AWARE searching.
    Checks citation history for ibid/short form suggestions.
    """
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        style = data.get('style', 'chicago')
        
        if not text:
            return jsonify({'results': []})
        
        # Map style names
        style_map = {
            'chicago': 'Chicago Manual of Style',
            'bluebook': 'Bluebook',
            'oscola': 'OSCOLA',
            'apa': 'APA 7',
            'mla': 'MLA 9',
        }
        full_style = style_map.get(style.lower(), 'Chicago Manual of Style')
        
        # Handle explicit "ibid." references
        if is_ibid(text):
            page = extract_ibid_page(text)
            from formatters.base import BaseFormatter
            formatted = BaseFormatter.format_ibid(page)
            return jsonify({
                'results': [{
                    'formatted': formatted,
                    'source': 'Short Form',
                    'type': 'reference',
                    'confidence': 'high'
                }]
            })
        
        # Detect type for routing
        detection = detect_type(text)
        citation_type = detection.citation_type
        
        print(f"[Search] Query: '{text[:50]}...' → Type: {citation_type.name} ({detection.confidence:.2f})")
        
        # Search using router's TYPE-AWARE search
        candidates = search_all_sources(text, citation_type, max_results=5)
        
        # Get formatter and session data
        formatter = get_formatter(full_style)
        session_data = get_session_data()
        history = session_data.get('citation_history', CitationHistory())
        
        results = []
        for meta in candidates:
            # Check for ibid/short form suggestions
            suggestion = None
            if history.is_same_as_previous(meta):
                suggestion = 'ibid'
            elif history.has_been_cited_before(meta):
                suggestion = 'short_form'
            
            # Format the citation
            try:
                formatted = formatter.format(meta)
            except Exception as e:
                print(f"[Search] Format error: {e}")
                formatted = meta.title or meta.case_name or meta.raw_source
            
            result = {
                'formatted': formatted,
                'source': meta.source_engine or 'Unknown',
                'type': meta.citation_type.name.lower(),
                'confidence': 'high' if detection.confidence > 0.7 else 'medium',
                'metadata': meta.to_dict() if hasattr(meta, 'to_dict') else {},
            }
            
            # Add suggestion if applicable
            if suggestion:
                result['suggestion'] = suggestion
                if suggestion == 'ibid':
                    result['suggested_text'] = 'ibid.'
                elif suggestion == 'short_form':
                    result['suggested_text'] = formatter.format_short(meta)
            
            results.append(result)
        
        return jsonify({'results': results})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'results': [], 'error': str(e)}), 500


@app.route('/update', methods=['POST'])
def update():
    """
    Update a specific note with new text.
    Records full citations to history for ibid/short form tracking.
    """
    try:
        data = request.get_json()
        note_id = data.get('id')
        new_html = data.get('html', '')
        metadata_dict = data.get('metadata')  # Optional metadata for history
        
        if not note_id:
            return jsonify({'success': False, 'error': 'No note ID provided'}), 400
        
        session_data = get_session_data()
        session_data['updates'][note_id] = new_html
        
        # Record to citation history (for ibid/short form detection)
        # Only record full citations, not ibid or short forms
        if metadata_dict and not is_ibid(new_html):
            history = session_data.get('citation_history')
            if history:
                meta = CitationMetadata.from_dict(metadata_dict)
                history.add(meta, new_html)
        
        print(f"[Update] Note {note_id} → {new_html[:50]}...")
        
        return jsonify({'success': True})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/history', methods=['GET'])
def view_history():
    """Debug endpoint: View citation history."""
    session_data = get_session_data()
    history = session_data.get('citation_history')
    
    if not history:
        return jsonify({'entries': [], 'count': 0})
    
    entries = []
    for key, entry in history.all_sources.items():
        entries.append({
            'key': key,
            'formatted': entry.formatted,
            'note_number': entry.note_number,
        })
    
    return jsonify({
        'entries': entries,
        'count': len(entries),
        'previous': history.previous.formatted if history.previous else None,
    })


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
            if str(note_id).startswith('fn_'):
                doc_processor.write_footnote(note_id, new_html)
            else:
                doc_processor.write_endnote(note_id, new_html)
        
        # Save to buffer
        output_buffer = doc_processor.save_to_buffer()
        
        # Activate hyperlinks using LinkActivator from document_processor.py
        output_buffer = LinkActivator.process(output_buffer)
        
        # Generate filename
        original_name = session_data.get('filename', 'document.docx')
        base_name = os.path.splitext(original_name)[0]
        download_name = f'{base_name}_formatted.docx'
        
        return send_file(
            output_buffer,
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
    """API endpoint for single citation lookup using router.get_citation()."""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago Manual of Style')
        
        if not query:
            return jsonify({'success': False, 'error': 'No query provided'}), 400
        
        # Use router's get_citation for full pipeline
        metadata, formatted = get_citation(query, style)
        
        if metadata and formatted:
            return jsonify({
                'success': True,
                'citation': formatted,
                'type': metadata.citation_type.name.lower(),
                'metadata': metadata.to_dict()
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
        style = data.get('style', 'Chicago Manual of Style')
        max_results = data.get('max_results', 5)
        
        if not query:
            return jsonify({'success': False, 'error': 'No query provided'}), 400
        
        # Detect type
        detection = detect_type(query)
        
        # Search using router
        candidates = search_all_sources(query, detection.citation_type, max_results)
        
        # Format results
        formatter = get_formatter(style)
        results = []
        for meta in candidates:
            results.append({
                'formatted': formatter.format(meta),
                'source': meta.source_engine,
                'type': meta.citation_type.name.lower(),
                'metadata': meta.to_dict(),
            })
        
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
        'version': '3.0',  # Thin wrapper version
        'architecture': 'modular',
        'timestamp': datetime.utcnow().isoformat()
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
