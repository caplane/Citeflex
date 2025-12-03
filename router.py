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

# -----------------------------------------------------------------------------
# Validation helpers (must be defined before search functions that use them)
# -----------------------------------------------------------------------------

def _validate_year_match(expected_year: Optional[str], result: CitationMetadata) -> bool:
    """
    Validate that a search result's year matches the expected year.
    
    Returns True if:
    - No expected year (can't validate)
    - Result has no year (can't validate)
    - Years match exactly
    - Years are within 1 year (allow for publication delays)
    
    Returns False if:
    - Years differ by more than 1 year
    """
    if not expected_year or not result.year:
        return True  # Can't validate
    
    try:
        expected = int(expected_year)
        actual = int(result.year)
        # Allow 1 year variance for publication delays
        return abs(expected - actual) <= 1
    except (ValueError, TypeError):
        return True  # Can't parse, assume OK


def _validate_author_match(original_query: str, result: CitationMetadata) -> bool:
    """
    Validate that a search result's author matches what was in the original query.
    
    If we can extract a potential author name from the query (e.g., "Woo" from 
    "Woo master slave"), check that the result has an author with that name.
    
    Returns True if:
    - No author could be extracted from query (can't validate)
    - Author was extracted and matches a result author
    
    Returns False if:
    - Author was extracted but result has no authors (suspicious)
    - Author was extracted but doesn't match any result author
    """
    # Try to extract author from query (first capitalized word)
    author_match = re.match(r'^([A-Z][a-z]+)', original_query)
    if not author_match:
        return True  # Can't extract author from query, assume OK
    
    query_author = author_match.group(1).lower()
    
    # If we extracted an author but result has no authors, that's suspicious
    if not result or not result.authors:
        return False
    
    # Check if any result author contains this name
    for author in result.authors:
        if query_author in author.lower():
            return True
    
    # Also check if result title contains author name (some formats put author in title)
    if result.title and query_author in result.title.lower():
        return True
    
    return False


def _log_validation_warning(engine_name: str, result: CitationMetadata, 
                            expected_year: Optional[str], query: str) -> None:
    """Log validation warnings without rejecting results."""
    warnings = []
    
    if expected_year and result.year:
        try:
            if abs(int(expected_year) - int(result.year)) > 1:
                warnings.append(f"year mismatch (expected {expected_year}, got {result.year})")
        except (ValueError, TypeError):
            pass
    
    if not _validate_author_match(query, result):
        warnings.append("possible author mismatch")
    
    if warnings:
        print(f"[Search] Warning for {engine_name} result '{result.title}': {', '.join(warnings)}")


# -----------------------------------------------------------------------------
# Search functions
# -----------------------------------------------------------------------------

def search_journal(query: str) -> Optional[CitationMetadata]:
    """
    Search for a journal article across multiple engines.
    
    Search order (optimized for finding obscure/older articles):
    1. Google CSE FIRST (searches JSTOR, Google Scholar - best coverage)
    2. Crossref (DOI registry)
    3. OpenAlex (broad coverage)
    4. Semantic Scholar (author-aware)
    
    Uses multiple search strategies. Logs validation warnings but accepts
    first valid result (trusts search engine relevance ranking).
    
    Returns first successful result.
    """
    # Extract year from query if present (for validation logging)
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', query)
    expected_year = year_match.group(1) if year_match else None
    
    # Build query variations
    queries_to_try = []
    
    # Strategy 1: Add "article" or "journal" context to help disambiguate from books
    if 'article' not in query.lower() and 'journal' not in query.lower():
        queries_to_try.append(f"{query} article")
    
    # Strategy 2: Original query
    queries_to_try.append(query)
    
    # Strategy 3: Remove year from query (some engines don't like year in text search)
    if expected_year:
        query_no_year = query.replace(expected_year, '').strip()
        query_no_year = ' '.join(query_no_year.split())  # Clean up extra spaces
        if query_no_year and query_no_year != query:
            queries_to_try.append(query_no_year)
    
    # ==========================================================================
    # Engine 1: Google CSE FIRST (best for JSTOR, older articles, obscure sources)
    # ==========================================================================
    google_cse = _get_engine('google_cse')
    if google_cse:
        for search_query in queries_to_try[:2]:  # Try first two variations
            print(f"[SearchJournal] Trying Google CSE: '{search_query}'")
            result = google_cse.search(search_query)
            if result and result.has_minimum_data():
                _log_validation_warning('Google CSE', result, expected_year, query)
                print(f"[SearchJournal] Found via Google CSE: {result.title}")
                return result
    
    # ==========================================================================
    # Engines 2-4: Other academic engines with query variations
    # ==========================================================================
    for search_query in queries_to_try:
        print(f"[SearchJournal] Trying: '{search_query}'")
        
        for engine_name in ['crossref', 'openalex', 'semantic_scholar']:
            engine = _get_engine(engine_name)
            if engine:
                result = engine.search(search_query)
                if result and result.has_minimum_data():
                    _log_validation_warning(engine_name, result, expected_year, query)
                    print(f"[SearchJournal] Found via {engine_name}: {result.title} ({result.year})")
                    return result
    
    return None


def search_book(query: str) -> Optional[CitationMetadata]:
    """
    Search for a book.
    
    Search order:
    1. Open Library (free, good for ISBN)
    2. Google Books (broad coverage)
    3. OpenAlex (academic books)
    
    Uses multiple search strategies:
    1. Original query + "book" context
    2. Original query alone
    3. Query variations (fuller title if possible)
    
    Logs validation warnings but accepts first valid result.
    
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
    
    # Build list of query variations to try
    queries_to_try = []
    
    # Strategy 1: Add "book" to help disambiguate from technical terms
    if 'book' not in query.lower():
        queries_to_try.append(f"{query} book")
    
    # Strategy 2: Original query
    queries_to_try.append(query)
    
    # Strategy 3: If query looks like "Author title", try with quotes around title
    # e.g., "Woo master slave" -> 'Woo "master slave"'
    words = query.split()
    if len(words) >= 2:
        # Assume first word(s) are author, rest is title
        # Try: Author "title words"
        author_part = words[0]
        title_part = " ".join(words[1:])
        if len(title_part) > 3:  # Only if title is substantial
            queries_to_try.append(f'{author_part} "{title_part}"')
    
    # Try each query variation
    for search_query in queries_to_try:
        print(f"[SearchBook] Trying: '{search_query}'")
        
        for engine_name in ['google_books', 'open_library']:
            engine = _get_engine(engine_name)
            if engine:
                result = engine.search(search_query)
                if result and result.has_minimum_data():
                    # Log validation warning but accept result
                    if not _validate_author_match(query, result):
                        print(f"[SearchBook] Warning: possible author mismatch for '{result.title}'")
                    print(f"[SearchBook] Found via {engine_name}: {result.title}")
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
    
    Messy notes include:
    - Informal references like "Eric wrote an article called trains"
    - Terse keyword queries like "Caplan trains brains 1995"
    - Partial references like "Woo master slave"
    
    Clean citations have structured elements like:
    - DOI, ISBN, volume/issue numbers
    - Publisher names with place
    - Formal citation patterns (journal name, page numbers)
    
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
    
    # Check for explicit messy note patterns
    for pattern in MESSY_NOTE_PATTERNS:
        if re.search(pattern, lower):
            return True
    
    # NEW: Detect terse keyword-only queries that need enhancement
    # These look like: "Author keyword keyword year" or "Author title-words"
    # Characteristics:
    # - Short (under 10 words)
    # - No punctuation like commas, colons, periods (except at end)
    # - No journal/publisher indicators
    # - Mostly just keywords
    
    # Remove trailing period for analysis
    clean = query.rstrip('.')
    
    # Count words
    words = clean.split()
    word_count = len(words)
    
    # If it's very short (2-8 words) with no structural punctuation, likely needs enhancement
    if 2 <= word_count <= 8:
        # Check for structural punctuation (commas, colons, semicolons indicate structure)
        if not re.search(r'[,:;]', clean):
            # Check if it lacks journal/publisher indicators
            publisher_indicators = ['press', 'university', 'journal', 'review', 'quarterly', 
                                    'publishing', 'publishers', 'books', 'edition']
            has_publisher = any(ind in lower for ind in publisher_indicators)
            
            if not has_publisher:
                # Looks like a terse query - enhance it
                print(f"[is_messy_note] Detected terse keyword query: '{query}'")
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
