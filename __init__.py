"""
citeflex - Modular Citation Management System

A clean, modular alternative to the monolithic citation_manager.py.

Usage:
    from citeflex import get_citation, search_journal, format_citation
    
    # Full pipeline (detect → search → format)
    metadata, citation = get_citation("Caplan trains brains sprains")
    
    # Just search
    metadata = search_journal("Caplan trains brains sprains")
    
    # Just format
    from citeflex.models import CitationStyle
    citation = format_citation(metadata, CitationStyle.CHICAGO)

Architecture:
    ┌─────────────────────────────────────────┐
    │ LAYER 1: Detectors (detectors.py)       │
    │ Pattern matching to identify type       │
    └─────────────────┬───────────────────────┘
                      │
            ┌─────────┴─────────┐
            │                   │
       LOCAL TYPES          SEARCH TYPES
            │                   │
            ▼                   ▼
    ┌───────────────┐   ┌─────────────────────┐
    │ Extractors    │   │ Engines             │
    │ (extractors)  │   │ (engines/)          │
    └───────┬───────┘   └──────────┬──────────┘
            │                      │
            └──────────┬───────────┘
                       ▼
            ┌─────────────────────┐
            │ CitationMetadata    │
            │ (models.py)         │
            └──────────┬──────────┘
                       ▼
            ┌─────────────────────┐
            │ Formatters          │
            │ (formatters/)       │
            └─────────────────────┘

Modules:
    - models.py: Data structures (CitationMetadata, CitationType, CitationStyle)
    - config.py: Constants, API keys, domain mappings
    - detectors.py: Pattern detection for type classification
    - extractors.py: Local metadata extraction (interview, newspaper, gov)
    - gemini_router.py: AI-powered classification for ambiguous queries
    - document_processor.py: Word document processing, LinkActivator
    - engines/: Search engine implementations
        - base.py: Abstract base class
        - academic.py: Crossref, OpenAlex, SemanticScholar, PubMed
        - legal.py: FamousCasesCache, CourtListener, UK parser
        - google_cse.py: Google CSE, Google Books, Open Library
    - formatters/: Citation style implementations
        - base.py: Abstract base and registry
        - chicago.py: Chicago Manual of Style
        - apa.py: APA 7th Edition
        - mla.py: MLA 9th Edition
        - bluebook.py: Bluebook (legal)
        - oscola.py: OSCOLA (UK legal)
    - router.py: Main orchestration logic
"""

__version__ = "2.1.0"
__author__ = "Eric Caplan"

# =============================================================================
# PUBLIC API
# =============================================================================

# Models
from models import (
    CitationMetadata,
    CitationType,
    CitationStyle,
    DetectionResult,
)

# Detection
from detectors import (
    detect_type,
    detect_citation_type,  # Backward compat
    is_url,
    is_interview,
    is_legal,
    is_newspaper,
    is_government,
    is_medical,
    is_journal,
    is_book,
)

# Extraction
from extractors import (
    extract_interview,
    extract_newspaper,
    extract_government,
    extract_url,
    extract_by_type,
)

# Formatting
from formatters import (
    format_citation,
    get_formatter,
    BaseFormatter,
    ChicagoFormatter,
    APAFormatter,
    MLAFormatter,
    BluebookFormatter,
    OSCOLAFormatter,
)

# Main Router API
from router import (
    get_citation,
    route_and_search,
    search_journal,
    search_medical,
    search_legal,
    search_book,
    search_all_sources,
    process_bulk,
)

# Engines (for advanced use)
from engines import (
    SearchEngine,
    CrossrefEngine,
    OpenAlexEngine,
    SemanticScholarEngine,
    PubMedEngine,
    LegalSearchEngine,
    FamousCasesCache,
    CourtListenerEngine,
    GoogleCSEEngine,
    GoogleBooksEngine,
    OpenLibraryEngine,
)

# Gemini AI Router (optional)
try:
    from gemini_router import (
        GeminiRouter,
        gemini_classify,
        gemini_enhance,
        get_gemini_router,
    )
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Document Processing (optional - requires python-docx)
try:
    from document_processor import (
        LinkActivator,
        BulkProcessor,
        EndnoteEditor,
        ProcessedCitation,
        process_document,
        process_citations,
    )
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

__all__ = [
    # Version
    '__version__',
    
    # Models
    'CitationMetadata',
    'CitationType', 
    'CitationStyle',
    'DetectionResult',
    
    # Detection
    'detect_type',
    'detect_citation_type',
    'is_url',
    'is_interview',
    'is_legal',
    'is_newspaper',
    'is_government',
    'is_medical',
    'is_journal',
    'is_book',
    
    # Extraction
    'extract_interview',
    'extract_newspaper',
    'extract_government',
    'extract_url',
    'extract_by_type',
    
    # Formatting
    'format_citation',
    'get_formatter',
    'BaseFormatter',
    'ChicagoFormatter',
    'APAFormatter',
    'MLAFormatter',
    'BluebookFormatter',
    'OSCOLAFormatter',
    
    # Main API
    'get_citation',
    'route_and_search',
    'search_journal',
    'search_medical',
    'search_legal',
    'search_book',
    'search_all_sources',
    'process_bulk',
    
    # Engines
    'SearchEngine',
    'CrossrefEngine',
    'OpenAlexEngine',
    'SemanticScholarEngine',
    'PubMedEngine',
    'LegalSearchEngine',
    'FamousCasesCache',
    'CourtListenerEngine',
    'GoogleCSEEngine',
    'GoogleBooksEngine',
    'OpenLibraryEngine',
    
    # Gemini (optional)
    'GeminiRouter',
    'gemini_classify',
    'gemini_enhance',
    'get_gemini_router',
    'GEMINI_AVAILABLE',
    
    # Document Processing (optional)
    'LinkActivator',
    'BulkProcessor',
    'EndnoteEditor',
    'ProcessedCitation',
    'process_document',
    'process_citations',
    'DOCX_AVAILABLE',
]
