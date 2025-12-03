"""
engines/doi.py

DOI extraction from academic publisher URLs and direct Crossref lookup.

This provides a fast path for URLs that contain DOIs - instead of scraping
the page or searching, we extract the DOI and fetch metadata directly from
Crossref's API.
"""

import re
import requests
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from models import CitationMetadata, CitationType


# Academic publisher domains that embed DOIs in URLs
ACADEMIC_PUBLISHER_DOMAINS = {
    'journals.uchicago.edu',
    'tandfonline.com',
    'onlinelibrary.wiley.com',
    'link.springer.com',
    'sciencedirect.com',
    'nature.com',
    'science.org',
    'cell.com',
    'oup.com',
    'academic.oup.com',
    'cambridge.org',
    'sagepub.com',
    'pnas.org',
    'jstor.org',
    'ieee.org',
    'ieeexplore.ieee.org',
    'acm.org',
    'dl.acm.org',
    'aps.org',
    'journals.aps.org',
    'plos.org',
    'journals.plos.org',
    'mdpi.com',
    'frontiersin.org',
    'bmj.com',
    'nejm.org',
    'thelancet.com',
    'jamanetwork.com',
    'annualreviews.org',
    'degruyter.com',
    'brill.com',
    'taylorfrancis.com',
    'elsevier.com',
    'karger.com',
    'thieme.com',
    'liebertpub.com',
    'emerald.com',
    'ingentaconnect.com',
}

HEADERS = {
    'User-Agent': 'CiteFlex/1.0 (Academic Citation Tool; mailto:support@citeflex.com)'
}


def extract_doi_from_url(url: str) -> str:
    """
    Extract DOI from academic publisher URLs.
    
    Examples:
        https://www.journals.uchicago.edu/doi/10.1086/737056 → 10.1086/737056
        https://doi.org/10.1038/nature12373 → 10.1038/nature12373
        https://onlinelibrary.wiley.com/doi/10.1002/abc.123 → 10.1002/abc.123
    
    Args:
        url: The URL to extract DOI from
        
    Returns:
        The DOI string, or empty string if not found
    """
    if not url or 'http' not in url.lower():
        return ''
    
    # Pattern 1: doi.org direct links
    if 'doi.org/' in url:
        match = re.search(r'doi\.org/(10\.\d{4,9}/[^\s&?#]+)', url)
        if match:
            return match.group(1).rstrip('.,;:)')
    
    # Pattern 2: /doi/ in path (most publishers)
    if '/doi/' in url:
        match = re.search(r'/doi/(?:full/|abs/|pdf/)?(10\.\d{4,9}/[^\s&?#]+)', url)
        if match:
            return match.group(1).rstrip('.,;:)')
    
    # Pattern 3: DOI in query string
    match = re.search(r'[?&]doi=(10\.\d{4,9}/[^\s&?#]+)', url)
    if match:
        return match.group(1).rstrip('.,;:)')
    
    # Pattern 4: article ID patterns (Nature, Science, etc.)
    # nature.com/articles/s41586-021-03819-2 → 10.1038/s41586-021-03819-2
    if 'nature.com/articles/' in url:
        match = re.search(r'nature\.com/articles/(s\d+-\d+-\d+-\w+)', url)
        if match:
            return f"10.1038/{match.group(1)}"
    
    return ''


def is_academic_publisher_url(url: str) -> bool:
    """
    Check if URL is from a known academic publisher.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is from a known academic publisher
    """
    if not url or 'http' not in url.lower():
        return False
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return any(pub_domain in domain for pub_domain in ACADEMIC_PUBLISHER_DOMAINS)
    except:
        return False


def fetch_crossref_by_doi(doi: str, original_url: str = '') -> Optional[CitationMetadata]:
    """
    Fetch metadata directly from Crossref using a DOI.
    This is faster and more reliable than searching.
    
    Args:
        doi: The DOI to look up
        original_url: The original URL (preserved in output)
        
    Returns:
        CitationMetadata object, or None if not found
    """
    if not doi:
        return None
    
    try:
        url = f"https://api.crossref.org/works/{doi}"
        print(f"[Crossref DOI] Fetching: {doi}")
        response = requests.get(url, headers=HEADERS, timeout=5)
        
        if response.status_code == 200:
            data = response.json().get('message', {})
            if data:
                metadata = _normalize_crossref(data, original_url or doi)
                print(f"[Crossref DOI] Found: {metadata.title[:50] if metadata.title else 'Unknown'}...")
                return metadata
        else:
            print(f"[Crossref DOI] Not found: {response.status_code}")
    except Exception as e:
        print(f"[Crossref DOI] Error: {e}")
    
    return None


def _normalize_crossref(data: Dict[str, Any], original_text: str) -> CitationMetadata:
    """
    Normalize Crossref API response to CitationMetadata.
    
    Args:
        data: The Crossref API response data
        original_text: The original query text or URL
        
    Returns:
        CitationMetadata object
    """
    # Extract authors
    authors = []
    for author in data.get('author', []):
        given = author.get('given', '')
        family = author.get('family', '')
        if given and family:
            authors.append(f"{given} {family}")
        elif family:
            authors.append(family)
    
    # Extract year
    year = ''
    try:
        # Try published date first
        if 'published' in data and 'date-parts' in data['published']:
            year = str(data['published']['date-parts'][0][0])
        # Fall back to created date
        elif 'created' in data and 'date-parts' in data['created']:
            year = str(data['created']['date-parts'][0][0])
    except (KeyError, IndexError, TypeError):
        pass
    
    # Get DOI and construct URL
    doi = data.get('DOI', '')
    doi_url = f"https://doi.org/{doi}" if doi else ''
    
    # Determine citation type based on Crossref type
    crossref_type = data.get('type', 'journal-article')
    if crossref_type in ['book', 'monograph', 'edited-book']:
        citation_type = CitationType.BOOK
    elif crossref_type in ['book-chapter', 'book-section']:
        citation_type = CitationType.BOOK  # Could add BOOK_CHAPTER type
    else:
        citation_type = CitationType.JOURNAL
    
    return CitationMetadata(
        citation_type=citation_type,
        title=data.get('title', [''])[0] if data.get('title') else '',
        authors=authors,
        year=year,
        journal=data.get('container-title', [''])[0] if data.get('container-title') else '',
        volume=data.get('volume', ''),
        issue=data.get('issue', ''),
        pages=data.get('page', ''),
        publisher=data.get('publisher', ''),
        doi=doi,
        url=doi_url,
        raw_source=original_text,
        source_engine='Crossref (DOI Direct)'
    )
