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
    
    Search order:
    1. Semantic Scholar (author-aware)
    2. Crossref (DOI registry)
    3. OpenAlex (broad coverage)
    4. Google CSE (nuclear fallback - searches JSTOR, Scholar, etc.)
    
    Returns first successful result.
    """
    # Try specialized engines first
    for engine_name in ['semantic_scholar', 'crossref', 'openalex']:
        engine = _get_engine(engine_name)
        if engine:
            result = engine.search(query)
            if result and result.has_minimum_data():
                return result
    
    # Fallback to Google CSE (searches JSTOR, Google Scholar, etc.)
    google_cse = _get_engine('google_cse')
    if google_cse:
        result = google_cse.search(query)
        if result and result.has_minimum_data():
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


def search_all_sources(query: str, max_results: int = 5) -> List[CitationMetadata]:
    """
    Search multiple engines and return all results for user selection.
    
    Useful for ambiguous queries where the user should choose.
    
    Args:
        query: Search query
        max_results: Maximum total results to return
        
    Returns:
        List of CitationMetadata from different sources
    """
    results = []
    seen_titles = set()
    
    def add_results(engine_name: str, limit: int = 2):
        """Helper to add results from an engine."""
        nonlocal results
        engine = _get_engine(engine_name)
        if engine:
            engine_results = engine.search_multiple(query, limit=limit)
            for r in engine_results:
                # Deduplicate by title
                title_key = r.title.lower().strip()[:50] if r.title else ''
                if title_key and title_key not in seen_titles:
                    seen_titles.add(title_key)
                    results.append(r)
                    if len(results) >= max_results:
                        return True
        return False
    
    # Search academic engines first
    for engine_name in ['crossref', 'openalex', 'semantic_scholar']:
        if add_results(engine_name, limit=2):
            break
    
    # If we need more results, try Google CSE
    if len(results) < max_results:
        add_results('google_cse', limit=max_results - len(results))
    
    # Also try book engines if we still need more
    if len(results) < max_results:
        add_results('google_books', limit=2)
    
    return results[:max_results]


# =============================================================================
# QUERY ENHANCEMENT (Clean messy notes before searching)
# =============================================================================

# Patterns that indicate a "messy note" rather than a clean citation
MESSY_NOTE_PATTERNS = [
    r'\bwrote\s+(a|an|the)\s+',          # "wrote a book", "wrote an article"
    r'\b(he|she|they)\s+wrote\b',         # "he wrote", "she wrote"
    r'\b(this|that)\s+is\s+(a|an)\s+',    # "this is a book"
    r'\b(book|article)\s+(called|titled|named)\b',  # "book called X"
    r'\b(by|from)\s+\w+\s+(about|on)\b',  # "by Smith about trains"
    r'^[A-Z][a-z]+\s+wrote\b',            # "Smith wrote..."
    r'\babout\s+(the|a|an)\s+',           # "about the history of"
]

# Words to strip from search queries
NOISE_WORDS = {
    'wrote', 'writes', 'written', 'author', 'authored',
    'book', 'article', 'paper', 'called', 'titled', 'named',
    'about', 'the', 'a', 'an', 'this', 'that', 'is', 'was', 'were',
    'he', 'she', 'they', 'their', 'his', 'her', 'its',
    'by', 'from', 'in', 'on', 'of', 'for', 'with', 'to',
}


def is_messy_note(query: str) -> bool:
    """
    Detect if a query looks like a messy note rather than a clean citation.
    
    Messy notes are informal references like:
    - "Eric wrote an article called trains"
    - "Woo wrote a book called master slave"
    - "Smith's book about the Civil War"
    
    Clean citations have structured elements like:
    - DOI, ISBN, volume/issue numbers
    - Publisher names
    - Formal citation patterns
    
    Returns:
        True if query appears to be a messy note needing enhancement
    """
    if not query:
        return False
    
    lower = query.lower()
    
    # If it has structured citation elements, it's not messy
    if re.search(r'10\.\d{4,}/', lower):  # DOI
        return False
    if re.search(r'\b\d+\s*\(\d+\)', lower):  # Volume(Issue)
        return False
    if re.search(r'\bpp?\.?\s*\d+', lower):  # Page numbers
        return False
    if re.search(r'\b(?:97[89][-\s]?)?(\d[-\s]?){9}[\dX]\b', query, re.IGNORECASE):  # ISBN
        return False
    if query.startswith(('http://', 'https://')):  # URL
        return False
    
    # Check for messy note patterns
    for pattern in MESSY_NOTE_PATTERNS:
        if re.search(pattern, lower):
            return True
    
    return False


def extract_search_terms_regex(query: str, citation_type: 'CitationType') -> str:
    """
    Extract key search terms from a messy note using regex.
    
    This is a fallback when Gemini is unavailable.
    
    Examples:
    - "Eric wrote an article called trains" → "Eric trains"
    - "Woo wrote a book called master slave" → "Woo master slave"
    - "Andy wrote a book called desperate remedies" → "Andy desperate remedies"
    
    Args:
        query: The messy note
        citation_type: Detected citation type (for type-specific extraction)
        
    Returns:
        Cleaned search query
    """
    # Extract potential author name (capitalized word at start)
    author_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', query)
    author = author_match.group(1) if author_match else ""
    
    # Extract title fragment after "called", "titled", "named", or "about"
    title_patterns = [
        r'\bcalled\s+["\']?(.+?)["\']?\s*(?:\.|,|$)',
        r'\btitled\s+["\']?(.+?)["\']?\s*(?:\.|,|$)',
        r'\bnamed\s+["\']?(.+?)["\']?\s*(?:\.|,|$)',
        r'\babout\s+(.+?)\s*(?:\.|,|$)',
        r'\b(?:book|article|paper)\s+(.+?)\s*(?:\.|,|$)',
    ]
    
    title_fragment = ""
    for pattern in title_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            title_fragment = match.group(1).strip()
            break
    
    # If no title pattern found, extract remaining content words
    if not title_fragment:
        words = query.split()
        content_words = [w for w in words if w.lower() not in NOISE_WORDS and len(w) > 2]
        # Skip the author if we already extracted it
        if author and content_words and content_words[0].lower() == author.split()[0].lower():
            content_words = content_words[1:]
        title_fragment = " ".join(content_words)
    
    # Combine author and title
    if author and title_fragment:
        enhanced = f"{author} {title_fragment}"
    elif title_fragment:
        enhanced = title_fragment
    elif author:
        enhanced = author
    else:
        enhanced = query  # Fallback to original
    
    # Clean up extra whitespace
    enhanced = " ".join(enhanced.split())
    
    print(f"[QueryEnhance] Regex: '{query}' → '{enhanced}'")
    return enhanced


def enhance_query(query: str, citation_type: 'CitationType', use_gemini: bool = True) -> str:
    """
    Enhance a messy note query into a clean search query.
    
    Uses Gemini if available, falls back to regex extraction.
    
    Args:
        query: The raw user input (possibly a messy note)
        citation_type: Detected citation type
        use_gemini: Whether to try Gemini enhancement
        
    Returns:
        Enhanced search query
    """
    # Check if enhancement is needed
    if not is_messy_note(query):
        return query
    
    print(f"[QueryEnhance] Detected messy note: '{query}'")
    
    # Try Gemini first
    if use_gemini:
        try:
            from gemini_router import gemini_enhance
            enhanced = gemini_enhance(query, citation_type)
            if enhanced and enhanced != query:
                print(f"[QueryEnhance] Gemini: '{query}' → '{enhanced}'")
                return enhanced
        except ImportError:
            pass  # Gemini not available
        except Exception as e:
            print(f"[QueryEnhance] Gemini error: {e}")
    
    # Fallback to regex extraction
    return extract_search_terms_regex(query, citation_type)


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
    
    # Step 2: If low confidence, try Gemini fallback for classification
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
    
    # ==========================================================================
    # Step 2.5: Enhance query for search-based types
    # This cleans messy notes like "Eric wrote an article called trains"
    # into searchable queries like "Eric trains"
    # ==========================================================================
    search_query = enhance_query(clean_query, detection.citation_type, use_gemini)
    
    # Types that use search engines
    if detection.citation_type == CitationType.LEGAL:
        return search_legal(search_query)
    
    if detection.citation_type == CitationType.MEDICAL:
        return search_medical(search_query)
    
    if detection.citation_type == CitationType.JOURNAL:
        return search_journal(search_query)
    
    if detection.citation_type == CitationType.BOOK:
        # Try book-specific search first
        result = search_book(search_query)
        if result and result.has_minimum_data():
            return result
        # Fall back to journal search (sometimes books are in journal databases)
        result = search_journal(search_query)
        if result:
            return result
    
    # Unknown type - try journal search as default (with Google CSE fallback)
    return search_journal(search_query)


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
