"""
CiteFlex Pro - Flask Application
Serves the web UI and provides citation API endpoints.
"""

import os
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

# Import CiteFlex components
from models import CitationMetadata, CitationType, CitationStyle
from detectors import detect_type
from extractors import extract_interview, extract_newspaper, extract_government, extract_url
from router import route_and_search, search_legal, search_all_sources, get_citation_candidates
from formatters import get_formatter

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    """Serve the main UI."""
    return render_template('index.html')


@app.route('/api/cite', methods=['POST'])
def cite():
    """
    Main citation endpoint - returns single best result.
    
    Request JSON:
        {
            "query": "Loving v. Virginia",
            "style": "Chicago"
        }
    
    Response JSON:
        {
            "success": true,
            "citation": "<em>Loving v. Virginia</em>, 388 U.S. 1 (1967).",
            "type": "legal",
            "metadata": { ... }
        }
    """
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago')
        
        if not query:
            return jsonify({
                'success': False,
                'error': 'No query provided'
            }), 400
        
        # Get citation
        metadata, citation = get_citation(query, style)
        
        if metadata and citation:
            return jsonify({
                'success': True,
                'citation': citation,
                'type': metadata.citation_type.name.lower(),
                'metadata': metadata.to_dict() if hasattr(metadata, 'to_dict') else {}
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Could not generate citation',
                'query': query
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/cite/candidates', methods=['POST'])
def cite_candidates():
    """
    Get multiple citation candidates for user selection.
    
    This powers the "PROPOSED RESOLUTIONS" panel.
    TYPE-AWARE: Routes legal queries to legal engine, journal queries to academic engines, etc.
    
    Request JSON:
        {
            "query": "Roe v Wade",
            "style": "Chicago",
            "max_results": 5
        }
    
    Response JSON:
        {
            "success": true,
            "detected_type": "legal",
            "candidates": [
                {
                    "formatted": "<i>Roe v. Wade</i>, 410 U.S. 113 (1973).",
                    "source_engine": "Famous Cases Cache",
                    "type": "legal",
                    "metadata": { ... }
                },
                ...
            ]
        }
    """
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        style = data.get('style', 'Chicago')
        max_results = data.get('max_results', 5)
        
        if not query:
            return jsonify({
                'success': False,
                'error': 'No query provided'
            }), 400
        
        # Map style names
        style_map = {
            'Chicago': 'Chicago Manual of Style',
            'APA': 'APA 7',
            'MLA': 'MLA 9',
            'Bluebook': 'Bluebook',
            'OSCOLA': 'OSCOLA'
        }
        full_style = style_map.get(style, style)
        
        # Detect type first (for logging/debugging)
        detection = detect_type(query)
        detected_type = detection.citation_type.name.lower()
        
        # Get candidates (type-aware search)
        candidates = get_citation_candidates(query, full_style, max_results)
        
        return jsonify({
            'success': True,
            'detected_type': detected_type,
            'confidence': detection.confidence,
            'candidates': candidates
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/cite/document', methods=['POST'])
def cite_document():
    """
    Process a Word document and format all citations.
    """
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file provided'
            }), 400
        
        file = request.files['file']
        style = request.form.get('style', 'Chicago')
        
        if not file.filename.endswith('.docx'):
            return jsonify({
                'success': False,
                'error': 'Only .docx files are supported'
            }), 400
        
        # Map style names
        style_map = {
            'Chicago': 'Chicago Manual of Style',
            'APA': 'APA 7',
            'MLA': 'MLA 9',
            'Bluebook': 'Bluebook',
            'OSCOLA': 'OSCOLA'
        }
        full_style = style_map.get(style, style)
        
        # Process the document using the new processor
        from document_processor import process_document
        
        # Read file bytes
        file_bytes = file.read()
        
        # Process document (preview mode - don't need the doc back, just results)
        _, results = process_document(file_bytes, style=full_style, add_links=False)
        
        # Format results for response
        citations = []
        for r in results:
            citations.append({
                'original': r.original,
                'formatted': r.formatted,
                'type': r.metadata.citation_type.name.lower() if r.metadata else 'unknown',
                'success': r.success
            })
        
        success_count = sum(1 for r in results if r.success)
        
        return jsonify({
            'success': True,
            'count': success_count,
            'total': len(results),
            'citations': citations,
            'message': f'{success_count} of {len(results)} citations formatted'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/cite/document/download', methods=['POST'])
def download_document():
    """
    Process a Word document and return the formatted version for download.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        style = request.form.get('style', 'Chicago')
        
        if not file.filename.endswith('.docx'):
            return jsonify({'success': False, 'error': 'Only .docx files supported'}), 400
        
        style_map = {
            'Chicago': 'Chicago Manual of Style',
            'APA': 'APA 7',
            'MLA': 'MLA 9',
            'Bluebook': 'Bluebook',
            'OSCOLA': 'OSCOLA'
        }
        full_style = style_map.get(style, style)
        
        from document_processor import process_document
        from io import BytesIO
        
        file_bytes = file.read()
        
        # Process document (with clickable links)
        doc_bytes, _ = process_document(file_bytes, style=full_style, add_links=True)
        
        # Return the modified document
        output = BytesIO(doc_bytes)
        
        from flask import send_file
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=f'formatted_{file.filename}'
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/detect', methods=['POST'])
def detect():
    """
    Detect citation type without searching.
    Useful for UI to show what type was detected.
    
    Request JSON:
        {"query": "Roe v. Wade"}
    
    Response JSON:
        {
            "type": "legal",
            "confidence": 0.9
        }
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
        return jsonify({
            'type': 'unknown',
            'confidence': 0,
            'error': str(e)
        })


@app.route('/api/styles', methods=['GET'])
def get_styles():
    """Return available citation styles."""
    return jsonify({
        'styles': ['Chicago', 'APA', 'MLA', 'Bluebook', 'OSCOLA']
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


# =============================================================================
# CITATION LOGIC
# =============================================================================

def get_citation(query: str, style: str = "Chicago") -> tuple:
    """
    Main entry point: detect type, fetch metadata, format citation.
    """
    if not query or not query.strip():
        return None, ""
    
    query = query.strip()
    
    # Map short style names to full names
    style_map = {
        'Chicago': 'Chicago Manual of Style',
        'APA': 'APA 7',
        'MLA': 'MLA 9',
        'Bluebook': 'Bluebook',
        'OSCOLA': 'OSCOLA'
    }
    full_style = style_map.get(style, style)
    
    # Step 1: Detect citation type
    detection = detect_type(query)
    citation_type = detection.citation_type
    
    # Step 2: Get metadata based on type
    metadata = None
    
    if citation_type == CitationType.INTERVIEW:
        metadata = extract_interview(query)
    
    elif citation_type == CitationType.NEWSPAPER:
        metadata = extract_newspaper(query)
    
    elif citation_type == CitationType.GOVERNMENT:
        metadata = extract_government(query)
    
    elif citation_type == CitationType.URL:
        metadata = extract_url(query)
    
    elif citation_type == CitationType.LEGAL:
        metadata = search_legal(query)
        if not metadata:
            metadata = CitationMetadata(
                citation_type=CitationType.LEGAL,
                case_name=query,
                raw_source=query
            )
    
    else:
        # JOURNAL, BOOK, MEDICAL - try API search
        metadata = route_and_search(query)
        if not metadata:
            metadata = CitationMetadata(
                citation_type=citation_type,
                title=query,
                raw_source=query
            )
    
    # Step 3: Format the citation
    if metadata:
        formatter = get_formatter(full_style)
        citation = formatter.format(metadata)
        return metadata, citation
    
    return None, ""


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
