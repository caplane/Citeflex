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
