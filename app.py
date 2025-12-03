"""
CiteFlex Pro - Flask Application (Interactive UI Version)

Bridges the modular backend with the monolithic-style interactive UI.

Endpoints:
    GET  /          - Serve the interactive workbench UI
    POST /upload    - Upload .docx, extract endnotes, return list
    POST /search    - Search for candidates, return multiple results for selection
    POST /update    - Write selected citation back to document
    GET  /download  - Download the modified document with clickable links
    POST /reset     - Clear session data
"""

import os
import uuid
import shutil
import tempfile
import threading
from io import BytesIO
from flask import Flask, render_template, request, jsonify, send_file, session

from models import CitationMetadata, CitationType, CitationStyle
from router import search_all_sources, route_and_search
from formatters import format_citation, get_formatter
from document_processor import WordDocumentProcessor, LinkActivator


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'citeflex-modular-v2')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# In-memory storage for user sessions
USER_DATA_STORE = {}
FILE_LOCK = threading.Lock()


# =============================================================================
# SESSION HELPERS
# =============================================================================

def get_user_data():
    """Get current user's session data."""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return USER_DATA_STORE.get(session['user_id'])


def set_user_data(data):
    """Store data for current user session."""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    USER_DATA_STORE[session['user_id']] = data


def clear_user_data():
    """Clear current user's session data."""
    user_id = session.get('user_id')
    if user_id and user_id in USER_DATA_STORE:
        data = USER_DATA_STORE.pop(user_id)
        # Clean up temp directory
        if data and 'temp_dir' in data:
            shutil.rmtree(data['temp_dir'], ignore_errors=True)


# =============================================================================
# STYLE MAPPING
# =============================================================================

STYLE_MAP = {
    'chicago': CitationStyle.CHICAGO,
    'apa': CitationStyle.APA,
    'mla': CitationStyle.MLA,
    'bluebook': CitationStyle.BLUEBOOK,
    'oscola': CitationStyle.OSCOLA,
}

STYLE_NAMES = {
    'chicago': 'Chicago Manual of Style',
    'apa': 'APA 7',
    'mla': 'MLA 9',
    'bluebook': 'Bluebook',
    'oscola': 'OSCOLA',
}


# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    """Serve the interactive workbench UI."""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    """
    Upload a Word document and extract endnotes/footnotes.
    
    Returns:
        JSON: {success: bool, endnotes: [{id, text}, ...], error?: string}
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.docx'):
        return jsonify({'success': False, 'error': 'Only .docx files supported'}), 400
    
    try:
        # Clear any previous session data
        clear_user_data()
        
        # Create temp directory for this session
        temp_dir = tempfile.mkdtemp()
        
        # Save uploaded file
        file_bytes = file.read()
        original_filename = file.filename
        temp_path = os.path.join(temp_dir, original_filename)
        
        with open(temp_path, 'wb') as f:
            f.write(file_bytes)
        
        # Extract endnotes using WordDocumentProcessor
        processor = WordDocumentProcessor(BytesIO(file_bytes))
        endnotes = processor.get_endnotes()
        footnotes = processor.get_footnotes()
        
        # Combine endnotes and footnotes, marking which is which
        all_notes = []
        for note in endnotes:
            all_notes.append({
                'id': note['id'],
                'text': note['text'],
                'type': 'endnote'
            })
        for note in footnotes:
            all_notes.append({
                'id': f"fn_{note['id']}",  # Prefix to distinguish from endnotes
                'text': note['text'],
                'type': 'footnote'
            })
        
        # Store session data
        set_user_data({
            'temp_dir': temp_dir,
            'original_filename': original_filename,
            'file_bytes': file_bytes,
            'processor_temp_dir': processor.temp_dir,
            'notes': all_notes,
        })
        
        return jsonify({
            'success': True,
            'endnotes': all_notes,
            'count': len(all_notes)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/search', methods=['POST'])
def search():
    """
    Search for citation candidates across multiple engines.
    
    Request JSON:
        {text: string, style: string}
    
    Returns:
        JSON: {results: [{formatted, source, confidence, type}, ...]}
    """
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        style_key = data.get('style', 'chicago').lower()
        
        if not text:
            return jsonify({'results': []})
        
        # Get citation style
        citation_style = STYLE_MAP.get(style_key, CitationStyle.CHICAGO)
        formatter = get_formatter(citation_style)
        
        # Search for candidates using modular search
        candidates = search_all_sources(text, max_results=5)
        
        # If no candidates from search_all_sources, try route_and_search for single result
        if not candidates:
            single_result = route_and_search(text)
            if single_result and single_result.has_minimum_data():
                candidates = [single_result]
        
        # Format results for the frontend
        results = []
        for metadata in candidates:
            try:
                formatted = formatter.format(metadata)
                
                # Determine confidence level
                confidence = 'high' if metadata.doi or metadata.pmid else 'medium'
                if metadata.confidence < 0.5:
                    confidence = 'low'
                
                results.append({
                    'formatted': formatted,
                    'source': metadata.source_engine or 'Unknown',
                    'confidence': confidence,
                    'type': metadata.citation_type.name.lower()
                })
            except Exception as e:
                print(f"[Search] Error formatting result: {e}")
                continue
        
        # If still no results, return the original text as fallback
        if not results:
            results.append({
                'formatted': text,
                'source': 'No Match Found',
                'confidence': 'low',
                'type': 'unknown'
            })
        
        return jsonify({'results': results})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'results': []}), 500


@app.route('/update', methods=['POST'])
def update():
    """
    Write a selected citation back to the document.
    
    Request JSON:
        {id: string, html: string}
    
    Returns:
        JSON: {success: bool, error?: string}
    """
    user_data = get_user_data()
    if not user_data:
        return jsonify({'success': False, 'error': 'Session expired'}), 400
    
    try:
        data = request.get_json()
        note_id = data.get('id')
        new_content = data.get('html', '')
        
        if not note_id:
            return jsonify({'success': False, 'error': 'No note ID provided'}), 400
        
        with FILE_LOCK:
            # Reload processor from stored bytes
            processor = WordDocumentProcessor(BytesIO(user_data['file_bytes']))
            
            # Check if this is a footnote (prefixed with fn_)
            if note_id.startswith('fn_'):
                actual_id = note_id[3:]  # Remove 'fn_' prefix
                success = processor.write_footnote(actual_id, new_content)
            else:
                success = processor.write_endnote(note_id, new_content)
            
            if success:
                # Save updated document back to session
                buffer = processor.save_to_buffer()
                user_data['file_bytes'] = buffer.read()
                processor.cleanup()
                
                return jsonify({'success': True})
            else:
                processor.cleanup()
                return jsonify({'success': False, 'error': 'Failed to update note'}), 500
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download')
def download():
    """
    Download the modified document with clickable hyperlinks.
    
    Returns:
        The processed .docx file as an attachment
    """
    user_data = get_user_data()
    if not user_data:
        return "Session expired", 400
    
    try:
        # Get the modified document bytes
        file_bytes = user_data.get('file_bytes')
        if not file_bytes:
            return "No document found", 400
        
        # Apply LinkActivator to make URLs clickable
        doc_buffer = BytesIO(file_bytes)
        activated_buffer = LinkActivator.process(doc_buffer)
        
        # Generate output filename
        original_name = user_data.get('original_filename', 'document.docx')
        name_without_ext = os.path.splitext(original_name)[0]
        output_name = f"Resolved_{name_without_ext}.docx"
        
        return send_file(
            activated_buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=output_name
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}", 500


@app.route('/reset', methods=['POST'])
def reset():
    """Clear session and remove temporary files."""
    clear_user_data()
    session.clear()
    return jsonify({'success': True})


@app.route('/health')
def health():
    """Health check endpoint for Railway/deployment."""
    return jsonify({'status': 'healthy', 'version': '2.0-modular'})


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    print(f"CiteFlex Pro v2.0 (Modular + Interactive UI)")
    print(f"Running on http://localhost:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
