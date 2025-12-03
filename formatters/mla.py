"""
citeflex/formatters/mla.py

MLA 9th Edition formatter.

MLA style characteristics:
- Author last name first for first author only
- Title in quotes for articles, italics for books
- Container (journal) in italics
- Volume and issue: vol. 45, no. 2
- Year at end
- DOI or URL at end
- No "p." or "pp." for page numbers
"""

from typing import List, Optional
from formatters.base import BaseFormatter, register_formatter
from models import CitationMetadata, CitationType


@register_formatter('MLA')
@register_formatter('MLA 9')
@register_formatter('MLA9')
class MLAFormatter(BaseFormatter):
    """MLA 9th Edition citation formatter."""
    
    style_name = "MLA 9"
    
    def format_authors(self, authors: List[str], max_authors: int = 2) -> str:
        """
        Format authors for MLA.
        
        Rules:
        - First author: Last, First
        - Subsequent authors: First Last
        - 2 authors: Last, First, and First Last
        - 3+ authors: Last, First, et al.
        """
        if not authors:
            return ""
        
        def invert_name(name: str) -> str:
            """Convert 'First Last' to 'Last, First'."""
            parts = name.strip().split()
            if len(parts) >= 2:
                return f"{parts[-1]}, {' '.join(parts[:-1])}"
            return name
        
        if len(authors) == 1:
            return invert_name(authors[0])
        elif len(authors) == 2:
            return f"{invert_name(authors[0])}, and {authors[1]}"
        else:
            # 3+ authors: use et al.
            return f"{invert_name(authors[0])}, et al."
    
    def format_journal(self, metadata: CitationMetadata) -> str:
        """
        Format journal article in MLA style.
        
        Pattern:
        Last, First. "Article Title." Journal Name, vol. X, no. Y, Year, pp. X-Y. DOI/URL.
        """
        parts = []
        
        # Authors
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors))
        
        # Title in quotes
        if metadata.title:
            parts.append(f'"{metadata.title}."')
        
        # Container (journal) in italics
        container_parts = []
        if metadata.journal:
            container_parts.append(self.italicize(metadata.journal))
        
        # Volume and issue
        if metadata.volume:
            container_parts.append(f"vol. {metadata.volume}")
        if metadata.issue:
            container_parts.append(f"no. {metadata.issue}")
        
        # Year
        if metadata.year:
            container_parts.append(metadata.year)
        
        # Pages (no pp. prefix in MLA 9)
        if metadata.pages:
            container_parts.append(f"pp. {metadata.pages}")
        
        if container_parts:
            parts.append(", ".join(container_parts) + ".")
        
        # DOI or URL
        if metadata.doi:
            doi = metadata.doi
            if not doi.startswith('http'):
                doi = f"https://doi.org/{doi}"
            parts.append(doi + ".")
        elif metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    def format_book(self, metadata: CitationMetadata) -> str:
        """
        Format book in MLA style.
        
        Pattern:
        Last, First. Title of Book. Publisher, Year.
        """
        parts = []
        
        # Authors
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors))
        
        # Title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title) + ".")
        
        # Publisher
        if metadata.publisher:
            pub_part = metadata.publisher
            if metadata.year:
                pub_part += f", {metadata.year}"
            parts.append(pub_part + ".")
        elif metadata.year:
            parts.append(metadata.year + ".")
        
        return " ".join(parts)
    
    def format_legal(self, metadata: CitationMetadata) -> str:
        """
        Format legal case in MLA style.
        
        MLA defers to Bluebook for legal citations, but uses italics for case names.
        Pattern: Case Name, Citation (Court Year).
        """
        parts = []
        
        # Case name in italics
        if metadata.case_name:
            parts.append(self.italicize(metadata.case_name) + ",")
        
        # Citation
        if metadata.citation:
            parts.append(metadata.citation)
        
        # Court and year
        if metadata.court or metadata.year:
            court_year = []
            if metadata.court:
                court_year.append(metadata.court)
            if metadata.year:
                court_year.append(str(metadata.year))
            parts.append(f"({' '.join(court_year)}).")
        else:
            # Add period to last part
            if parts:
                parts[-1] = parts[-1].rstrip(',') + "."
        
        return " ".join(parts)
    
    def format_interview(self, metadata: CitationMetadata) -> str:
        """
        Format interview in MLA style.
        
        Pattern:
        Last, First. Interview. Conducted by Interviewer Name, Day Month Year.
        """
        parts = []
        
        # Interviewee
        if metadata.interviewee:
            name_parts = metadata.interviewee.split()
            if len(name_parts) >= 2:
                parts.append(f"{name_parts[-1]}, {' '.join(name_parts[:-1])}.")
            else:
                parts.append(metadata.interviewee + ".")
        
        # Interview type
        parts.append("Interview.")
        
        # Conducted by
        if metadata.interviewer:
            if metadata.interviewer.lower() != 'author':
                parts.append(f"Conducted by {metadata.interviewer},")
            else:
                parts.append("Conducted by the author,")
        
        # Date
        if metadata.date:
            parts.append(metadata.date + ".")
        elif metadata.year:
            parts.append(metadata.year + ".")
        
        return " ".join(parts)
    
    def format_newspaper(self, metadata: CitationMetadata) -> str:
        """
        Format newspaper article in MLA style.
        
        Pattern:
        Last, First. "Article Title." Newspaper Name, Day Month Year, URL.
        """
        parts = []
        
        # Authors
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors))
        
        # Title in quotes
        if metadata.title:
            parts.append(f'"{metadata.title}."')
        
        # Newspaper name in italics
        if metadata.publication:
            parts.append(self.italicize(metadata.publication) + ",")
        
        # Date
        if metadata.date:
            parts.append(metadata.date + ",")
        elif metadata.year:
            parts.append(metadata.year + ",")
        
        # URL
        if metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    def format_government(self, metadata: CitationMetadata) -> str:
        """
        Format government document in MLA style.
        
        Pattern:
        Agency Name. Title of Document. Publisher, Year, URL.
        """
        parts = []
        
        # Agency
        if metadata.agency:
            parts.append(metadata.agency + ".")
        
        # Title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title) + ".")
        
        # Year
        if metadata.year:
            parts.append(metadata.year + ",")
        
        # URL
        if metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    def format_medical(self, metadata: CitationMetadata) -> str:
        """Format medical article (same as journal in MLA)."""
        return self.format_journal(metadata)
    
    def format_url(self, metadata: CitationMetadata) -> str:
        """
        Format web page in MLA style.
        
        Pattern:
        "Page Title." Website Name, Publisher, Day Month Year, URL.
        """
        parts = []
        
        # Title in quotes
        if metadata.title:
            parts.append(f'"{metadata.title}."')
        
        # Website/publication
        if metadata.publication:
            parts.append(self.italicize(metadata.publication) + ",")
        
        # Date
        if metadata.date:
            parts.append(metadata.date + ",")
        elif metadata.year:
            parts.append(metadata.year + ",")
        
        # URL
        if metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    # =========================================================================
    # SHORT FORM METHODS - MLA style
    # =========================================================================
    
    def format_short_journal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for journal article.
        
        Pattern: Author page
        Example: Watson and Crick 737
        
        MLA uses parenthetical citations with author and page only.
        """
        parts = []
        
        # Author last name(s)
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=2))
        
        # Page (no "p." in MLA)
        if page:
            parts.append(page)
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_book(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for book.
        
        Pattern: Author page
        Example: Klerman 45
        """
        parts = []
        
        # Author last name(s)
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=2))
        
        # Page (no "p." in MLA)
        if page:
            parts.append(page)
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_legal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for legal case.
        
        Pattern: Case Name page
        Example: Roe v. Wade 153
        """
        parts = []
        
        # Case name in italics
        if m.case_name:
            parts.append(self.italicize(m.case_name))
        
        # Page
        if page:
            parts.append(page)
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_interview(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for interview.
        
        Pattern: Interviewee
        Example: Smith
        """
        if m.interviewee:
            name_parts = m.interviewee.split()
            last_name = name_parts[-1] if name_parts else m.interviewee
            return f"{last_name}."
        
        return "Interview."
    
    def format_short_newspaper(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for newspaper.
        
        Pattern: Author
        Example: Smith
        """
        if m.authors:
            return self.get_authors_short(m.authors, max_authors=1) + "."
        
        # If no author, use short title
        short_title = self._get_short_title(m.title)
        if short_title:
            return f'"{short_title}."'
        
        return m.raw_source or "Unknown source"
    
    def format_short_government(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for government document.
        
        Pattern: Agency or Short Title page
        Example: NIH 15
        """
        parts = []
        
        # Use agency if available, otherwise short title
        if m.agency:
            # Try to create abbreviation for long agency names
            agency = m.agency
            if len(agency.split()) > 3:
                words = agency.split()
                acronym = ''.join(w[0].upper() for w in words if w[0].isupper() or w[0].isalpha())
                if len(acronym) >= 2:
                    agency = acronym
            parts.append(agency)
        else:
            short_title = self._get_short_title(m.title)
            if short_title:
                parts.append(self.italicize(short_title))
        
        if page:
            parts.append(page)
        
        return " ".join(parts) + "." if parts else m.raw_source or "Unknown source"
    
    def format_short_url(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        MLA short form for web page.
        
        Pattern: "Short Title"
        """
        short_title = self._get_short_title(m.title)
        if short_title:
            return f'"{short_title}."'
        
        return m.url or m.raw_source or "Unknown source"
