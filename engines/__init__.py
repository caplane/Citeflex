"""
citeflex/engines/__init__.py

Search engines package.
"""

from .base import SearchEngine, MultiAttemptEngine
from .academic import (
    CrossrefEngine,
    OpenAlexEngine,
    SemanticScholarEngine,
    PubMedEngine,
)
from .legal import (
    FamousCasesCache,
    UKCitationParser,
    CourtListenerEngine,
    LegalSearchEngine,
)
from .google_cse import (
    GoogleCSEEngine,
    GoogleBooksEngine,
    OpenLibraryEngine,
)

__all__ = [
    # Base
    'SearchEngine',
    'MultiAttemptEngine',
    # Academic
    'CrossrefEngine',
    'OpenAlexEngine', 
    'SemanticScholarEngine',
    'PubMedEngine',
    # Legal
    'FamousCasesCache',
    'UKCitationParser',
    'CourtListenerEngine',
    'LegalSearchEngine',
    # Google/Books
    'GoogleCSEEngine',
    'GoogleBooksEngine',
    'OpenLibraryEngine',
]
