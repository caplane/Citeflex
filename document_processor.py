"""
citeflex/document_processor.py

Word document processing using direct XML manipulation.

Ported from the monolithic citation_manager.py to preserve:
- Proper endnote/footnote reference elements
- Italic formatting via <i> tags
- Clickable hyperlinks for URLs

This approach extracts the docx as a zip, manipulates the XML directly,
and repackages it - giving full control over Word's internal structure.
"""

import os
import re
import html
import zipfile
import tempfile
import shutil
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from io import BytesIO

from router import get_citation
from formatters.base import BaseFormatter, get_formatter


# =============================================================================
# IBID DETECTION AND HANDLING
# =============================================================================

# Pattern to match ibid variations
# Matches: ibid, ibid., Ibid, Ibid., IBID, IBID., ibidem, etc.
# Optionally followed by comma/period and page number
IBID_PATTERN = re.compile(
    r'^(?:ibid\.?|ibidem\.?)(?:\s*[,.]?\s*(\d+[\-–]?\d*)?)?\.?$',
    re.IGNORECASE
)


def is_ibid(text: str) -> bool:
    """
    Check if the text is an ibid reference.
    
    Recognizes variations:
    - ibid
    - ibid.
    - Ibid
    - Ibid.
    - IBID
    - ibidem
    - ibid, 45
    - ibid., 45
    - ibid. 123-125
    
    Args:
        text: The citation text to check
        
    Returns:
        True if this is an ibid reference
    """
    if not text:
        return False
    
    cleaned = text.strip()
    return IBID_PATTERN.match(cleaned) is not None


def extract_ibid_page(text: str) -> Optional[str]:
    """
    Extract page number from an ibid reference.
    
    Examples:
    - "ibid, 45" → "45"
    - "ibid., 123-125" → "123-125"
    - "ibid." → None
    - "ibid" → None
    
    Args:
        text: The ibid text
        
    Returns:
        Page number string if present, None otherwise
    """
    if not text:
        return None
    
    cleaned = text.strip()
    match = IBID_PATTERN.match(cleaned)
    
    if match and match.group(1):
        return match.group(1).strip()
    
    return None


def normalize_url(url: str) -> str:
    """
    Normalize a URL for comparison purposes.
    
    Removes trailing slashes, converts to lowercase, strips whitespace,
    and removes common tracking parameters to ensure matching URLs
    are recognized as the same source.
    
    Args:
        url: The URL to normalize
        
    Returns:
        Normalized URL string
    """
    if not url:
        return ""
    
    # Strip whitespace and convert to lowercase
    normalized = url.strip().lower()
    
    # Remove trailing slashes
    normalized = normalized.rstrip('/')
    
    # Remove common tracking parameters (utm_, etc.)
    # Simple approach: remove everything after ? for comparison
    # This may be too aggressive for some URLs, but works for most cases
    if '?' in normalized:
        base_url = normalized.split('?')[0]
        # Keep the base URL without query params for comparison
        normalized = base_url
    
    return normalized


def urls_match(url1: Optional[str], url2: Optional[str]) -> bool:
    """
    Check if two URLs refer to the same source.
    
    Uses normalized comparison to handle minor variations like
    trailing slashes, case differences, and tracking parameters.
    
    Args:
        url1: First URL
        url2: Second URL
        
    Returns:
        True if both URLs are non-empty and match after normalization
    """
    if not url1 or not url2:
        return False
    
    return normalize_url(url1) == normalize_url(url2)


# =============================================================================
# SOURCE MATCHING FOR SHORT FORM DETECTION
# =============================================================================

def generate_source_key(metadata: Any) -> Optional[str]:
    """
    Generate a unique key to identify a source for short form matching.
    
    Two citations with the same source key refer to the same work.
    
    Priority order for matching:
    1. DOI (most reliable)
    2. URL (for web sources)
    3. Case name + citation (for legal)
    4. Title + first author (for books/articles)
    
    Args:
        metadata: CitationMetadata object
        
    Returns:
        String key for source matching, or None if no key can be generated
    """
    if not metadata:
        return None
    
    # Priority 1: DOI
    doi = getattr(metadata, 'doi', None)
    if doi:
        return f"doi:{doi.lower().strip()}"
    
    # Priority 2: URL (normalized)
    url = getattr(metadata, 'url', None)
    if url:
        return f"url:{normalize_url(url)}"
    
    # Priority 3: Legal case (case name + citation)
    case_name = getattr(metadata, 'case_name', None)
    citation = getattr(metadata, 'citation', None)
    if case_name and citation:
        return f"legal:{case_name.lower().strip()}|{citation.lower().strip()}"
    
    # Priority 4: Title + first author
    title = getattr(metadata, 'title', None)
    authors = getattr(metadata, 'authors', None)
    if title:
        key = f"title:{title.lower().strip()}"
        if authors and len(authors) > 0:
            key += f"|author:{authors[0].lower().strip()}"
        return key
    
    # Priority 5: Just case name for legal without citation
    if case_name:
        return f"case:{case_name.lower().strip()}"
    
    return None


def sources_match(metadata1: Any, metadata2: Any) -> bool:
    """
    Check if two citation metadata objects refer to the same source.
    
    Args:
        metadata1: First CitationMetadata
        metadata2: Second CitationMetadata
        
    Returns:
        True if both refer to the same work
    """
    key1 = generate_source_key(metadata1)
    key2 = generate_source_key(metadata2)
    
    if key1 is None or key2 is None:
        return False
    
    return key1 == key2


@dataclass
class ProcessedCitation:
    """Result of processing a single citation."""
    original: str
    formatted: str
    metadata: Any
    url: Optional[str]
    success: bool
    error: Optional[str] = None
    citation_form: str = "full"  # "full", "ibid", or "short"


@dataclass 
class CitationHistoryEntry:
    """Entry in the citation history for tracking previously cited sources."""
    metadata: Any
    formatted: str
    source_key: Optional[str]
    note_number: int


class CitationHistory:
    """
    Tracks all citations seen in a document for ibid and short form handling.
    
    Maintains:
    - Previous citation (for ibid detection)
    - All cited sources (for short form detection)
    """
    
    def __init__(self):
        self.previous: Optional[CitationHistoryEntry] = None
        self.all_sources: Dict[str, CitationHistoryEntry] = {}  # source_key -> first occurrence
        self.note_counter: int = 0
    
    def add(self, metadata: Any, formatted: str) -> None:
        """
        Add a citation to the history.
        
        Args:
            metadata: Citation metadata
            formatted: Formatted citation string
        """
        self.note_counter += 1
        source_key = generate_source_key(metadata)
        
        entry = CitationHistoryEntry(
            metadata=metadata,
            formatted=formatted,
            source_key=source_key,
            note_number=self.note_counter
        )
        
        # Update previous
        self.previous = entry
        
        # Add to all_sources if this is the first time we've seen this source
        if source_key and source_key not in self.all_sources:
            self.all_sources[source_key] = entry
    
    def is_same_as_previous(self, metadata: Any) -> bool:
        """
        Check if the given metadata matches the immediately previous citation.
        
        Args:
            metadata: Citation metadata to check
            
        Returns:
            True if this is the same source as the previous citation
        """
        if self.previous is None:
            return False
        
        return sources_match(metadata, self.previous.metadata)
    
    def has_been_cited_before(self, metadata: Any) -> bool:
        """
        Check if this source has been cited previously in the document.
        
        Args:
            metadata: Citation metadata to check
            
        Returns:
            True if this source has been cited before (not counting current)
        """
        source_key = generate_source_key(metadata)
        if source_key is None:
            return False
        
        return source_key in self.all_sources
    
    def get_previous_metadata(self) -> Optional[Any]:
        """Get the metadata of the previous citation."""
        if self.previous:
            return self.previous.metadata
        return None
    
    def get_previous_url(self) -> Optional[str]:
        """Get the URL of the previous citation."""
        if self.previous and self.previous.metadata:
            return getattr(self.previous.metadata, 'url', None)
        return None


class WordDocumentProcessor:
    """
    Processes Word documents to read and write endnotes/footnotes.
    Preserves the main document body while allowing citation fixes.
    
    Uses direct XML manipulation for precise control over Word's structure.
    """
    
    NS = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'xml': 'http://www.w3.org/XML/1998/namespace'
    }
    
    def __init__(self, file_path_or_buffer):
        """
        Initialize with a file path or file-like object (BytesIO).
        """
        self.temp_dir = tempfile.mkdtemp()
        self.original_path = None
        
        # Handle both file paths and file-like objects
        if hasattr(file_path_or_buffer, 'read'):
            # It's a file-like object (e.g., from upload)
            with zipfile.ZipFile(file_path_or_buffer, 'r') as z:
                z.extractall(self.temp_dir)
        else:
            # It's a file path
            self.original_path = file_path_or_buffer
            with zipfile.ZipFile(file_path_or_buffer, 'r') as z:
                z.extractall(self.temp_dir)
    
    def get_endnotes(self) -> List[Dict[str, str]]:
        """
        Extract all endnotes from the document.
        
        Returns:
            List of dicts: [{'id': '1', 'text': 'citation text'}, ...]
        """
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        if not os.path.exists(endnotes_path):
            return []
        
        try:
            tree = ET.parse(endnotes_path)
            root = tree.getroot()
            notes = []
            
            for endnote in root.findall('.//w:endnote', self.NS):
                note_id = endnote.get(f"{{{self.NS['w']}}}id")
                
                # Skip system endnotes (id 0 and -1)
                try:
                    if int(note_id) < 1:
                        continue
                except (ValueError, TypeError):
                    continue
                
                # Extract all text from this endnote
                text_parts = []
                for t in endnote.findall('.//w:t', self.NS):
                    if t.text:
                        text_parts.append(t.text)
                
                full_text = "".join(text_parts).strip()
                if full_text:
                    notes.append({'id': note_id, 'text': full_text})
            
            return notes
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error reading endnotes: {e}")
            return []
    
    def get_footnotes(self) -> List[Dict[str, str]]:
        """
        Extract all footnotes from the document.
        
        Returns:
            List of dicts: [{'id': '1', 'text': 'citation text'}, ...]
        """
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        if not os.path.exists(footnotes_path):
            return []
        
        try:
            tree = ET.parse(footnotes_path)
            root = tree.getroot()
            notes = []
            
            for footnote in root.findall('.//w:footnote', self.NS):
                note_id = footnote.get(f"{{{self.NS['w']}}}id")
                
                # Skip system footnotes (id 0 and -1)
                try:
                    if int(note_id) < 1:
                        continue
                except (ValueError, TypeError):
                    continue
                
                # Extract all text
                text_parts = []
                for t in footnote.findall('.//w:t', self.NS):
                    if t.text:
                        text_parts.append(t.text)
                
                full_text = "".join(text_parts).strip()
                if full_text:
                    notes.append({'id': note_id, 'text': full_text})
            
            return notes
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error reading footnotes: {e}")
            return []
    
    def write_endnote(self, note_id: str, new_content: str) -> bool:
        """
        Replace an endnote's content with new formatted citation.
        Handles <i> tags for italics using regex (no BeautifulSoup needed).
        PRESERVES the endnoteRef element for proper numbering and linking.
        
        Args:
            note_id: The endnote ID to update
            new_content: New citation text (may contain <i> tags for italics)
            
        Returns:
            bool: True if successful
        """
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        if not os.path.exists(endnotes_path):
            return False
        
        try:
            # Register namespace to preserve it
            ET.register_namespace('w', self.NS['w'])
            ET.register_namespace('xml', self.NS['xml'])
            
            tree = ET.parse(endnotes_path)
            root = tree.getroot()
            
            # Find the target endnote
            target = None
            for endnote in root.findall('.//w:endnote', self.NS):
                if endnote.get(f"{{{self.NS['w']}}}id") == str(note_id):
                    target = endnote
                    break
            
            if target is None:
                return False
            
            # Find or create paragraph
            para = target.find('.//w:p', self.NS)
            if para is None:
                para = ET.SubElement(target, f"{{{self.NS['w']}}}p")
            else:
                # FIXED: Preserve paragraph properties AND endnoteRef run
                preserved_pPr = None
                preserved_endnoteRef_run = None
                
                for child in list(para):
                    tag = child.tag.replace(f"{{{self.NS['w']}}}", "")
                    
                    # Preserve paragraph properties
                    if tag == 'pPr':
                        preserved_pPr = child
                        continue
                    
                    # Check if this run contains endnoteRef
                    if tag == 'r':
                        endnote_ref = child.find(f".//{{{self.NS['w']}}}endnoteRef")
                        if endnote_ref is not None:
                            preserved_endnoteRef_run = child
                            continue
                    
                    # Remove all other children
                    para.remove(child)
                
                # If no endnoteRef run was found, create one
                if preserved_endnoteRef_run is None:
                    ref_run = ET.Element(f"{{{self.NS['w']}}}r")
                    rPr = ET.SubElement(ref_run, f"{{{self.NS['w']}}}rPr")
                    rStyle = ET.SubElement(rPr, f"{{{self.NS['w']}}}rStyle")
                    rStyle.set(f"{{{self.NS['w']}}}val", "EndnoteReference")
                    ET.SubElement(ref_run, f"{{{self.NS['w']}}}endnoteRef")
                    
                    # Insert after pPr if it exists, otherwise at beginning
                    if preserved_pPr is not None:
                        idx = list(para).index(preserved_pPr) + 1
                        para.insert(idx, ref_run)
                    else:
                        para.insert(0, ref_run)
            
            # Parse content using regex to handle <i> tags (no BeautifulSoup)
            parts = re.split(r'(<i>.*?</i>)', html.unescape(new_content))
            
            for part in parts:
                if not part:
                    continue
                    
                run = ET.SubElement(para, f"{{{self.NS['w']}}}r")
                
                # Check if this is italic text
                italic_match = re.match(r'<i>(.*?)</i>', part)
                if italic_match:
                    rPr = ET.SubElement(run, f"{{{self.NS['w']}}}rPr")
                    ET.SubElement(rPr, f"{{{self.NS['w']}}}i")
                    text_content = italic_match.group(1)
                else:
                    text_content = part
                
                t = ET.SubElement(run, f"{{{self.NS['w']}}}t")
                t.text = text_content
                t.set(f"{{{self.NS['xml']}}}space", "preserve")
            
            tree.write(endnotes_path, encoding='UTF-8', xml_declaration=True)
            return True
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error writing endnote: {e}")
            return False
    
    def write_footnote(self, note_id: str, new_content: str) -> bool:
        """
        Replace a footnote's content with new formatted citation.
        Handles <i> tags for italics using regex (no BeautifulSoup needed).
        PRESERVES the footnoteRef element for proper numbering and linking.
        """
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        if not os.path.exists(footnotes_path):
            return False
        
        try:
            ET.register_namespace('w', self.NS['w'])
            ET.register_namespace('xml', self.NS['xml'])
            
            tree = ET.parse(footnotes_path)
            root = tree.getroot()
            
            target = None
            for footnote in root.findall('.//w:footnote', self.NS):
                if footnote.get(f"{{{self.NS['w']}}}id") == str(note_id):
                    target = footnote
                    break
            
            if target is None:
                return False
            
            para = target.find('.//w:p', self.NS)
            if para is None:
                para = ET.SubElement(target, f"{{{self.NS['w']}}}p")
            else:
                # FIXED: Preserve paragraph properties AND footnoteRef run
                preserved_pPr = None
                preserved_footnoteRef_run = None
                
                for child in list(para):
                    tag = child.tag.replace(f"{{{self.NS['w']}}}", "")
                    
                    # Preserve paragraph properties
                    if tag == 'pPr':
                        preserved_pPr = child
                        continue
                    
                    # Check if this run contains footnoteRef
                    if tag == 'r':
                        footnote_ref = child.find(f".//{{{self.NS['w']}}}footnoteRef")
                        if footnote_ref is not None:
                            preserved_footnoteRef_run = child
                            continue
                    
                    # Remove all other children
                    para.remove(child)
                
                # If no footnoteRef run was found, create one
                if preserved_footnoteRef_run is None:
                    ref_run = ET.Element(f"{{{self.NS['w']}}}r")
                    rPr = ET.SubElement(ref_run, f"{{{self.NS['w']}}}rPr")
                    rStyle = ET.SubElement(rPr, f"{{{self.NS['w']}}}rStyle")
                    rStyle.set(f"{{{self.NS['w']}}}val", "FootnoteReference")
                    ET.SubElement(ref_run, f"{{{self.NS['w']}}}footnoteRef")
                    
                    # Insert after pPr if it exists, otherwise at beginning
                    if preserved_pPr is not None:
                        idx = list(para).index(preserved_pPr) + 1
                        para.insert(idx, ref_run)
                    else:
                        para.insert(0, ref_run)
            
            # Parse content using regex to handle <i> tags
            parts = re.split(r'(<i>.*?</i>)', html.unescape(new_content))
            
            for part in parts:
                if not part:
                    continue
                    
                run = ET.SubElement(para, f"{{{self.NS['w']}}}r")
                
                # Check if this is italic text
                italic_match = re.match(r'<i>(.*?)</i>', part)
                if italic_match:
                    rPr = ET.SubElement(run, f"{{{self.NS['w']}}}rPr")
                    ET.SubElement(rPr, f"{{{self.NS['w']}}}i")
                    text_content = italic_match.group(1)
                else:
                    text_content = part
                
                t = ET.SubElement(run, f"{{{self.NS['w']}}}t")
                t.text = text_content
                t.set(f"{{{self.NS['xml']}}}space", "preserve")
            
            tree.write(footnotes_path, encoding='UTF-8', xml_declaration=True)
            return True
            
        except Exception as e:
            print(f"[WordDocumentProcessor] Error writing footnote: {e}")
            return False
    
    def save_to_buffer(self) -> BytesIO:
        """
        Save the modified document to a BytesIO buffer.
        
        Returns:
            BytesIO buffer containing the .docx file
        """
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arcname)
        buffer.seek(0)
        return buffer
    
    def save_as(self, output_path: str) -> None:
        """
        Save the modified document to a new file.
        
        Args:
            output_path: Path for the output .docx file
        """
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arcname)
    
    def cleanup(self) -> None:
        """Remove temporary files."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.cleanup()
        except:
            pass


class LinkActivator:
    """
    Post-processing module that converts plain text URLs in Word documents
    into clickable hyperlinks. Processes document.xml, endnotes.xml, and footnotes.xml.
    """
    
    @staticmethod
    def process(docx_buffer: BytesIO) -> BytesIO:
        """
        Process a docx buffer to make all URLs clickable.
        
        Args:
            docx_buffer: BytesIO containing the .docx file
            
        Returns:
            BytesIO containing the processed .docx file
        """
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Extract docx
            docx_buffer.seek(0)
            with zipfile.ZipFile(docx_buffer, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            target_files = ['word/document.xml', 'word/endnotes.xml', 'word/footnotes.xml']
            
            for xml_file in target_files:
                full_path = os.path.join(temp_dir, xml_file)
                if not os.path.exists(full_path):
                    continue

                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                def linkify_text_node(match):
                    text_content = match.group(2) 
                    url_match = re.search(r'(https?://[^\s<>"]+)', text_content)
                    
                    if url_match:
                        url = url_match.group(1)
                        clean_url = url.rstrip('.,;)')
                        trailing_punct = url[len(clean_url):]
                        safe_url = html.escape(clean_url)
                        
                        parts = text_content.split(url, 1)
                        pre = parts[0]
                        post = parts[1] if len(parts) > 1 else ""
                        
                        fld_begin = r'<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                        instr = f'<w:r><w:instrText xml:space="preserve"> HYPERLINK "{safe_url}" </w:instrText></w:r>'
                        fld_sep = r'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                        display = (
                            f'<w:r>'
                            f'<w:rPr><w:color w:val="0000FF"/><w:u w:val="single"/></w:rPr>'
                            f'<w:t>{clean_url}</w:t>'
                            f'</w:r>'
                        )
                        fld_end = r'<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                        
                        full_field_xml = f"{fld_begin}{instr}{fld_sep}{display}{fld_end}"
                        new_xml = f"{pre}</w:t></w:r>{full_field_xml}<w:r><w:t>{trailing_punct}{post}"
                        return f"{match.group(1)}{new_xml}{match.group(3)}"
                        
                    return match.group(0)

                run_pattern = r'(<w:r[^\>]*>)(.*?<w:t[^>]*>.*?<\/w:t>.*?)(<\/w:r>)'
                
                def process_run(run_match):
                    run_inner = run_match.group(2)
                    if 'HYPERLINK' in run_inner or 'w:instrText' in run_inner:
                        return run_match.group(0)
                    return re.sub(r'(<w:t[^>]*>)(.*?)(</w:t>)', linkify_text_node, run_match.group(0))

                new_content = re.sub(run_pattern, process_run, content, flags=re.DOTALL)
                
                if new_content != content:
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

            # Repackage as docx
            output_buffer = BytesIO()
            with zipfile.ZipFile(output_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
            
            output_buffer.seek(0)
            return output_buffer

        except Exception as e:
            print(f"[LinkActivator] Error: {e}")
            docx_buffer.seek(0)
            return docx_buffer
            
        finally:
            shutil.rmtree(temp_dir)


def process_document(
    file_bytes: bytes,
    style: str = "Chicago Manual of Style",
    add_links: bool = True
) -> tuple:
    """
    Process all citations in a Word document.
    
    Handles citation forms:
    1. Full citation - first time a source is cited
    2. Ibid - same source as immediately preceding citation
    3. Short form - source has been cited before, but not immediately preceding
    
    Also handles:
    - Explicit ibid references (user typed "ibid" or "ibid., 45")
    - Repetitive URLs (same URL as previous note → ibid)
    
    Args:
        file_bytes: The document as bytes
        style: Citation style to use
        add_links: Whether to make URLs clickable
        
    Returns:
        Tuple of (processed_document_bytes, results_list)
    """
    results = []
    
    # Initialize citation history for ibid and short form tracking
    history = CitationHistory()
    
    # Get the formatter for short form citations
    formatter = get_formatter(style)
    
    # Load document
    processor = WordDocumentProcessor(BytesIO(file_bytes))
    
    # Get all endnotes and footnotes
    endnotes = processor.get_endnotes()
    footnotes = processor.get_footnotes()
    
    def process_single_note(note: Dict[str, str], note_type: str) -> ProcessedCitation:
        """
        Process a single endnote or footnote.
        
        Handles:
        1. Explicit ibid references (user typed "ibid" or "ibid., 45")
        2. Repetitive URLs (same URL as previous note → ibid)
        3. Same source as previous → ibid
        4. Previously cited source → short form
        5. New source → full citation
        
        Args:
            note: Dict with 'id' and 'text' keys
            note_type: Either 'endnote' or 'footnote'
            
        Returns:
            ProcessedCitation result
        """
        note_id = note['id']
        original_text = note['text']
        
        try:
            # =================================================================
            # Case 1: Explicit ibid reference (user typed "ibid" or "ibid., 45")
            # =================================================================
            if is_ibid(original_text):
                previous_metadata = history.get_previous_metadata()
                
                if previous_metadata is None:
                    # Ibid without a previous citation - can't resolve
                    print(f"[process_document] Warning: ibid in {note_type} {note_id} but no previous citation")
                    return ProcessedCitation(
                        original=original_text,
                        formatted=original_text,
                        metadata=None,
                        url=None,
                        success=False,
                        error="ibid reference but no previous citation found",
                        citation_form="ibid"
                    )
                
                # Extract page number if present
                page = extract_ibid_page(original_text)
                
                # Format as ibid
                formatted = BaseFormatter.format_ibid(page)
                
                # Write the formatted ibid back
                if note_type == 'endnote':
                    processor.write_endnote(note_id, formatted)
                else:
                    processor.write_footnote(note_id, formatted)
                
                # Note: don't add to history - ibid doesn't change the "previous" source
                
                return ProcessedCitation(
                    original=original_text,
                    formatted=formatted,
                    metadata=previous_metadata,
                    url=history.get_previous_url(),
                    success=True,
                    citation_form="ibid"
                )
            
            # =================================================================
            # Case 2+: Process citation to get metadata
            # =================================================================
            metadata, full_formatted = get_citation(original_text, style)
            
            if not metadata or not full_formatted:
                # No metadata found - leave original text
                return ProcessedCitation(
                    original=original_text,
                    formatted=original_text,
                    metadata=None,
                    url=None,
                    success=False,
                    error="No metadata found",
                    citation_form="full"
                )
            
            # Get current URL for matching
            current_url = getattr(metadata, 'url', None)
            if not current_url and original_text.strip().startswith('http'):
                current_url = original_text.strip()
            
            # =================================================================
            # Case 2: Check if same URL as previous → ibid
            # =================================================================
            previous_url = history.get_previous_url()
            if current_url and previous_url and urls_match(current_url, previous_url):
                formatted = BaseFormatter.format_ibid()
                
                print(f"[process_document] Repetitive URL in {note_type} {note_id} - using ibid.")
                
                if note_type == 'endnote':
                    processor.write_endnote(note_id, formatted)
                else:
                    processor.write_footnote(note_id, formatted)
                
                # Don't add to history - ibid references the previous
                
                return ProcessedCitation(
                    original=original_text,
                    formatted=formatted,
                    metadata=history.get_previous_metadata(),
                    url=current_url,
                    success=True,
                    citation_form="ibid"
                )
            
            # =================================================================
            # Case 3: Check if same source as previous → ibid
            # =================================================================
            if history.is_same_as_previous(metadata):
                formatted = BaseFormatter.format_ibid()
                
                print(f"[process_document] Same source as previous in {note_type} {note_id} - using ibid.")
                
                if note_type == 'endnote':
                    processor.write_endnote(note_id, formatted)
                else:
                    processor.write_footnote(note_id, formatted)
                
                # Don't add to history - ibid references the previous
                
                return ProcessedCitation(
                    original=original_text,
                    formatted=formatted,
                    metadata=metadata,
                    url=current_url,
                    success=True,
                    citation_form="ibid"
                )
            
            # =================================================================
            # Case 4: Check if previously cited → short form
            # =================================================================
            if history.has_been_cited_before(metadata):
                # Use short form
                formatted = formatter.format_short(metadata)
                
                print(f"[process_document] Previously cited source in {note_type} {note_id} - using short form.")
                
                if note_type == 'endnote':
                    processor.write_endnote(note_id, formatted)
                else:
                    processor.write_footnote(note_id, formatted)
                
                # Add to history (updates "previous" for future ibid checks)
                history.add(metadata, formatted)
                
                return ProcessedCitation(
                    original=original_text,
                    formatted=formatted,
                    metadata=metadata,
                    url=current_url,
                    success=True,
                    citation_form="short"
                )
            
            # =================================================================
            # Case 5: New source → full citation
            # =================================================================
            if note_type == 'endnote':
                processor.write_endnote(note_id, full_formatted)
            else:
                processor.write_footnote(note_id, full_formatted)
            
            # Add to history
            history.add(metadata, full_formatted)
            
            return ProcessedCitation(
                original=original_text,
                formatted=full_formatted,
                metadata=metadata,
                url=current_url,
                success=True,
                citation_form="full"
            )
                
        except Exception as e:
            print(f"[process_document] Error processing {note_type} {note_id}: {e}")
            return ProcessedCitation(
                original=original_text,
                formatted=original_text,
                metadata=None,
                url=None,
                success=False,
                error=str(e),
                citation_form="full"
            )
    
    # Process endnotes (in order - important for ibid/short form tracking)
    for note in endnotes:
        result = process_single_note(note, 'endnote')
        results.append(result)
    
    # Process footnotes (in order - important for ibid/short form tracking)
    # Note: We continue tracking from endnotes, which may or may not be desired
    # If footnotes should have separate tracking, reset history here
    for note in footnotes:
        result = process_single_note(note, 'footnote')
        results.append(result)
    
    # Save to buffer
    doc_buffer = processor.save_to_buffer()
    
    # Make URLs clickable if requested
    if add_links:
        doc_buffer = LinkActivator.process(doc_buffer)
    
    # Cleanup
    processor.cleanup()
    
    return doc_buffer.read(), results
