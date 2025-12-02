"""
citeflex/formatters/apa.py

APA 7th Edition citation formatter.
Common in psychology, education, and social sciences.

Uses <i> tags for italics (Word-compatible).
"""

import re
from .base import BaseFormatter, register_formatter
from ..models import CitationMetadata, CitationStyle


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
            paren_parts.append(m.year)
        
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
