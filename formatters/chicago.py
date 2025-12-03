"""
citeflex/formatters/chicago.py

Chicago Manual of Style (17th ed.) citation formatter.
This is the default style for history and humanities.

Uses <i> tags for italics (Word-compatible).
"""

from typing import Optional
from formatters.base import BaseFormatter, register_formatter
from models import CitationMetadata, CitationStyle


@register_formatter(CitationStyle.CHICAGO)
@register_formatter('Chicago')
@register_formatter('Chicago Manual of Style')
@register_formatter('CMS')
class ChicagoFormatter(BaseFormatter):
    """
    Chicago Manual of Style formatter.
    
    Notes-Bibliography style (commonly used in history).
    
    Format patterns:
    - Journal: Author, "Title," Journal Vol, no. Issue (Year): Pages. DOI
    - Book: Author, Title (Place: Publisher, Year).
    - Legal: Case Name, Citation (Court Year).
    - Interview: Subject, interview by Interviewer, Location, Date.
    - Newspaper: Author, "Title," Newspaper, Date. URL
    - Government: Agency, Title. URL
    
    Short form patterns:
    - Journal: Author, "Short Title," page.
    - Book: Author, Short Title, page.
    - Legal: Case Name, citation at page.
    - Interview: Subject interview.
    - Newspaper: Author, "Short Title."
    - Government: Short Title.
    """
    
    style = CitationStyle.CHICAGO
    
    def format_journal(self, m: CitationMetadata) -> str:
        """
        Chicago journal article format:
        Author, "Title," Journal Vol, no. Issue (Year): Pages. DOI/URL
        """
        parts = []
        
        # Authors
        if m.authors:
            parts.append(self.format_authors(m.authors, 'chicago'))
        
        # Title in quotes
        if m.title:
            parts.append(self.quote(m.title))
        
        # Journal info
        journal_str = self.italicize(m.journal) if m.journal else ""
        if m.volume:
            journal_str += f" {m.volume}"
        if m.issue:
            journal_str += f", no. {m.issue}"
        if m.year:
            journal_str += f" ({m.year})"
        if m.pages:
            journal_str += f": {m.pages}"
        if journal_str:
            parts.append(journal_str)
        
        # DOI or URL
        if m.doi:
            doi_url = m.doi if m.doi.startswith('http') else f"https://doi.org/{m.doi}"
            parts.append(doi_url)
        elif m.url:
            parts.append(m.url)
        
        result = ", ".join(filter(None, parts))
        return result + "." if result and not result.endswith('.') else result
    
    def format_book(self, m: CitationMetadata) -> str:
        """
        Chicago book format:
        Author, Title (Place: Publisher, Year).
        """
        parts = []
        
        # Authors
        if m.authors:
            parts.append(self.format_authors(m.authors, 'chicago'))
        
        # Title in italics
        if m.title:
            parts.append(self.italicize(m.title))
        
        # Publication info in parentheses
        pub_parts = []
        if m.place:
            pub_parts.append(m.place)
        if m.publisher:
            pub_parts.append(m.publisher)
        if m.year:
            pub_parts.append(str(m.year))
        
        if pub_parts:
            if m.place and m.publisher:
                pub_str = f"{m.place}: {m.publisher}"
                if m.year:
                    pub_str += f", {m.year}"
            else:
                pub_str = ", ".join(pub_parts)
            parts.append(f"({pub_str})")
        
        result = ", ".join(filter(None, parts))
        return result + "." if result and not result.endswith('.') else result
    
    def format_legal(self, m: CitationMetadata) -> str:
        """
        Chicago legal citation format:
        Case Name, Citation (Court Year).
        
        For UK citations:
        Case Name [Year] Court Number
        """
        # UK-style neutral citation
        if m.jurisdiction == 'UK' and m.neutral_citation:
            return f"{self.italicize(m.case_name)} {m.neutral_citation}"
        
        # US-style citation
        case_name = self.italicize(m.case_name) if m.case_name else ""
        
        # Build parenthetical (Court Year)
        paren_parts = []
        if m.court and 'U.S.' not in (m.citation or ''):
            # Don't repeat court for Supreme Court cases with U.S. citation
            paren_parts.append(m.court)
        if m.year:
            paren_parts.append(str(m.year))
        
        parenthetical = f"({' '.join(paren_parts)})" if paren_parts else ""
        
        if m.citation:
            return f"{case_name}, {m.citation} {parenthetical}.".replace('  ', ' ')
        return f"{case_name} {parenthetical}.".replace('  ', ' ')
    
    def format_interview(self, m: CitationMetadata) -> str:
        """
        Chicago interview format:
        Subject, interview by Interviewer, Location, Date.
        """
        parts = []
        
        # Subject (interviewee)
        if m.interviewee:
            parts.append(m.interviewee)
        
        # Interview phrase
        if m.interviewer:
            parts.append(f"interview by {m.interviewer}")
        else:
            parts.append("interview by author")
        
        # Location
        if m.location:
            parts.append(m.location)
        
        # Date
        if m.date:
            parts.append(m.date)
        
        result = ", ".join(filter(None, parts))
        return result + "." if result and not result.endswith('.') else result
    
    def format_newspaper(self, m: CitationMetadata) -> str:
        """
        Chicago newspaper format:
        Author, "Title," Newspaper, Date. URL
        """
        parts = []
        
        # Author (often missing for news)
        if m.authors:
            parts.append(self.format_authors(m.authors, 'chicago'))
        
        # Title in quotes
        if m.title:
            parts.append(self.quote(m.title))
        
        # Newspaper name in italics
        if m.newspaper:
            parts.append(self.italicize(m.newspaper))
        
        # Date
        if m.date:
            parts.append(m.date)
        
        # URL
        if m.url:
            parts.append(m.url)
        
        result = ", ".join(filter(None, parts))
        return result + "." if result and not result.endswith('.') else result
    
    def format_government(self, m: CitationMetadata) -> str:
        """
        Chicago government document format:
        Agency, Title. URL
        """
        parts = []
        
        # Agency as author
        agency = m.agency or "U.S. Government"
        parts.append(agency)
        
        # Title in italics
        if m.title:
            parts.append(self.italicize(m.title))
        
        # Date if available
        if m.date:
            parts.append(m.date)
        
        # URL
        if m.url:
            parts.append(m.url)
        
        result = ", ".join(filter(None, parts))
        return result + "." if result and not result.endswith('.') else result
    
    # =========================================================================
    # SHORT FORM METHODS - Chicago style
    # =========================================================================
    
    def format_short_journal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for journal article.
        
        Pattern: Author, "Short Title," page.
        Example: Watson and Crick, "Molecular Structure," 737.
        """
        parts = []
        
        # Author last name(s)
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=2))
        
        # Short title in quotes
        short_title = self._get_short_title(m.title)
        if short_title:
            parts.append(f'"{short_title}"')
        
        result = ", ".join(parts)
        
        # Add page if provided
        if page:
            result += f", {page}"
        
        return result + "." if result else m.raw_source or "Unknown source"
    
    def format_short_book(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for book.
        
        Pattern: Author, Short Title, page.
        Example: Klerman, Lazarus, 45.
        """
        parts = []
        
        # Author last name(s)
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=2))
        
        # Short title in italics
        short_title = self._get_short_title(m.title)
        if short_title:
            parts.append(self.italicize(short_title))
        
        result = ", ".join(parts)
        
        # Add page if provided
        if page:
            result += f", {page}"
        
        return result + "." if result else m.raw_source or "Unknown source"
    
    def format_short_legal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for legal case.
        
        Pattern: Case Name, citation at page.
        Example: Roe v. Wade, 410 U.S. at 153.
        
        Or just: Case Name (if no pinpoint).
        Example: Roe v. Wade.
        """
        parts = []
        
        # Case name in italics (shortened if very long)
        if m.case_name:
            # Use first party name for very long case names
            case_name = m.case_name
            if ' v. ' in case_name or ' v ' in case_name:
                # Keep full case name for short form in Chicago
                pass
            parts.append(self.italicize(case_name))
        
        # Add citation with pinpoint if page provided
        if page and m.citation:
            parts.append(f"{m.citation} at {page}")
        elif m.citation:
            parts.append(m.citation)
        
        result = ", ".join(parts)
        return result + "." if result else m.raw_source or "Unknown source"
    
    def format_short_interview(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for interview.
        
        Pattern: Subject interview.
        Example: Klerman interview.
        """
        if m.interviewee:
            # Get last name
            name_parts = m.interviewee.split()
            last_name = name_parts[-1] if name_parts else m.interviewee
            return f"{last_name} interview."
        
        return "Interview."
    
    def format_short_newspaper(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for newspaper article.
        
        Pattern: Author, "Short Title."
        Example: Smith, "Court Ruling."
        """
        parts = []
        
        # Author last name
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=1))
        
        # Short title in quotes
        short_title = self._get_short_title(m.title)
        if short_title:
            parts.append(f'"{short_title}"')
        
        result = ", ".join(parts)
        return result + "." if result else m.raw_source or "Unknown source"
    
    def format_short_government(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for government document.
        
        Pattern: Short Title.
        Example: Mental Health Report.
        """
        short_title = self._get_short_title(m.title)
        if short_title:
            result = self.italicize(short_title)
            if page:
                result += f", {page}"
            return result + "."
        
        return m.raw_source or "Unknown source"
    
    def format_short_url(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Chicago short form for web page.
        
        Pattern: "Short Title."
        """
        short_title = self._get_short_title(m.title)
        if short_title:
            return f'"{short_title}."'
        
        return m.url or m.raw_source or "Unknown source"
