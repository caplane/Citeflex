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
from router import route_and_search, search_legal
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
    Main citation endpoint.
    
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
        
        return jsonify({
            'success': True,
            'count': 0,
            'citations': [],
            'message': 'Document processing coming soon'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
        formatter = get_formatter(style)
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
