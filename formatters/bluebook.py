"""
citeflex/formatters/bluebook.py

Bluebook (21st Edition) legal citation formatter.

The Bluebook is the standard citation system for US legal documents.

Key characteristics:
- Case names in italics (or underlined in court documents)
- Specific reporter abbreviations
- Pinpoint citations with "at" for page references
- Signals (e.g., See, Cf., Compare)
- Short forms for subsequent citations
"""

from typing import List, Optional
from formatters.base import BaseFormatter, register_formatter
from models import CitationMetadata, CitationType


# Common court abbreviations
COURT_ABBREVIATIONS = {
    'Supreme Court': 'S. Ct.',
    'Supreme Court of the United States': '',  # No court designation needed for U.S. Reports
    'United States Supreme Court': '',
    'SCOTUS': '',
    'Court of Appeals': 'Cir.',
    'District Court': 'D.',
    'Bankruptcy Court': 'Bankr.',
    # State courts
    'Supreme Court of Virginia': 'Va.',
    'Virginia Supreme Court': 'Va.',
    'Court of Appeals of Virginia': 'Va. Ct. App.',
    'Supreme Court of California': 'Cal.',
    'Supreme Court of New York': 'N.Y.',
    'Supreme Court of Texas': 'Tex.',
}

# Reporter abbreviations
REPORTER_ABBREVIATIONS = {
    'United States Reports': 'U.S.',
    'Supreme Court Reporter': 'S. Ct.',
    'Lawyers Edition': 'L. Ed.',
    'Federal Reporter': 'F.',
    'Federal Reporter Second': 'F.2d',
    'Federal Reporter Third': 'F.3d',
    'Federal Supplement': 'F. Supp.',
    'Federal Supplement Second': 'F. Supp. 2d',
    'Federal Supplement Third': 'F. Supp. 3d',
    'Virginia Reports': 'Va.',
    'Southeastern Reporter': 'S.E.',
    'Southeastern Reporter Second': 'S.E.2d',
}


@register_formatter('Bluebook')
@register_formatter('BLUEBOOK')
@register_formatter('Blue Book')
class BluebookFormatter(BaseFormatter):
    """Bluebook 21st Edition citation formatter."""
    
    style_name = "Bluebook"
    
    def format_authors(self, authors: List[str], max_authors: int = 1) -> str:
        """
        Format authors for Bluebook (used in law review articles).
        
        Rules:
        - Full name, no inversion
        - Use ampersand for multiple authors
        - "et al." for 3+ authors
        """
        if not authors:
            return ""
        
        if len(authors) == 1:
            return authors[0]
        elif len(authors) == 2:
            return f"{authors[0]} & {authors[1]}"
        else:
            return f"{authors[0]} et al."
    
    def format_legal(self, metadata: CitationMetadata) -> str:
        """
        Format legal case in Bluebook style.
        
        Full citation pattern:
        Case Name, Volume Reporter Page (Court Year).
        
        Examples:
        Brown v. Board of Education, 347 U.S. 483 (1954).
        Miranda v. Arizona, 384 U.S. 436 (1966).
        Loving v. Virginia, 388 U.S. 1 (1967).
        """
        parts = []
        
        # Case name in italics
        if metadata.case_name:
            parts.append(self.italicize(metadata.case_name) + ",")
        
        # Citation (volume, reporter, page)
        if metadata.citation:
            parts.append(metadata.citation)
        
        # Parenthetical with court and year
        # Note: For U.S. Reports, no court designation is needed
        paren_parts = []
        
        # Check if this is a Supreme Court case (has U.S. in citation)
        is_scotus = metadata.citation and 'U.S.' in metadata.citation
        
        if metadata.court and not is_scotus:
            # Abbreviate court name
            court = metadata.court
            for full, abbrev in COURT_ABBREVIATIONS.items():
                if full.lower() in court.lower():
                    court = abbrev
                    break
            if court:
                paren_parts.append(court)
        
        if metadata.year:
            paren_parts.append(str(metadata.year))
        
        if paren_parts:
            parts.append(f"({' '.join(paren_parts)}).")
        else:
            # Add period to citation
            if parts:
                parts[-1] = parts[-1] + "."
        
        return " ".join(parts)
    
    def format_journal(self, metadata: CitationMetadata) -> str:
        """
        Format law review/journal article in Bluebook style.
        
        Pattern:
        Author, Article Title, Volume Journal Page (Year).
        
        Example:
        William J. Novak, The Myth of the "Weak" American State, 
        113 Am. Hist. Rev. 752 (2008).
        """
        parts = []
        
        # Author(s)
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Article title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title) + ",")
        
        # Volume
        if metadata.volume:
            parts.append(metadata.volume)
        
        # Journal name (abbreviated in Bluebook)
        if metadata.journal:
            # Use journal name as-is (abbreviation would require lookup table)
            parts.append(metadata.journal)
        
        # Starting page
        if metadata.pages:
            # Just first page for Bluebook
            first_page = metadata.pages.split('-')[0].split('–')[0].strip()
            parts.append(first_page)
        
        # Year in parentheses
        if metadata.year:
            parts.append(f"({metadata.year}).")
        else:
            if parts:
                parts[-1] = parts[-1] + "."
        
        return " ".join(parts)
    
    def format_book(self, metadata: CitationMetadata) -> str:
        """
        Format book in Bluebook style.
        
        Pattern:
        Author, Title (Edition ed. Year).
        
        Example:
        Bryan A. Garner, The Bluebook: A Uniform System of Citation (21st ed. 2020).
        """
        parts = []
        
        # Author(s)
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in small caps (rendered as italics here)
        if metadata.title:
            parts.append(self.italicize(metadata.title))
        
        # Parenthetical with edition and year
        paren_parts = []
        if metadata.edition:
            paren_parts.append(f"{metadata.edition} ed.")
        if metadata.year:
            paren_parts.append(str(metadata.year))
        
        if paren_parts:
            parts.append(f"({' '.join(paren_parts)}).")
        else:
            parts[-1] = parts[-1] + "."
        
        return " ".join(parts)
    
    def format_interview(self, metadata: CitationMetadata) -> str:
        """
        Format interview in Bluebook style.
        
        Interviews are typically cited as unpublished sources.
        Pattern:
        Interview with [Name], [Title] (Date).
        """
        parts = []
        
        parts.append("Interview with")
        
        if metadata.interviewee:
            interviewee = metadata.interviewee
            if metadata.title:
                interviewee += f", {metadata.title}"
            parts.append(interviewee)
        
        # Location and date
        paren_parts = []
        if metadata.location:
            paren_parts.append(metadata.location)
        if metadata.date:
            paren_parts.append(metadata.date)
        elif metadata.year:
            paren_parts.append(str(metadata.year))
        
        if paren_parts:
            parts.append(f"({', '.join(paren_parts)}).")
        else:
            parts[-1] = parts[-1] + "."
        
        return " ".join(parts)
    
    def format_newspaper(self, metadata: CitationMetadata) -> str:
        """
        Format newspaper article in Bluebook style.
        
        Pattern:
        Author, Title, Newspaper, Date, at Page.
        
        Example:
        Adam Liptak, Supreme Court to Hear Case on Voting Rights, 
        N.Y. Times, Jan. 15, 2024, at A1.
        """
        parts = []
        
        # Author
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title) + ",")
        
        # Newspaper name (abbreviated)
        if metadata.publication:
            # Common abbreviations
            pub = metadata.publication
            abbreviations = {
                'The New York Times': 'N.Y. Times',
                'New York Times': 'N.Y. Times',
                'The Washington Post': 'Wash. Post',
                'Washington Post': 'Wash. Post',
                'The Wall Street Journal': 'Wall St. J.',
                'Wall Street Journal': 'Wall St. J.',
                'Los Angeles Times': 'L.A. Times',
                'The Guardian': 'Guardian',
            }
            for full, abbrev in abbreviations.items():
                if full.lower() == pub.lower():
                    pub = abbrev
                    break
            parts.append(pub + ",")
        
        # Date
        if metadata.date:
            parts.append(metadata.date + ".")
        elif metadata.year:
            parts.append(metadata.year + ".")
        
        # URL for online sources
        if metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    def format_government(self, metadata: CitationMetadata) -> str:
        """
        Format government document in Bluebook style.
        
        Pattern varies by document type. For regulations:
        Title, Volume Fed. Reg. Page (Date).
        """
        parts = []
        
        # Title
        if metadata.title:
            parts.append(metadata.title + ",")
        
        # Federal Register citation if available
        if metadata.citation:
            parts.append(metadata.citation)
        
        # Agency
        if metadata.agency and not metadata.citation:
            parts.append(metadata.agency)
        
        # Date/year
        if metadata.date:
            parts.append(f"({metadata.date}).")
        elif metadata.year:
            parts.append(f"({metadata.year}).")
        else:
            if parts:
                parts[-1] = parts[-1].rstrip(',') + "."
        
        # URL
        if metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    def format_medical(self, metadata: CitationMetadata) -> str:
        """Format medical article (same as journal in Bluebook)."""
        return self.format_journal(metadata)
    
    def format_url(self, metadata: CitationMetadata) -> str:
        """
        Format web page in Bluebook style.
        
        Pattern:
        Author, Title, Website (Date), URL.
        """
        parts = []
        
        # Author
        if metadata.authors:
            parts.append(self.format_authors(metadata.authors) + ",")
        
        # Title in italics
        if metadata.title:
            parts.append(self.italicize(metadata.title) + ",")
        
        # Website
        if metadata.publication:
            parts.append(metadata.publication)
        
        # Date
        if metadata.date:
            parts.append(f"({metadata.date}),")
        elif metadata.year:
            parts.append(f"({metadata.year}),")
        
        # URL
        if metadata.url:
            parts.append(metadata.url + ".")
        
        return " ".join(parts)
    
    def format_statute(self, metadata: CitationMetadata) -> str:
        """
        Format statute in Bluebook style.
        
        Pattern:
        Name of Act, Title U.S.C. § Section (Year).
        
        Example:
        Civil Rights Act of 1964, 42 U.S.C. § 2000e (2018).
        """
        parts = []
        
        # Statute name
        if metadata.title:
            parts.append(metadata.title + ",")
        
        # Citation
        if metadata.citation:
            parts.append(metadata.citation)
        
        # Year
        if metadata.year:
            parts.append(f"({metadata.year}).")
        else:
            if parts:
                parts[-1] = parts[-1] + "."
        
        return " ".join(parts)
    
    # =========================================================================
    # SHORT FORM METHODS - Bluebook style
    # =========================================================================
    
    def format_short_legal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for legal case.
        
        Pattern: Case Name, Volume Reporter at Page.
        Example: Loving, 388 U.S. at 12.
        
        For cases without pinpoint: Case Name, Volume Reporter.
        Example: Loving, 388 U.S.
        """
        parts = []
        
        # Short case name (first party only) in italics
        if m.case_name:
            case_name = m.case_name
            # Extract first party name for short form
            if ' v. ' in case_name:
                short_name = case_name.split(' v. ')[0]
            elif ' v ' in case_name:
                short_name = case_name.split(' v ')[0]
            else:
                short_name = case_name
            parts.append(self.italicize(short_name) + ",")
        
        # Citation with "at" for pinpoint
        if m.citation:
            if page:
                parts.append(f"{m.citation} at {page}.")
            else:
                parts.append(f"{m.citation}.")
        else:
            if parts:
                parts[-1] = parts[-1].rstrip(',') + "."
        
        return " ".join(parts)
    
    def format_short_journal(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for journal article.
        
        Pattern: Author, supra, at page.
        Example: Novak, supra, at 755.
        """
        parts = []
        
        # Author last name
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=1) + ",")
        
        # Supra
        parts.append("supra")
        
        # Page with "at"
        if page:
            parts.append(f"at {page}")
        
        result = ", ".join(parts)
        return result + "." if not result.endswith('.') else result
    
    def format_short_book(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for book.
        
        Pattern: Author, supra, at page.
        Example: Garner, supra, at 45.
        """
        parts = []
        
        # Author last name
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=1) + ",")
        
        # Supra
        parts.append("supra")
        
        # Page with "at"
        if page:
            parts.append(f"at {page}")
        
        result = ", ".join(parts)
        return result + "." if not result.endswith('.') else result
    
    def format_short_interview(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for interview.
        
        Pattern: Name Interview, supra.
        """
        if m.interviewee:
            name_parts = m.interviewee.split()
            last_name = name_parts[-1] if name_parts else m.interviewee
            return f"{last_name} Interview, supra."
        
        return "Interview, supra."
    
    def format_short_newspaper(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for newspaper.
        
        Pattern: Author, supra.
        """
        parts = []
        
        if m.authors:
            parts.append(self.get_authors_short(m.authors, max_authors=1) + ",")
        
        parts.append("supra")
        
        if page:
            parts.append(f"at {page}")
        
        result = ", ".join(parts)
        return result + "." if not result.endswith('.') else result
    
    def format_short_government(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for government document.
        
        Pattern: Short Title, supra, at page.
        """
        parts = []
        
        short_title = self._get_short_title(m.title)
        if short_title:
            parts.append(short_title + ",")
        
        parts.append("supra")
        
        if page:
            parts.append(f"at {page}")
        
        result = ", ".join(parts)
        return result + "." if not result.endswith('.') else result
    
    def format_short_url(self, m: CitationMetadata, page: Optional[str] = None) -> str:
        """
        Bluebook short form for web page.
        
        Pattern: Short Title, supra.
        """
        short_title = self._get_short_title(m.title)
        if short_title:
            return f"{short_title}, supra."
        
        return "supra."
