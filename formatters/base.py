"""
citeflex/formatters/base.py

Base citation formatter and style router.
"""

from abc import ABC, abstractmethod
from typing import Optional, List

from models import CitationMetadata, CitationType, CitationStyle


class BaseFormatter(ABC):
    """
    Abstract base class for citation formatters.
    
    Each style (Chicago, APA, etc.) implements this interface.
    Subclasses must implement format methods for each citation type.
    """
    
    style: CitationStyle = CitationStyle.CHICAGO
    
    def format(self, metadata: CitationMetadata) -> str:
        """
        Main entry point - routes to type-specific formatter.
        """
        # Route by citation type
        formatters = {
            CitationType.JOURNAL: self.format_journal,
            CitationType.BOOK: self.format_book,
            CitationType.LEGAL: self.format_legal,
            CitationType.INTERVIEW: self.format_interview,
            CitationType.NEWSPAPER: self.format_newspaper,
            CitationType.GOVERNMENT: self.format_government,
            CitationType.MEDICAL: self.format_medical,
            CitationType.URL: self.format_url,
        }
        
        formatter = formatters.get(metadata.citation_type)
        if formatter:
            return formatter(metadata)
        
        # Fallback
        return self.format_generic(metadata)
    
    # =========================================================================
    # IBID FORMATTING - Universal across all styles
    # =========================================================================
    
    @staticmethod
    def format_ibid(page: Optional[str] = None) -> str:
        """
        Format an ibid citation.
        
        Ibid (from Latin "ibidem" meaning "in the same place") is used when
        citing the same source as the immediately preceding citation.
        
        Rules:
        - Always lowercase: "ibid." not "Ibid."
        - Always roman (normal) font, never italic
        - Same page: "ibid."
        - Different page: "ibid., [page]"
        
        Args:
            page: Optional page number for different page in same source
            
        Returns:
            Formatted ibid string
        """
        if page:
            # Different page from same source
            return f"ibid., {page}."
        else:
            # Same source, same page (or page not specified)
            return "ibid."
    
    # =========================================================================
    # SHORT FORM FORMATTING - Style-specific implementations
    # =========================================================================
    
    def format_short(self, metadata: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Format a short form citation for subsequent references.
        
        Short form is used when citing a source that has been cited before
        in the document, but not immediately preceding (which would use ibid).
        
        Each style has different conventions for short forms:
        - Chicago: Author, "Short Title," page.
        - Bluebook: Case Name at page. / Author, supra, at page.
        - OSCOLA: Author (n X) page. / Short case name (n X).
        - MLA: Author page.
        - APA: Author (Year) or page reference.
        
        This base implementation provides a generic fallback.
        Subclasses should override for style-specific formatting.
        
        Args:
            metadata: The citation metadata
            page: Optional page number for pinpoint reference
            
        Returns:
            Formatted short form citation string
        """
        # Route by citation type for short form
        short_formatters = {
            CitationType.JOURNAL: self.format_short_journal,
            CitationType.BOOK: self.format_short_book,
            CitationType.LEGAL: self.format_short_legal,
            CitationType.INTERVIEW: self.format_short_interview,
            CitationType.NEWSPAPER: self.format_short_newspaper,
            CitationType.GOVERNMENT: self.format_short_government,
            CitationType.MEDICAL: self.format_short_journal,  # Same as journal
            CitationType.URL: self.format_short_url,
        }
        
        formatter = short_formatters.get(metadata.citation_type)
        if formatter:
            return formatter(metadata, page)
        
        # Generic fallback
        return self.format_short_generic(metadata, page)
    
    def format_short_journal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for journal article. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_book(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for book. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_legal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for legal case. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_interview(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for interview. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_newspaper(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for newspaper. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_government(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for government document. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_url(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for URL/web page. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def format_short_generic(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """Format short form for unknown types. Override in subclasses."""
        return self._default_short_form(m, page)
    
    def _default_short_form(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Default short form implementation.
        
        Uses first author's last name + short title.
        """
        parts = []
        
        # First author's last name
        if m.authors:
            first_author = m.authors[0]
            name_parts = first_author.split()
            if name_parts:
                parts.append(name_parts[-1])  # Last name
        
        # Short title
        short_title = self._get_short_title(m.title)
        if short_title:
            parts.append(self.italicize(short_title))
        
        result = ", ".join(parts)
        
        # Add page if provided
        if page:
            result += f", {page}"
        
        return result + "." if result else m.raw_source or "Unknown source"
    
    @staticmethod
    def _get_short_title(title: Optional[str], max_words: int = 4) -> str:
        """
        Generate a short title from a full title.
        
        Rules:
        - Use first 4 words (or fewer if title is short)
        - Omit initial articles (A, An, The)
        - End with ellipsis if truncated (optional - style dependent)
        
        Args:
            title: The full title
            max_words: Maximum words to include (default 4)
            
        Returns:
            Shortened title string
        """
        if not title:
            return ""
        
        words = title.split()
        
        # Remove leading articles
        articles = {'a', 'an', 'the'}
        while words and words[0].lower() in articles:
            words = words[1:]
        
        if not words:
            return title  # Return original if nothing left
        
        # Take first N words
        if len(words) <= max_words:
            return " ".join(words)
        
        return " ".join(words[:max_words])
    
    # =========================================================================
    # ABSTRACT METHODS - Must be implemented by each style
    # =========================================================================
    
    @abstractmethod
    def format_journal(self, m: CitationMetadata) -> str:
        """Format a journal article citation."""
        pass
    
    @abstractmethod
    def format_book(self, m: CitationMetadata) -> str:
        """Format a book citation."""
        pass
    
    @abstractmethod
    def format_legal(self, m: CitationMetadata) -> str:
        """Format a legal case citation."""
        pass
    
    @abstractmethod
    def format_interview(self, m: CitationMetadata) -> str:
        """Format an interview citation."""
        pass
    
    @abstractmethod
    def format_newspaper(self, m: CitationMetadata) -> str:
        """Format a newspaper article citation."""
        pass
    
    @abstractmethod
    def format_government(self, m: CitationMetadata) -> str:
        """Format a government document citation."""
        pass
    
    def format_medical(self, m: CitationMetadata) -> str:
        """Format a medical article. Default: same as journal."""
        return self.format_journal(m)
    
    def format_url(self, m: CitationMetadata) -> str:
        """Format a generic URL citation."""
        parts = []
        if m.title:
            parts.append(f'"{m.title}"')
        if m.access_date:
            parts.append(f"accessed {m.access_date}")
        if m.url:
            parts.append(m.url)
        return ", ".join(parts) + "." if parts else m.raw_source
    
    def format_generic(self, m: CitationMetadata) -> str:
        """Fallback for unknown types."""
        return m.raw_source or m.url or "Unknown source"
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    @staticmethod
    def format_authors(authors: List[str], style: str = 'default', max_authors: int = 3) -> str:
        """
        Format author list according to style conventions.
        
        Args:
            authors: List of author names (First Last format)
            style: One of 'default', 'apa', 'mla', 'chicago'
            max_authors: Maximum authors before et al.
        
        Returns:
            Formatted author string
        """
        if not authors:
            return ""
        
        def split_name(name: str) -> tuple:
            """Split 'First Last' into (first, last)."""
            parts = name.split()
            if len(parts) > 1:
                return parts[0], " ".join(parts[1:])
            return name, ""
        
        if style == 'apa':
            # APA: Last, F. I., & Last, F. I.
            formatted = []
            for name in authors[:max_authors]:
                first, last = split_name(name)
                initial = f"{first[0]}." if first else ""
                formatted.append(f"{last}, {initial}")
            
            if len(authors) > max_authors:
                return ", ".join(formatted[:-1]) + ", ... " + formatted[-1]
            elif len(formatted) > 1:
                return ", & ".join([", ".join(formatted[:-1]), formatted[-1]])
            return formatted[0] if formatted else ""
        
        elif style == 'mla':
            # MLA: Last, First, and First Last, et al.
            if len(authors) == 1:
                first, last = split_name(authors[0])
                return f"{last}, {first}"
            elif len(authors) == 2:
                f1, l1 = split_name(authors[0])
                return f"{l1}, {f1}, and {authors[1]}"
            else:
                f1, l1 = split_name(authors[0])
                return f"{l1}, {f1}, et al."
        
        else:  # default/chicago
            # Chicago: First Last and First Last
            if len(authors) == 1:
                return authors[0]
            elif len(authors) == 2:
                return f"{authors[0]} and {authors[1]}"
            else:
                return f"{authors[0]} et al."
    
    @staticmethod
    def get_author_last_name(author: str) -> str:
        """
        Extract last name from an author name.
        
        Args:
            author: Full author name (e.g., "James Watson")
            
        Returns:
            Last name (e.g., "Watson")
        """
        if not author:
            return ""
        parts = author.strip().split()
        return parts[-1] if parts else ""
    
    @staticmethod
    def get_authors_short(authors: List[str], max_authors: int = 1) -> str:
        """
        Get shortened author string for short form citations.
        
        Args:
            authors: List of author names
            max_authors: Max authors to include before "et al."
            
        Returns:
            Shortened author string (last names only)
        """
        if not authors:
            return ""
        
        last_names = []
        for author in authors[:max_authors]:
            parts = author.strip().split()
            if parts:
                last_names.append(parts[-1])
        
        if len(authors) > max_authors:
            return last_names[0] + " et al." if last_names else ""
        elif len(last_names) == 1:
            return last_names[0]
        elif len(last_names) == 2:
            return f"{last_names[0]} and {last_names[1]}"
        else:
            return ", ".join(last_names[:-1]) + f", and {last_names[-1]}"
    
    @staticmethod
    def italicize(text: str) -> str:
        """Wrap text in <i> tags for italics (Word-compatible)."""
        return f"<i>{text}</i>" if text else ""
    
    @staticmethod
    def quote(text: str) -> str:
        """Wrap text in quotation marks."""
        return f'"{text}"' if text else ""


# =============================================================================
# FORMATTER REGISTRY
# =============================================================================

_formatters = {}


def register_formatter(style):
    """
    Decorator to register a formatter class.
    
    Can be used with CitationStyle enum or string:
        @register_formatter(CitationStyle.APA)
        @register_formatter('APA 7')
        class APAFormatter: ...
    """
    def decorator(cls):
        # Normalize the key
        if isinstance(style, CitationStyle):
            key = style.value.lower()
        else:
            key = str(style).lower()
        _formatters[key] = cls
        return cls
    return decorator


def get_formatter(style) -> BaseFormatter:
    """
    Get formatter instance for a style.
    
    Accepts CitationStyle enum or string.
    
    Args:
        style: CitationStyle enum or string (e.g., 'APA', 'Chicago Manual of Style')
        
    Returns:
        Formatter instance
    """
    # Normalize the key
    if isinstance(style, CitationStyle):
        key = style.value.lower()
    else:
        key = str(style).lower()
    
    # Direct lookup
    formatter_cls = _formatters.get(key)
    if formatter_cls:
        return formatter_cls()
    
    # Try partial matching for common variations
    key_words = key.replace('-', ' ').replace('_', ' ').split()
    for registered_key, cls in _formatters.items():
        # Check if all words in the key appear in the registered key
        if all(word in registered_key for word in key_words):
            return cls()
        # Check if the registered key starts with our key
        if registered_key.startswith(key_words[0]):
            return cls()
    
    # Default to Chicago
    from formatters.chicago import ChicagoFormatter
    return ChicagoFormatter()


def format_citation(metadata: CitationMetadata, style = CitationStyle.CHICAGO) -> str:
    """
    Format a citation using the specified style.
    
    This is the main public API for formatting.
    
    Args:
        metadata: CitationMetadata to format
        style: Citation style to use (CitationStyle enum or string)
        
    Returns:
        Formatted citation string
    """
    formatter = get_formatter(style)
    return formatter.format(metadata)
