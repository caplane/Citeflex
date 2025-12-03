"""
citeflex/router.py

Main routing logic that orchestrates:
1. Detection (what type of citation is this?)
2. Search/Extraction (get metadata from appropriate source)
3. Formatting (produce citation string in requested style)

This is the primary public API for the modular citation system.
"""

import re
from typing import Optional, List, Tuple

from models import CitationMetadata, CitationType, CitationStyle, DetectionResult
from detectors import detect_type
from extractors import extract_by_type
from engines import (
    CrossrefEngine,
    OpenAlexEngine,
    SemanticScholarEngine,
    PubMedEngine,
    LegalSearchEngine,
    GoogleCSEEngine,
    GoogleBooksEngine,
    OpenLibraryEngine,
)
from engines.doi import extract_doi_from_url, fetch_crossref_by_doi
from formatters import format_citation, get_formatter


# =============================================================================
# ENGINE INSTANCES (lazy-loaded singletons)
# =============================================================================

_engines = {}


def _get_engine(name: str):
    """Get or create engine instance."""
    if name not in _engines:
        engine_map = {
            'crossref': CrossrefEngine,
            'openalex': OpenAlexEngine,
            'semantic_scholar': SemanticScholarEngine,
            'pubmed': PubMedEngine,
            'legal': LegalSearchEngine,
            'google_cse': GoogleCSEEngine,
            'google_books': GoogleBooksEngine,
            'open_library': OpenLibraryEngine,
        }
        if name in engine_map:
            _engines[name] = engine_map[name]()
    return _engines.get(name)


# =============================================================================
# SEARCH FUNCTIONS
# =============================================================================

def search_journal(query: str) -> Optional[CitationMetadata]:
    """
    Search for a journal article across multiple engines.
    
    Search order (optimized for finding obscure/older articles):
    1. Google CSE FIRST (searches JSTOR, Google Scholar - best coverage for obscure sources)
    2. Crossref (DOI registry)
    3. OpenAlex (broad coverage)
    4. Semantic Scholar (author-aware)
    
    Returns first successful result.
    """
    # Engine 1: Google CSE FIRST (best for JSTOR, older articles, obscure sources)
    # This is critical for messy notes like "Caplan trains brains sprains"
    google_cse = _get_engine('google_cse')
    if google_cse:
        result = google_cse.search(query)
        if result and result.has_minimum_data():
            print(f"[search_journal] Found via Google CSE: {result.title}")
            return result
    
    # Engines 2-4: Other academic engines
    for engine_name in ['crossref', 'openalex', 'semantic_scholar']:
        engine = _get_engine(engine_name)
        if engine:
            result = engine.search(query)
            if result and result.has_minimum_data():
                print(f"[search_journal] Found via {engine_name}: {result.title}")
                return result
    
    return None


def search_book(query: str) -> Optional[CitationMetadata]:
    """
    Search for a book.
    
    Search order:
    1. Open Library (free, good for ISBN)
    2. Google Books (broad coverage)
    3. OpenAlex (academic books)
    
    Returns first successful result.
    """
    # Check for ISBN in query
    isbn_match = re.search(r'\b(?:97[89][-\s]?)?(\d[-\s]?){9}[\dX]\b', query, re.IGNORECASE)
    
    if isbn_match:
        # Direct ISBN lookup
        isbn = isbn_match.group(0)
        
        # Try Open Library first (free)
        open_library = _get_engine('open_library')
        if open_library:
            result = open_library.get_by_id(isbn)
            if result and result.has_minimum_data():
                return result
        
        # Try Google Books
        google_books = _get_engine('google_books')
        if google_books:
            result = google_books.get_by_id(isbn)
            if result and result.has_minimum_data():
                return result
    
    # Text search
    for engine_name in ['google_books', 'open_library']:
        engine = _get_engine(engine_name)
        if engine:
            result = engine.search(query)
            if result and result.has_minimum_data():
                return result
    
    # Try OpenAlex as fallback (sometimes has books)
    openalex = _get_engine('openalex')
    if openalex:
        result = openalex.search(query)
        if result and result.has_minimum_data():
            result.citation_type = CitationType.BOOK
            return result
    
    return None


def search_medical(query: str) -> Optional[CitationMetadata]:
    """
    Search for a medical/clinical article.
    
    Search order:
    1. PubMed (primary for biomedical)
    2. Crossref (fallback)
    """
    # Try PubMed first
    pubmed = _get_engine('pubmed')
    if pubmed:
        result = pubmed.search(query)
        if result and result.has_minimum_data():
            return result
    
    # Fallback to Crossref
    crossref = _get_engine('crossref')
    if crossref:
        result = crossref.search(query)
        if result and result.has_minimum_data():
            result.citation_type = CitationType.MEDICAL
            return result
    
    return None


def search_legal(query: str) -> Optional[CitationMetadata]:
    """
    Search for a legal case.
    
    Uses composite LegalSearchEngine which tries:
    1. UK Citation Parser
    2. Famous Cases Cache
    3. CourtListener API
    """
    engine = _get_engine('legal')
    if engine:
        return engine.search(query)
    return None


# =============================================================================
# SEARCH_ALL_SOURCES - TYPE-AWARE VERSION
# =============================================================================

def search_all_sources(query: str, citation_type: CitationType = None, max_results: int = 5) -> List[CitationMetadata]:
    """
    Search multiple engines and return all results for user selection.
    
    TYPE-AWARE: Routes to appropriate engines based on detected type.
    This prevents:
    - "Roe v Wade" returning journal articles ABOUT the case instead of the case itself
    - "Novak weak state" returning unrelated books
    
    Args:
        query: Search query
        citation_type: Detected type (if None, will auto-detect)
        max_results: Maximum total results to return
        
    Returns:
        List of CitationMetadata from appropriate sources
    """
    results = []
    seen_titles = set()
    
    # Auto-detect type if not provided
    if citation_type is None:
        detection = detect_type(query)
        citation_type = detection.citation_type
        print(f"[search_all_sources] Auto-detected type: {citation_type.name}")
    
    def add_result(result: CitationMetadata) -> bool:
        """Add a single result, deduplicating. Returns True if max reached."""
        if result and result.has_minimum_data():
            # Use case_name for legal, title for others
            if result.citation_type == CitationType.LEGAL and result.case_name:
                key = result.case_name.lower().strip()[:50]
            else:
                key = result.title.lower().strip()[:50] if result.title else ''
            
            if key and key not in seen_titles:
                seen_titles.add(key)
                results.append(result)
                return len(results) >= max_results
        return False
    
    def add_results_from_engine(engine_name: str, limit: int = 2) -> bool:
        """Add results from an engine. Returns True if max reached."""
        engine = _get_engine(engine_name)
        if engine:
            if hasattr(engine, 'search_multiple'):
                engine_results = engine.search_multiple(query, limit=limit)
                for r in engine_results:
                    if add_result(r):
                        return True
            else:
                # Fallback to single search
                result = engine.search(query)
                if add_result(result):
                    return True
        return False
    
    # ==========================================================================
    # TYPE-AWARE ROUTING
    # ==========================================================================
    
    if citation_type == CitationType.LEGAL:
        # LEGAL: Only search legal engine
        # Prevents "Roe v Wade" from returning articles ABOUT the case
        print(f"[search_all_sources] Routing to LEGAL engine only")
        add_results_from_engine('legal', limit=max_results)
    
    elif citation_type == CitationType.BOOK:
        # BOOK: Search book engines only
        print(f"[search_all_sources] Routing to BOOK engines")
        for engine_name in ['google_books', 'open_library']:
            if add_results_from_engine(engine_name, limit=3):
                break
        if len(results) < max_results:
            add_results_from_engine('openalex', limit=2)
    
    elif citation_type == CitationType.MEDICAL:
        # MEDICAL: PubMed first, then academic
        print(f"[search_all_sources] Routing to MEDICAL engines")
        add_results_from_engine('pubmed', limit=3)
        if len(results) < max_results:
            add_results_from_engine('crossref', limit=2)
    
    elif citation_type in [CitationType.INTERVIEW, CitationType.NEWSPAPER, 
                           CitationType.GOVERNMENT, CitationType.URL]:
        # LOCAL EXTRACTORS: These don't need multiple results
        print(f"[search_all_sources] Using local extractor for {citation_type.name}")
        extracted = extract_by_type(query, citation_type)
        if extracted:
            results.append(extracted)
    
    else:
        # JOURNAL, UNKNOWN: Academic engines + Google CSE (NO Google Books)
        print(f"[search_all_sources] Routing to JOURNAL/ACADEMIC engines")
        
        # Google CSE FIRST (best for JSTOR, obscure articles)
        add_results_from_engine('google_cse', limit=2)
        
        # Then other academic engines
        for engine_name in ['crossref', 'openalex', 'semantic_scholar']:
            if len(results) >= max_results:
                break
            add_results_from_engine(engine_name, limit=2)
        
        # NO Google Books for journal queries - prevents noise like "Novak weak state" returning unrelated books
    
    return results[:max_results]


# =============================================================================
# MAIN ROUTING FUNCTIONS
# =============================================================================

# Threshold for using Gemini fallback
GEMINI_CONFIDENCE_THRESHOLD = 0.5


def route_and_search(query: str, use_gemini: bool = True) -> Optional[CitationMetadata]:
    """
    Main routing function.
    
    1. Detect citation type using pattern matching (Layer 1)
    2. If confidence is low and Gemini is available, use AI classification (Layer 2)
    3. Route to appropriate extractor or search engine (Layer 3)
    4. Return metadata
    
    Args:
        query: Raw user input
        use_gemini: Whether to use Gemini for low-confidence queries
        
    Returns:
        CitationMetadata if found, None otherwise
    """
    if not query or not query.strip():
        return None
    
    clean_query = query.strip()
    
    # ==========================================================================
    # Route 0: DOI in URL - highest priority for academic publisher URLs
    # ==========================================================================
    if 'http' in clean_query.lower():
        doi = extract_doi_from_url(clean_query)
        if doi:
            print(f"[Router] Detected DOI in URL: {doi}")
            metadata = fetch_crossref_by_doi(doi, clean_query)
            if metadata and metadata.has_minimum_data():
                # Keep original URL in the metadata
                metadata.url = clean_query
                return metadata
    
    # Step 1: Detect type using pattern matching
    detection = detect_type(clean_query)
    
    # Step 2: If low confidence, try Gemini fallback
    if use_gemini and detection.confidence < GEMINI_CONFIDENCE_THRESHOLD:
        try:
            from gemini_router import gemini_classify
            gemini_result = gemini_classify(clean_query, detection.hints)
            if gemini_result and gemini_result.confidence > detection.confidence:
                detection = gemini_result
                print(f"[Router] Gemini override: {detection.citation_type.name} ({detection.confidence:.2f})")
        except ImportError:
            pass  # Gemini not available
        except Exception as e:
            print(f"[Router] Gemini fallback error: {e}")
    
    # Step 3: Route based on type
    
    # Types that use local extractors (no API calls)
    if detection.citation_type in [CitationType.INTERVIEW, CitationType.NEWSPAPER, 
                                    CitationType.GOVERNMENT, CitationType.URL]:
        return extract_by_type(clean_query, detection.citation_type)
    
    # Types that use search engines
    if detection.citation_type == CitationType.LEGAL:
        return search_legal(clean_query)
    
    if detection.citation_type == CitationType.MEDICAL:
        return search_medical(clean_query)
    
    if detection.citation_type == CitationType.JOURNAL:
        return search_journal(clean_query)
    
    if detection.citation_type == CitationType.BOOK:
        # Try book-specific search first
        result = search_book(clean_query)
        if result and result.has_minimum_data():
            return result
        # Fall back to journal search (sometimes books are in journal databases)
        result = search_journal(clean_query)
        if result:
            return result
    
    # Unknown type - try journal search as default (with Google CSE fallback)
    return search_journal(clean_query)


def get_citation(
    query: str,
    style: str = "Chicago Manual of Style"
) -> Tuple[Optional[CitationMetadata], str]:
    """
    Full pipeline: detect, search, and format.
    
    This is the main public API that mirrors the old citation_manager.get_citation().
    
    Args:
        query: Raw user input
        style: Citation style name (e.g., "Chicago Manual of Style", "APA 7")
        
    Returns:
        Tuple of (metadata, formatted_citation_string)
    """
    # Search
    metadata = route_and_search(query)
    
    if metadata is None:
        return None, "No citation found for the given query."
    
    # Parse style
    citation_style = CitationStyle.from_string(style)
    
    # Format
    formatted = format_citation(metadata, citation_style)
    
    return metadata, formatted


def get_citation_candidates(
    query: str,
    style: str = "Chicago Manual of Style",
    max_results: int = 5
) -> List[dict]:
    """
    Get multiple citation candidates for user selection.
    
    This powers the "PROPOSED RESOLUTIONS" panel in the UI.
    Returns formatted citations from appropriate engines based on detected type.
    
    Args:
        query: Raw user input
        style: Citation style for formatting
        max_results: Maximum candidates to return
        
    Returns:
        List of dicts with 'formatted', 'source_engine', 'metadata', 'type'
    """
    # Detect type first
    detection = detect_type(query)
    
    # Search appropriate engines based on type
    candidates = search_all_sources(query, detection.citation_type, max_results)
    
    # Format each candidate
    citation_style = CitationStyle.from_string(style)
    formatter = get_formatter(citation_style)
    
    results = []
    for metadata in candidates:
        formatted = formatter.format(metadata)
        results.append({
            'formatted': formatted,
            'source_engine': metadata.source_engine,
            'type': metadata.citation_type.name.lower(),
            'metadata': metadata.to_dict() if hasattr(metadata, 'to_dict') else {},
        })
    
    return results


def process_bulk(
    queries: List[str],
    style: str = "Chicago Manual of Style"
) -> List[dict]:
    """
    Process multiple citations in bulk.
    
    Args:
        queries: List of raw citation strings
        style: Citation style to use
        
    Returns:
        List of result dictionaries with 'original', 'fixed', 'source' keys
    """
    results = []
    
    for query in queries:
        if not query or not query.strip():
            continue
        
        clean = query.strip()
        
        try:
            metadata, formatted = get_citation(clean, style)
            
            if metadata:
                results.append({
                    'original': clean,
                    'fixed': formatted,
                    'source': metadata.source_engine,
                    'metadata': metadata
                })
            else:
                results.append({
                    'original': clean,
                    'fixed': None,
                    'source': None,
                    'metadata': None
                })
        except Exception as e:
            results.append({
                'original': clean,
                'fixed': f"Error: {str(e)}",
                'source': None,
                'metadata': None
            })
    
    return results


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

def detect_citation_type(text: str) -> str:
    """
    Backward-compatible type detection.
    Returns string type name.
    """
    result = detect_type(text)
    return result.citation_type.name
