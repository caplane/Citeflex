"""
citeflex/engines/google_cse.py

Google Custom Search Engine for academic sources.

This is the "nuclear option" - when specialized APIs fail, Google CSE
searches across:
- JSTOR
- Google Scholar
- PubMed
- Oxford Academic
- Cambridge University Press
- Taylor & Francis
- Springer
- Wiley
- SAGE
- Project MUSE
- ScienceDirect
- HeinOnline (legal journals)
- HathiTrust (books)
- Internet Archive (books)
- WorldCat (books)

The engine parses results, extracts metadata from citation_ metatags,
and does follow-up enrichment via academic APIs.
"""

import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from .base import SearchEngine
from .academic import CrossrefEngine, OpenAlexEngine, SemanticScholarEngine, PubMedEngine
from ..models import CitationMetadata, CitationType
from ..config import GOOGLE_CSE_API_KEY, GOOGLE_CSE_ID, ACADEMIC_DOMAINS


class GoogleCSEEngine(SearchEngine):
    """
    Google Custom Search Engine targeting academic sources.
    
    Strategy:
    1. Search Google CSE (configured to prioritize academic sites)
    2. Parse results for basic metadata
    3. If result is from known source (PubMed, JSTOR), fetch via their API
    4. Otherwise, enrich via Crossref/OpenAlex/Semantic Scholar
    
    This is the fallback when specialized APIs don't find what you need.
    """
    
    name = "Google CSE"
    base_url = "https://www.googleapis.com/customsearch/v1"
    
    def __init__(self, api_key: Optional[str] = None, search_engine_id: Optional[str] = None, **kwargs):
        super().__init__(api_key=api_key or GOOGLE_CSE_API_KEY, **kwargs)
        self.search_engine_id = search_engine_id or GOOGLE_CSE_ID
        
        # Lazy-load enrichment engines
        self._crossref = None
        self._openalex = None
        self._semantic = None
        self._pubmed = None
    
    @property
    def crossref(self):
        if self._crossref is None:
            self._crossref = CrossrefEngine()
        return self._crossref
    
    @property
    def openalex(self):
        if self._openalex is None:
            self._openalex = OpenAlexEngine()
        return self._openalex
    
    @property
    def semantic(self):
        if self._semantic is None:
            self._semantic = SemanticScholarEngine()
        return self._semantic
    
    @property
    def pubmed(self):
        if self._pubmed is None:
            self._pubmed = PubMedEngine()
        return self._pubmed
    
    def search(self, query: str) -> Optional[CitationMetadata]:
        """
        Search Google CSE and return best enriched result.
        """
        if not self.api_key or not self.search_engine_id:
            print(f"[{self.name}] No API key or Search Engine ID configured")
            return None
        
        results = self._search_google(query, num_results=5)
        if not results:
            return None
        
        # Try each result until we get good metadata
        for item in results:
            metadata = self._process_result(item, query)
            if metadata and metadata.has_minimum_data():
                return metadata
        
        return None
    
    def search_multiple(self, query: str, limit: int = 5) -> List[CitationMetadata]:
        """
        Search and return multiple results.
        """
        if not self.api_key or not self.search_engine_id:
            return []
        
        results = self._search_google(query, num_results=limit)
        metadata_list = []
        
        for item in results[:limit]:
            metadata = self._process_result(item, query)
            if metadata and metadata.has_minimum_data():
                metadata_list.append(metadata)
        
        return metadata_list
    
    def _search_google(self, query: str, num_results: int = 5) -> List[dict]:
        """Execute Google CSE search."""
        params = {
            'key': self.api_key,
            'cx': self.search_engine_id,
            'q': query,
            'num': num_results
        }
        
        response = self._make_request(self.base_url, params=params)
        if not response:
            return []
        
        try:
            data = response.json()
            return data.get('items', [])
        except Exception as e:
            print(f"[{self.name}] Parse error: {e}")
            return []
    
    def _process_result(self, item: dict, query: str) -> Optional[CitationMetadata]:
        """
        Process a single search result.
        
        1. Check if it's from a known source (PubMed, JSTOR) → fetch via API
        2. Parse metatags for citation data
        3. Enrich via academic APIs if needed
        """
        link = item.get('link', '')
        title = item.get('title', '')
        snippet = item.get('snippet', '')
        pagemap = item.get('pagemap', {})
        metatags = pagemap.get('metatags', [{}])[0] if pagemap.get('metatags') else {}
        
        # =================================================================
        # STRATEGY 1: Known source detection → use specialized API
        # =================================================================
        
        # PubMed link → fetch from PubMed API
        pubmed_match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', link)
        if pubmed_match:
            pmid = pubmed_match.group(1)
            print(f"[{self.name}] Found PubMed ID: {pmid}, fetching via API...")
            result = self.pubmed.get_by_id(pmid)
            if result:
                result.source_engine = f"{self.name} → PubMed"
                return result
        
        # JSTOR link → try to get DOI and fetch from Crossref
        jstor_match = re.search(r'jstor\.org/stable/(\d+)', link)
        if jstor_match:
            jstor_id = jstor_match.group(1)
            print(f"[{self.name}] Found JSTOR ID: {jstor_id}")
            # JSTOR DOIs follow pattern 10.2307/{id}
            doi = f"10.2307/{jstor_id}"
            result = self.crossref.get_by_id(doi)
            if result:
                result.source_engine = f"{self.name} → JSTOR/Crossref"
                return result
        
        # =================================================================
        # STRATEGY 2: Parse metatags from academic publishers
        # =================================================================
        
        metadata = self._parse_metatags(metatags, link, query)
        
        # If metatags gave us a title, try to enrich
        if metadata.title:
            enriched = self._enrich_metadata(metadata, query)
            if enriched:
                return enriched
        
        # =================================================================
        # STRATEGY 3: Parse from title/snippet as fallback
        # =================================================================
        
        if not metadata.title:
            metadata = self._parse_from_snippet(title, snippet, link, query)
        
        # Final enrichment attempt
        if metadata.title:
            enriched = self._enrich_metadata(metadata, query)
            if enriched:
                return enriched
        
        # Return what we have
        metadata.source_engine = self._get_source_name(link)
        return metadata if metadata.has_minimum_data() else None
    
    def _parse_metatags(self, metatags: dict, url: str, query: str) -> CitationMetadata:
        """
        Parse citation_ metatags from academic publisher pages.
        
        Standard metatags (used by most publishers):
        - citation_title
        - citation_author (may appear multiple times)
        - citation_publication_date / citation_date
        - citation_journal_title / citation_journal_abbrev
        - citation_volume
        - citation_issue
        - citation_firstpage / citation_lastpage
        - citation_doi
        """
        metadata = CitationMetadata(
            citation_type=CitationType.JOURNAL,
            raw_source=query,
            url=url
        )
        
        if not metatags:
            return metadata
        
        # Title
        metadata.title = metatags.get('citation_title', '')
        
        # Journal
        metadata.journal = (
            metatags.get('citation_journal_title', '') or 
            metatags.get('citation_journal_abbrev', '')
        )
        
        # Volume/Issue
        metadata.volume = metatags.get('citation_volume', '')
        metadata.issue = metatags.get('citation_issue', '')
        
        # DOI
        metadata.doi = metatags.get('citation_doi', '')
        
        # Pages
        first_page = metatags.get('citation_firstpage', '')
        last_page = metatags.get('citation_lastpage', '')
        if first_page and last_page:
            metadata.pages = f"{first_page}-{last_page}"
        elif first_page:
            metadata.pages = first_page
        
        # Year from publication date
        pub_date = metatags.get('citation_publication_date', '') or metatags.get('citation_date', '')
        if pub_date:
            year_match = re.search(r'(19|20)\d{2}', pub_date)
            if year_match:
                metadata.year = year_match.group(0)
        
        # Authors (may be single value or need to be parsed)
        author = metatags.get('citation_author', '')
        if author:
            metadata.authors = [author]
        
        return metadata
    
    def _parse_from_snippet(self, title: str, snippet: str, url: str, query: str) -> CitationMetadata:
        """
        Extract metadata from search result title and snippet.
        """
        metadata = CitationMetadata(
            citation_type=CitationType.JOURNAL,
            raw_source=query,
            url=url
        )
        
        # Clean title (remove "... - JSTOR", "| Oxford Academic", etc.)
        clean_title = re.sub(
            r'\s*[-|].*?(JSTOR|Google Scholar|PubMed|Oxford|Cambridge|Wiley|Springer|SAGE|Taylor|Project MUSE|ScienceDirect).*$',
            '', title, flags=re.IGNORECASE
        )
        clean_title = re.sub(r'\s*\.\.\.$', '', clean_title)
        metadata.title = clean_title.strip()
        
        # Extract year from title or snippet
        combined = f"{title} {snippet}"
        year_match = re.search(r'\b(19|20)\d{2}\b', combined)
        if year_match:
            metadata.year = year_match.group(0)
        
        # Extract author from snippet (often "by Author Name - ...")
        author_match = re.search(r'^(?:by\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*[-–·]', snippet)
        if author_match:
            metadata.authors = [author_match.group(1)]
        
        # Extract journal from snippet
        journal_patterns = [
            r'(?:published in|from)\s+([A-Z][^,\d]+?)(?:,|\d|$)',
            r'[-–·]\s*([A-Z][^,\d]+?),\s*\d{4}',
        ]
        for pattern in journal_patterns:
            match = re.search(pattern, snippet)
            if match:
                metadata.journal = match.group(1).strip()
                break
        
        # Determine type based on URL
        metadata.citation_type = self._detect_type_from_url(url)
        
        return metadata
    
    def _enrich_metadata(self, metadata: CitationMetadata, query: str) -> Optional[CitationMetadata]:
        """
        Enrich basic metadata by searching academic APIs with the title.
        
        Priority:
        1. Crossref (best for DOI/accurate metadata)
        2. Semantic Scholar (good for author matching)
        3. OpenAlex (broad coverage)
        """
        if not metadata.title:
            return None
        
        clean_title = re.sub(r'[^\w\s]', '', metadata.title).strip()
        if len(clean_title) < 10:
            return None
        
        print(f"[{self.name}] Enriching: {clean_title[:50]}...")
        
        # Try Crossref first
        cr_result = self.crossref.search(clean_title)
        if cr_result and self._is_same_article(metadata, cr_result):
            # Crossref found it - use Crossref data but note source
            cr_result.source_engine = f"{self.name} → Crossref"
            return cr_result
        
        # Try Semantic Scholar
        ss_result = self.semantic.search(clean_title)
        if ss_result and self._is_same_article(metadata, ss_result):
            ss_result.source_engine = f"{self.name} → Semantic Scholar"
            return ss_result
        
        # Try OpenAlex
        oa_result = self.openalex.search(clean_title)
        if oa_result and self._is_same_article(metadata, oa_result):
            oa_result.source_engine = f"{self.name} → OpenAlex"
            return oa_result
        
        # Enrichment failed, return original
        return None
    
    def _is_same_article(self, original: CitationMetadata, enriched: CitationMetadata) -> bool:
        """
        Check if enriched result matches original (avoid false positives).
        Uses fuzzy title matching.
        """
        import difflib
        
        if not original.title or not enriched.title:
            return False
        
        ratio = difflib.SequenceMatcher(
            None,
            original.title.lower(),
            enriched.title.lower()
        ).ratio()
        
        return ratio > 0.6
    
    def _detect_type_from_url(self, url: str) -> CitationType:
        """Detect citation type from URL domain."""
        url_lower = url.lower()
        
        if any(domain in url_lower for domain in ['courtlistener.com', 'oyez.org', 'heinonline.org']):
            return CitationType.LEGAL
        
        if any(domain in url_lower for domain in ['hathitrust.org', 'archive.org', 'worldcat.org']):
            return CitationType.BOOK
        
        return CitationType.JOURNAL
    
    def _get_source_name(self, url: str) -> str:
        """Get friendly source name from URL."""
        try:
            domain = urlparse(url).netloc.lower().replace('www.', '')
            
            # Check known domains
            for pattern, name in ACADEMIC_DOMAINS.items():
                if pattern in domain:
                    return f"{self.name} ({name})"
            
            return self.name
        except:
            return self.name


class GoogleBooksEngine(SearchEngine):
    """
    Google Books API for book searches.
    
    Best for:
    - ISBN lookups
    - Book title/author searches
    - Finding publisher and edition info
    """
    
    name = "Google Books"
    base_url = "https://www.googleapis.com/books/v1/volumes"
    
    def search(self, query: str) -> Optional[CitationMetadata]:
        params = {
            'q': query,
            'maxResults': 1,
            'printType': 'books'
        }
        
        response = self._make_request(self.base_url, params=params)
        if not response:
            return None
        
        try:
            data = response.json()
            items = data.get('items', [])
            if not items:
                return None
            return self._normalize(items[0], query)
        except Exception as e:
            print(f"[{self.name}] Parse error: {e}")
            return None
    
    def search_multiple(self, query: str, limit: int = 5) -> List[CitationMetadata]:
        params = {
            'q': query,
            'maxResults': limit,
            'printType': 'books'
        }
        
        response = self._make_request(self.base_url, params=params)
        if not response:
            return []
        
        try:
            data = response.json()
            items = data.get('items', [])
            return [self._normalize(item, query) for item in items[:limit]]
        except:
            return []
    
    def get_by_id(self, isbn: str) -> Optional[CitationMetadata]:
        """Look up by ISBN."""
        # Clean ISBN
        isbn = re.sub(r'[^\dX]', '', isbn.upper())
        return self.search(f"isbn:{isbn}")
    
    def _normalize(self, item: dict, raw_source: str) -> CitationMetadata:
        """Convert Google Books response to CitationMetadata."""
        info = item.get('volumeInfo', {})
        
        # Build title with subtitle
        title = info.get('title', '')
        if info.get('subtitle'):
            title = f"{title}: {info.get('subtitle')}"
        
        # Extract year from publishedDate (format: "2024-03-15" or "2024")
        year = None
        pub_date = info.get('publishedDate', '')
        if pub_date:
            year = pub_date[:4] if len(pub_date) >= 4 else None
        
        # Get ISBN
        isbn = ''
        for identifier in info.get('industryIdentifiers', []):
            if identifier.get('type') in ['ISBN_13', 'ISBN_10']:
                isbn = identifier.get('identifier', '')
                break
        
        # Get publisher place from our mapping
        from ..config import resolve_publisher_place
        publisher = info.get('publisher', '')
        place = resolve_publisher_place(publisher, '')
        
        return self._create_metadata(
            citation_type=CitationType.BOOK,
            raw_source=raw_source,
            title=title,
            authors=info.get('authors', []),
            year=year,
            publisher=publisher,
            place=place,
            isbn=isbn,
            url=info.get('infoLink', ''),
            raw_data=item
        )


class OpenLibraryEngine(SearchEngine):
    """
    Open Library API for book searches.
    
    Best for:
    - ISBN lookups (free, no API key needed)
    - Older/public domain books
    - Library catalog data
    """
    
    name = "Open Library"
    base_url = "https://openlibrary.org"
    
    def search(self, query: str) -> Optional[CitationMetadata]:
        """Search Open Library."""
        params = {
            'q': query,
            'limit': 1
        }
        
        response = self._make_request(f"{self.base_url}/search.json", params=params)
        if not response:
            return None
        
        try:
            data = response.json()
            docs = data.get('docs', [])
            if not docs:
                return None
            return self._normalize(docs[0], query)
        except Exception as e:
            print(f"[{self.name}] Parse error: {e}")
            return None
    
    def get_by_id(self, isbn: str) -> Optional[CitationMetadata]:
        """Look up by ISBN directly."""
        # Clean ISBN
        isbn = re.sub(r'[^\dX]', '', isbn.upper())
        
        response = self._make_request(f"{self.base_url}/isbn/{isbn}.json")
        if not response:
            return None
        
        try:
            data = response.json()
            return self._normalize_isbn(data, isbn)
        except:
            return None
    
    def _normalize(self, doc: dict, raw_source: str) -> CitationMetadata:
        """Convert Open Library search result to CitationMetadata."""
        # Get publisher place
        from ..config import resolve_publisher_place
        publishers = doc.get('publisher', [])
        publisher = publishers[0] if publishers else ''
        place = resolve_publisher_place(publisher, '')
        
        return self._create_metadata(
            citation_type=CitationType.BOOK,
            raw_source=raw_source,
            title=doc.get('title', ''),
            authors=doc.get('author_name', []),
            year=str(doc.get('first_publish_year', '')) if doc.get('first_publish_year') else None,
            publisher=publisher,
            place=place,
            isbn=doc.get('isbn', [''])[0] if doc.get('isbn') else '',
            raw_data=doc
        )
    
    def _normalize_isbn(self, data: dict, isbn: str) -> CitationMetadata:
        """Convert ISBN lookup result to CitationMetadata."""
        title = data.get('title', '')
        
        # Need to fetch authors separately (they're references)
        authors = []
        for author_ref in data.get('authors', []):
            key = author_ref.get('key', '')
            if key:
                author_resp = self._make_request(f"{self.base_url}{key}.json")
                if author_resp:
                    try:
                        author_data = author_resp.json()
                        authors.append(author_data.get('name', ''))
                    except:
                        pass
        
        # Get publisher info
        publishers = data.get('publishers', [])
        publisher = publishers[0] if publishers else ''
        
        from ..config import resolve_publisher_place
        place = resolve_publisher_place(publisher, '')
        
        return self._create_metadata(
            citation_type=CitationType.BOOK,
            raw_source=f"ISBN:{isbn}",
            title=title,
            authors=authors,
            publisher=publisher,
            place=place,
            isbn=isbn,
            url=f"{self.base_url}/isbn/{isbn}",
            raw_data=data
        )
