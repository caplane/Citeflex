"""
citeflex/formatters/oscola.py

OSCOLA (Oxford University Standard for Citation of Legal Authorities) formatter.

OSCOLA is the standard citation system for UK legal documents and academic writing.

Key characteristics:
- Case names in italics
- Neutral citations preferred (e.g., [2024] UKSC 1)
- No full stops after abbreviations
- Footnote numbers in superscript
- Pinpoint references use paragraph numbers (not pages) for neutral citations
"""

from typing import List, Optional
from .base import BaseFormatter, register_formatter
from ..models import CitationMetadata, CitationType


# UK Court abbreviations for neutral citations
UK_COURTS = {
    'UKSC': 'United Kingdom Supreme Court',
    'UKPC': 'Privy Council',
    'EWCA Civ': 'Court of Appeal (Civil Division)',
    'EWCA Crim': 'Court of Appeal (Criminal Division)',
    'EWHC': 'High Court',
    'UKUT': 'Upper Tribunal',
    'UKFTT': 'First-tier Tribunal',
    'UKEAT': 'Employment Appeal Tribunal',
    'UKHL': 'House of Lords',  # Pre-2009
}

# Law report abbreviations
LAW_REPORTS = {
    'AC': 'Appeal Cases',
    'QB': "Queen's Bench",
    'KB': "King's Bench",
    'Ch': 'Chancery',
    'Fam': 'Family',
    'WLR': 'Weekly Law Reports',
    'All ER': 'All England Law Reports',
    'BCLC': 'Butterworths Company Law Cases',
    'Cr App R': 'Criminal Appeal Reports',
    'CMLR': 'Common Market Law Reports',
}


@register_formatter('OSCOLA')
@register_formatter('Oxford')
@register_formatter('UK Legal')
class OSCOLAFormatter(BaseFormatter):
    """OSCOLA citation formatter for UK legal citations."""
    
    style_name = "OSCOLA"
    
    def format_authors(self, authors: List[str], max_authors: int = 3) -> str:
        """
        Format authors for OSCOLA.
        
        Rules:
        - First name then surname
        - 'and' between last two authors
        - 'and others' for 4+ authors
        """
        if not authors:
            return ""
        
        if len(authors) == 1:
            return authors[0]
        elif len(authors) == 2:
            return f"{authors[0]} and {authors[1]}"
        elif len(authors) == 3:
            return f"{authors[0]}, {authors[1]} and {authors[2]}"
        else:
            return f"{authors[0]} and others"
    
    def format_legal(self, metadata: CitationMetadata) -> str:
        """
        Format legal case in OSCOLA style.
        
        UK Neutral Citation pattern:
        Case Name [Year] Court Number
        
        Examples:
        Donoghue v Stevenson [1932] AC 562
        R v Brown [1994] 1 AC 212
        R (Miller) v Secretary of State for Exiting the EU [2017] UKSC 5
        
        Note: OSCOLA omits full stops and uses neutral citations where available.
        """
        parts = []
        
        # Case name in italics (note: no comma after in OSCOLA)
        if metadata.case_name:
            # OSCOLA uses 'v' not 'v.' 
            case_name = metadata.case_name.replace(' v. ', ' v ')
            parts.append(self.italicize(case_name))
        
        # Neutral citation or law report citation
        if metadata.citation:
            citation = metadata.citation
            # Check if this is a UK neutral citation [Year] Court Number
            if '[' in citation and ']' in citation:
                # Neutral citation - no modification needed
                parts.append(citation)
            else:
                # Traditional law report citation
                parts.append(citation)
        
        # For older cases without neutral citations, add year if not in citation
        if metadata.year and metadata.citation and '[' not in metadata.citation:
            # Year goes in parentheses for traditional citations
            if f"({metadata.year})" not in metadata.citation and metadata.year not in metadata.citation:
                parts.append(f"({metadata.year})")
        
        return " ".join(parts)
    
    def format_journal(self, metadata: CitationMetadata) -> str:
        """
        Format journal article in OSCOLA style.
        
        Pattern:
        Author, 'Title' [Year] or (Year) Volume Journal First Page
        
        Examples:
        HLA Hart, 'Positivism and the Separation of Law and Morals' (1958) 71 Harv L Rev 593
        Joseph Raz, 'The Rule of Law and its Virtue' [1977] LQR 195
        
        Note: [Year] for journals organized by year, (Year) Volume for numbered volumes.
        """
        parts = []
        
        # Author(s) - no full stop after initials in OSCOLA
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in single quotes
        if metadata.title:
            parts.append(f"'{metadata.title}'")
        
        # Year and volume
        if metadata.volume:
            # Numbered volume: (Year) Volume
            if metadata.year:
                parts.append(f"({metadata.year})")
            parts.append(metadata.volume)
        elif metadata.year:
            # Year-organized journal: [Year]
            parts.append(f"[{metadata.year}]")
        
        # Journal name (abbreviated, no full stops)
        if metadata.journal:
            parts.append(metadata.journal)
        
        # First page only
        if metadata.pages:
            first_page = metadata.pages.split('-')[0].split('–')[0].strip()
            parts.append(first_page)
        
        return " ".join(parts)
    
    def format_book(self, metadata: CitationMetadata) -> str:
        """
        Format book in OSCOLA style.
        
        Pattern:
        Author, Title (Edition, Publisher Year)
        
        Example:
        Andrew Burrows, A Restatement of the English Law of Contract (2nd edn, OUP 2020)
        """
        parts = []
        
        # Author(s)
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title))
        
        # Parenthetical with edition, publisher, year
        paren_parts = []
        if metadata.edition:
            paren_parts.append(f"{metadata.edition} edn")
        if metadata.publisher:
            paren_parts.append(metadata.publisher)
        if metadata.year:
            paren_parts.append(metadata.year)
        
        if paren_parts:
            parts.append(f"({', '.join(paren_parts)})")
        
        return " ".join(parts)
    
    def format_interview(self, metadata: CitationMetadata) -> str:
        """
        Format interview in OSCOLA style.
        
        Pattern:
        Interview with Name (Location, Date)
        """
        parts = []
        
        parts.append("Interview with")
        
        if metadata.interviewee:
            parts.append(metadata.interviewee)
        
        # Parenthetical with location and date
        paren_parts = []
        if metadata.location:
            paren_parts.append(metadata.location)
        if metadata.date:
            paren_parts.append(metadata.date)
        elif metadata.year:
            paren_parts.append(metadata.year)
        
        if paren_parts:
            parts.append(f"({', '.join(paren_parts)})")
        
        return " ".join(parts)
    
    def format_newspaper(self, metadata: CitationMetadata) -> str:
        """
        Format newspaper article in OSCOLA style.
        
        Pattern:
        Author, 'Title' Newspaper (Location, Date)
        
        Example:
        Joshua Rozenberg, 'Justice in the Age of AI' The Guardian (London, 15 January 2024)
        """
        parts = []
        
        # Author
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in single quotes
        if metadata.title:
            parts.append(f"'{metadata.title}'")
        
        # Newspaper name in italics
        if metadata.publication:
            parts.append(self.italicize(metadata.publication))
        
        # Parenthetical with location and date
        paren_parts = []
        if metadata.location:
            paren_parts.append(metadata.location)
        if metadata.date:
            paren_parts.append(metadata.date)
        elif metadata.year:
            paren_parts.append(metadata.year)
        
        if paren_parts:
            parts.append(f"({', '.join(paren_parts)})")
        
        # URL for online sources
        if metadata.url:
            parts.append(f"<{metadata.url}> accessed {metadata.access_date or 'date'}")
        
        return " ".join(parts)
    
    def format_government(self, metadata: CitationMetadata) -> str:
        """
        Format government/parliamentary document in OSCOLA style.
        
        Command Papers:
        Title (Cm Number, Year)
        
        Hansard:
        HC Deb/HL Deb Date, vol Volume, col Column
        """
        parts = []
        
        # Title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title))
        
        # Citation or command paper number
        paren_parts = []
        if metadata.citation:
            paren_parts.append(metadata.citation)
        if metadata.year:
            paren_parts.append(metadata.year)
        
        if paren_parts:
            parts.append(f"({', '.join(paren_parts)})")
        
        # URL with access date
        if metadata.url:
            parts.append(f"<{metadata.url}> accessed {metadata.access_date or 'date'}")
        
        return " ".join(parts)
    
    def format_medical(self, metadata: CitationMetadata) -> str:
        """Format medical article (same as journal in OSCOLA)."""
        return self.format_journal(metadata)
    
    def format_url(self, metadata: CitationMetadata) -> str:
        """
        Format web page in OSCOLA style.
        
        Pattern:
        Author, 'Title' (Website, Date) <URL> accessed Date
        
        Example:
        'About Us' (UK Supreme Court) <https://www.supremecourt.uk/about/> accessed 15 January 2024
        """
        parts = []
        
        # Author
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in single quotes
        if metadata.title:
            parts.append(f"'{metadata.title}'")
        
        # Website name
        if metadata.publication:
            parts.append(f"({metadata.publication})")
        
        # URL in angle brackets
        if metadata.url:
            parts.append(f"<{metadata.url}>")
            # Access date
            parts.append(f"accessed {metadata.access_date or 'date'}")
        
        return " ".join(parts)
    
    def format_statute(self, metadata: CitationMetadata) -> str:
        """
        Format UK statute in OSCOLA style.
        
        Pattern:
        Short Title Year
        
        Example:
        Human Rights Act 1998
        Equality Act 2010
        """
        if metadata.title:
            # Statutes should have year in title
            return metadata.title
        return ""
    
    def format_eu_case(self, metadata: CitationMetadata) -> str:
        """
        Format EU case in OSCOLA style.
        
        Pattern:
        Case Number Case Name [Year] ECR Page
        
        Example:
        Case C-6/64 Costa v ENEL [1964] ECR 585
        """
        parts = []
        
        # Case number
        if metadata.citation and 'Case' in metadata.citation:
            parts.append(metadata.citation)
        
        # Case name in italics
        if metadata.case_name:
            parts.append(self.italicize(metadata.case_name))
        
        # ECR citation
        if metadata.year and '[' not in str(metadata.citation or ''):
            parts.append(f"[{metadata.year}]")
        
        if metadata.pages:
            parts.append(f"ECR {metadata.pages}")
        
        return " ".join(parts)
