"""
citeflex/formatters/apa.py

APA 7th Edition citation formatter.
Common in psychology, education, and social sciences.

Uses <i> tags for italics (Word-compatible).
"""

import re
from typing import Optional
from formatters.base import BaseFormatter, register_formatter
from models import CitationMetadata, CitationStyle


@register_formatter(CitationStyle.APA)
@register_formatter('APA')
@register_formatter('APA 7')
@register_formatter('APA7')
class APAFormatter(BaseFormatter):
    """
    APA 7th Edition formatter.
    
    Format patterns:
    - Journal: Author, A. A., & Author, B. B. (Year). Title. Journal, Vol(Issue), pages. DOI
    - Book: Author, A. A. (Year). Title. Publisher.
    - Interview: Interviewee, A. A. (Year). [Interview].
    - Newspaper: Author, A. A. (Year, Month Day). Title. Newspaper. URL
    - Government: Agency. (Year). Title. URL
    
    Short form patterns (for footnotes/endnotes):
    - Author (Year, p. X)
    - Author (Year)
    """
    
    style = CitationStyle.APA
    
    def format_journal(self, m: CitationMetadata) -> str:
        """
        APA journal article format:
        Author, A. A., & Author, B. B. (Year). Title of article. Journal Name, Vol(Issue), pages. https://doi.org/xxx
        """
        parts = []
        
        # Authors (APA style: Last, F. I.)
        if m.authors:
            parts.append(self.format_authors(m.authors, 'apa'))
        
        # Year in parentheses
        year = m.year or 'n.d.'
        parts.append(f"({year}).")
        
        # Title (sentence case, no quotes, no italics)
        if m.title:
            parts.append(f"{m.title}.")
        
        # Journal in italics with volume
        journal_str = self.italicize(m.journal) if m.journal else ""
        if m.volume:
            journal_str += f", {self.italicize(m.volume)}"
            if m.issue:
                journal_str += f"({m.issue})"
        if m.pages:
            journal_str += f", {m.pages}"
        if journal_str:
            parts.append(journal_str + ".")
        
        # DOI (required when available)
        if m.doi:
            doi_url = m.doi if m.doi.startswith('http') else f"https://doi.org/{m.doi}"
            parts.append(doi_url)
        elif m.url:
            parts.append(m.url)
        
        return " ".join(filter(None, parts))
    
    def format_book(self, m: CitationMetadata) -> str:
        """
        APA book format:
        Author, A. A. (Year). Title of book. Publisher.
        """
        parts = []
        
        # Authors
        if m.authors:
            parts.append(self.format_authors(m.authors, 'apa'))
        
        # Year
        year = m.year or 'n.d.'
        parts.append(f"({year}).")
        
        # Title in italics
        if m.title:
            parts.append(self.italicize(m.title) + ".")
        
        # Publisher (no location in APA 7)
        if m.publisher:
            parts.append(m.publisher + ".")
        
        # DOI if available
        if m.doi:
            doi_url = m.doi if m.doi.startswith('http') else f"https://doi.org/{m.doi}"
            parts.append(doi_url)
        
        return " ".join(filter(None, parts))
    
    def format_legal(self, m: CitationMetadata) -> str:
        """
        APA legal citation format (uses Bluebook style):
        Case Name, Citation (Court Year).
        """
        # APA defers to Bluebook for legal citations
        case_name = self.italicize(m.case_name) if m.case_name else ""
        
        paren_parts = []
        if m.court and 'U.S.' not in (m.citation or ''):
            paren_parts.append(m.court)
        if m.year:
            paren_parts.append(str(m.year))
        
        parenthetical = f"({' '.join(paren_parts)})" if paren_parts else ""
        
        if m.citation:
            return f"{case_name}, {m.citation} {parenthetical}.".replace('  ', ' ')
        return f"{case_name} {parenthetical}.".replace('  ', ' ')
    
    def format_interview(self, m: CitationMetadata) -> str:
        """
        APA interview format:
        Interviewee, A. A. (Year, Month Day). [Description of interview].
        """
        parts = []
        
        # Interviewee as author
        if m.interviewee:
            # Try to format as Last, F. I.
            name_parts = m.interviewee.split()
            if len(name_parts) > 1:
                first = name_parts[0]
                last = " ".join(name_parts[1:])
                parts.append(f"{last}, {first[0]}.")
            else:
                parts.append(m.interviewee)
        
        # Date/Year
        year = m.year
        if not year and m.date:
            year_match = re.search(r'\d{4}', m.date)
            if year_match:
                year = year_match.group(0)
        year = year or 'n.d.'
        parts.append(f"({year}).")
        
        # Description
        desc = "[Interview]"
        if m.location:
            desc = f"[Interview conducted in {m.location}]"
        parts.append(desc + ".")
        
        return " ".join(filter(None, parts))
    
    def format_newspaper(self, m: CitationMetadata) -> str:
        """
        APA newspaper format:
        Author, A. A. (Year, Month Day). Title of article. Newspaper Name. URL
        """
        parts = []
        
        # Author
        if m.authors:
            parts.append(self.format_authors(m.authors, 'apa'))
        
        # Date
        date_str = m.date if m.date else 'n.d.'
        parts.append(f"({date_str}).")
        
        # Title (no italics for article titles)
        if m.title:
            parts.append(f"{m.title}.")
        
        # Newspaper in italics
        if m.newspaper:
            parts.append(self.italicize(m.newspaper) + ".")
        
        # URL
        if m.url:
            parts.append(m.url)
        
        return " ".join(filter(None, parts))
    
    def format_government(self, m: CitationMetadata) -> str:
        """
        APA government document format:
        Agency Name. (Year). Title. URL
        """
        parts = []
        
        # Agency as author
        agency = m.agency or "U.S. Government"
        parts.append(agency + ".")
        
        # Year
        year = m.year or 'n.d.'
        parts.append(f"({year}).")
        
        # Title in italics
        if m.title:
            parts.append(self.italicize(m.title) + ".")
        
        # URL
        if m.url:
            parts.append(m.url)
        
        return " ".join(filter(None, parts))
    
    # =========================================================================
    # SHORT FORM METHODS - APA style
    # =========================================================================
    
    def format_short_journal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for journal article.
        
        Pattern: Author (Year, p. X) or Author (Year)
        Example: Watson & Crick (1953, p. 737)
        """
        parts = []
        
        # Author last name(s)
        if m.authors:
            author_str = self.get_authors_short(m.authors, max_authors=2)
            parts.append(author_str)
        
        # Year and optional page
        year = m.year or 'n.d.'
        if page:
            parts.append(f"({year}, p. {page})")
        else:
            parts.append(f"({year})")
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_book(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for book.
        
        Pattern: Author (Year, p. X) or Author (Year)
        Example: Klerman (1990, p. 45)
        """
        parts = []
        
        # Author last name(s)
        if m.authors:
            author_str = self.get_authors_short(m.authors, max_authors=2)
            parts.append(author_str)
        
        # Year and optional page
        year = m.year or 'n.d.'
        if page:
            parts.append(f"({year}, p. {page})")
        else:
            parts.append(f"({year})")
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_legal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for legal case.
        
        APA defers to Bluebook for legal citations.
        Pattern: Case Name (Year)
        Example: Roe v. Wade (1973)
        """
        parts = []
        
        # Case name in italics
        if m.case_name:
            parts.append(self.italicize(m.case_name))
        
        # Year
        if m.year:
            parts.append(f"({m.year})")
        
        # Page reference if provided
        if page and m.citation:
            parts.append(f"at {page}")
        
        result = " ".join(parts)
        return result + "." if result else m.raw_source or "Unknown source"
    
    def format_short_interview(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for interview.
        
        Pattern: Interviewee (Year)
        Example: Smith (2020)
        """
        parts = []
        
        if m.interviewee:
            name_parts = m.interviewee.split()
            last_name = name_parts[-1] if name_parts else m.interviewee
            parts.append(last_name)
        
        # Extract year
        year = m.year
        if not year and m.date:
            year_match = re.search(r'\d{4}', m.date)
            if year_match:
                year = year_match.group(0)
        year = year or 'n.d.'
        parts.append(f"({year})")
        
        return " ".join(parts) + "." if parts else "Interview."
    
    def format_short_newspaper(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for newspaper.
        
        Pattern: Author (Year)
        Example: Smith (2024)
        """
        parts = []
        
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=1))
        
        # Extract year from date if needed
        year = m.year
        if not year and m.date:
            year_match = re.search(r'\d{4}', m.date)
            if year_match:
                year = year_match.group(0)
        year = year or 'n.d.'
        parts.append(f"({year})")
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_government(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for government document.
        
        Pattern: Agency (Year, p. X)
        Example: NIH (2020, p. 15)
        """
        parts = []
        
        # Short agency name or abbreviation
        agency = m.agency or "Government"
        # Try to extract acronym if it's a long agency name
        if len(agency.split()) > 3:
            # Use initials as abbreviation
            words = agency.split()
            acronym = ''.join(w[0].upper() for w in words if w[0].isupper() or w[0].isalpha())
            if len(acronym) >= 2:
                agency = acronym
        parts.append(agency)
        
        year = m.year or 'n.d.'
        if page:
            parts.append(f"({year}, p. {page})")
        else:
            parts.append(f"({year})")
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_url(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        APA short form for web page.
        
        Pattern: "Short Title" (Year)
        """
        parts = []
        
        short_title = self._get_short_title(m.title)
        if short_title:
            parts.append(f'"{short_title}"')
        
        year = m.year or 'n.d.'
        parts.append(f"({year})")
        
        return " ".join(parts) + "." if parts else m.url or m.raw_source or "Unknown source"
