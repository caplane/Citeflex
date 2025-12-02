"""
app.py

Streamlit web application for CiteFlex Pro.
Transforms messy references into perfectly formatted citations.

Supports:
- Single citation lookup with multi-source search
- Bulk .docx processing
- Multiple citation styles (Chicago, APA, MLA, Bluebook, OSCOLA)
"""

import os
import re
from io import BytesIO

import streamlit as st

# Import the modular citeflex system
import citeflex
from citeflex import (
    get_citation,
    route_and_search,
    search_all_sources,
    detect_type,
    format_citation,
    CitationType,
    CitationStyle,
)

# Try to load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# =============================================================================
# Page Configuration
# =============================================================================

st.set_page_config(
    page_title="CiteFlex Pro",
    page_icon="📚",
    layout="centered"
)


# =============================================================================
# Sidebar - Configuration
# =============================================================================

with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Mode selection
    st.markdown("### 📋 Mode")
    mode = st.radio(
        "Select processing mode:",
        options=["Single Citation", "Bulk Upload"],
        index=0,
        help="Single: Fix one citation at a time. Bulk: Upload a .docx file."
    )
    
    st.divider()
    
    st.markdown("### How it works")
    st.markdown("""
    **HYBRID ARCHITECTURE:**
    1. **Pattern Detection** → Regex identifies type
    2. **Specialized Search** → Routes to right database
    3. **Multi-Source** → Crossref, OpenAlex, Semantic Scholar, PubMed
    4. **Fallback** → Google CSE for JSTOR, Scholar
    5. **Format** → Chicago, APA, MLA, Bluebook, OSCOLA
    """)
    
    st.divider()
    
    st.markdown("### Citation Types")
    st.markdown("""
    - 🎤 **Interview** → Regex extraction
    - ⚖️ **Legal** → Famous Cases Cache + CourtListener
    - 🏛️ **Government** → URL parsing
    - 📰 **Newspaper** → Domain detection
    - 📚 **Journal** → Crossref → OpenAlex → Semantic Scholar
    - 📖 **Book** → Google Books → Open Library
    - 🏥 **Medical** → PubMed
    """)
    
    st.divider()
    
    st.markdown(f"*CiteFlex v{citeflex.__version__}*")


# =============================================================================
# Helper Functions
# =============================================================================

def metadata_to_dict(metadata):
    """Convert CitationMetadata to dict for display."""
    if metadata is None:
        return None
    return metadata.to_dict()


def get_source_badge(source_engine: str) -> str:
    """Get emoji badge for source engine."""
    badges = {
        'Crossref': '🔵',
        'OpenAlex': '🟢',
        'Semantic Scholar': '🟣',
        'PubMed': '🏥',
        'Google Books': '📚',
        'Open Library': '📖',
        'Google CSE': '🔍',
        'Famous Cases Cache': '⚖️',
        'CourtListener': '🏛️',
        'Interview Extractor': '🎤',
        'Newspaper Extractor': '📰',
        'Government Extractor': '🏛️',
    }
    # Check for composite sources like "Google CSE → Crossref"
    for key, badge in badges.items():
        if key in source_engine:
            return badge
    return '📖'


def format_result_preview(result: dict, style: str) -> str:
    """Format a search result for preview display."""
    result_type = result.get('citation_type', 'UNKNOWN')
    title = result.get('title', 'Unknown Title')
    authors = result.get('authors', [])
    year = result.get('year', '')
    journal = result.get('journal', '')
    publisher = result.get('publisher', '')
    
    if result_type == 'BOOK':
        author_str = ', '.join(authors[:2]) if authors else 'Unknown'
        preview = f"**{author_str}**, *{title}*"
        if publisher:
            preview += f" ({publisher}, {year})"
        elif year:
            preview += f" ({year})"
    elif result_type in ['INTERVIEW', 'LEGAL']:
        # Just show formatted citation
        from citeflex.models import CitationMetadata
        meta = CitationMetadata.from_dict(result)
        preview = format_citation(meta, style)
    else:  # JOURNAL, MEDICAL, etc.
        author_str = authors[0].split()[-1] if authors else ''
        preview = f"**{author_str}**, \"{title}\""
        if journal:
            preview += f", *{journal}*"
        if year:
            preview += f" ({year})"
    
    # Truncate if too long
    if len(preview) > 200:
        preview = preview[:200] + "..."
    
    return preview


# =============================================================================
# Main Content
# =============================================================================

st.title("📚 CiteFlex Pro")
st.markdown("*Transform messy references into perfectly formatted citations*")

st.divider()


# =============================================================================
# Single Citation Mode
# =============================================================================

if mode == "Single Citation":
    # Style selector
    style_options = ["Chicago Manual of Style", "APA 7", "MLA 9", "Bluebook", "OSCOLA"]
    selected_style = st.selectbox("📝 Citation Style", style_options, key="single_style")
    
    st.markdown("")
    
    # Input area
    user_input = st.text_input(
        "Enter a messy citation or reference",
        placeholder='e.g., "caplan trains brains" or "roe v wade 1973"',
        help="Type a partial title, author name, or any reference you want to find and format"
    )
    
    # Example queries
    with st.expander("📝 Example queries to try"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **Academic:**
            - `Caplan trains brains sprains`
            - `transformer attention mechanism`
            - `CRISPR gene editing therapy`
            - `novak myth weak american state`
            """)
        with col2:
            st.markdown("""
            **Legal / Interviews:**
            - `brown v board of education`
            - `loving v virginia`
            - `John Smith interview March 2020`
            - `greenspan v osheroff`
            """)
    
    st.markdown("")
    
    # Search button
    search_button = st.button("🔍 Search All Sources", type="primary", use_container_width=True)
    
    # Initialize session state
    if 'search_results' not in st.session_state:
        st.session_state.search_results = []
    if 'selected_result' not in st.session_state:
        st.session_state.selected_result = None
    if 'final_citation' not in st.session_state:
        st.session_state.final_citation = ""
    if 'last_query' not in st.session_state:
        st.session_state.last_query = ""
    
    # Search Logic
    if search_button and user_input.strip():
        with st.spinner("🔄 Searching Crossref, OpenAlex, Semantic Scholar, PubMed, Google..."):
            try:
                # Detect type first
                detection = detect_type(user_input)
                detected_type = detection.citation_type
                
                if detected_type in [CitationType.INTERVIEW, CitationType.LEGAL, 
                                     CitationType.GOVERNMENT, CitationType.NEWSPAPER]:
                    # These types don't need multi-search
                    result = route_and_search(user_input)
                    if result:
                        st.session_state.search_results = [metadata_to_dict(result)]
                    else:
                        st.session_state.search_results = []
                else:
                    # Multi-source search for journals/books/medical
                    results = search_all_sources(user_input, max_results=5)
                    st.session_state.search_results = [metadata_to_dict(r) for r in results]
                
                st.session_state.selected_result = None
                st.session_state.final_citation = ""
                st.session_state.last_query = user_input
                
            except Exception as e:
                st.error(f"Search error: {e}")
                st.session_state.search_results = []
    
    # Display results
    if st.session_state.search_results:
        st.divider()
        
        # Original text display
        st.markdown("#### ORIGINAL TEXT")
        st.markdown(f"*{st.session_state.last_query}*")
        
        st.markdown("")
        st.markdown("#### PROPOSED RESOLUTIONS")
        
        # Show each result
        for i, result in enumerate(st.session_state.search_results):
            source_engine = result.get('source_engine', 'Unknown')
            badge = get_source_badge(source_engine)
            
            with st.container():
                col1, col2 = st.columns([1, 6])
                
                with col1:
                    st.markdown(f"**{badge}**")
                
                with col2:
                    preview = format_result_preview(result, selected_style)
                    st.markdown(preview)
                    st.caption(f"Source: {source_engine}")
                
                # Select button
                if st.button(f"Select #{i+1}", key=f"select_{i}"):
                    st.session_state.selected_result = result
                    # Format the citation
                    from citeflex.models import CitationMetadata
                    meta = CitationMetadata.from_dict(result)
                    formatted = format_citation(meta, selected_style)
                    st.session_state.final_citation = formatted
                    st.rerun()
                
                st.markdown("---")
        
        # If no results found
        if not st.session_state.search_results:
            st.warning("No results found. Try a different query.")
    
    # Show final citation if selected
    if st.session_state.final_citation:
        st.divider()
        st.markdown("#### ✅ FORMATTED CITATION")
        
        # Display with copy button
        st.code(st.session_state.final_citation, language=None)
        
        # Show metadata details
        if st.session_state.selected_result:
            with st.expander("📋 Metadata Details"):
                result = st.session_state.selected_result
                st.markdown(f"**Type:** {result.get('citation_type', 'Unknown')}")
                st.markdown(f"**Title:** {result.get('title', 'N/A')}")
                st.markdown(f"**Authors:** {', '.join(result.get('authors', []))}")
                st.markdown(f"**Year:** {result.get('year', 'N/A')}")
                if result.get('journal'):
                    st.markdown(f"**Journal:** {result.get('journal')}")
                if result.get('doi'):
                    st.markdown(f"**DOI:** {result.get('doi')}")
                if result.get('url'):
                    st.markdown(f"**URL:** {result.get('url')}")


# =============================================================================
# Bulk Upload Mode
# =============================================================================

elif mode == "Bulk Upload":
    st.markdown("### 📄 Bulk Citation Processing")
    st.markdown("Upload a Word document (.docx) with citations to process.")
    
    # Style selector for bulk mode
    style_options = ["Chicago Manual of Style", "APA 7", "MLA 9", "Bluebook", "OSCOLA"]
    selected_style = st.selectbox("📝 Citation Style", style_options, key="bulk_style")
    
    st.markdown("")
    
    # File uploader
    uploaded_file = st.file_uploader(
        "Upload .docx file",
        type=['docx'],
        help="Upload a Word document with citations (one per line or separated by semicolons)"
    )
    
    if uploaded_file:
        st.success(f"✓ Uploaded: {uploaded_file.name}")
        
        # Process button
        if st.button("🔄 Process All Citations", type="primary", use_container_width=True):
            try:
                import docx
                
                # Read the document
                doc = docx.Document(uploaded_file)
                
                # Extract text from paragraphs
                citations = []
                for para in doc.paragraphs:
                    text = para.text.strip()
                    if text:
                        # Split by semicolons if present
                        if ';' in text:
                            citations.extend([c.strip() for c in text.split(';') if c.strip()])
                        else:
                            citations.append(text)
                
                if not citations:
                    st.warning("No citations found in document.")
                else:
                    st.info(f"Found {len(citations)} citations to process")
                    
                    # Progress bar
                    progress = st.progress(0)
                    results_container = st.container()
                    
                    processed_results = []
                    
                    for i, citation in enumerate(citations):
                        progress.progress((i + 1) / len(citations))
                        
                        try:
                            metadata, formatted = get_citation(citation, selected_style)
                            processed_results.append({
                                'original': citation,
                                'formatted': formatted,
                                'source': metadata.source_engine if metadata else None,
                                'success': metadata is not None
                            })
                        except Exception as e:
                            processed_results.append({
                                'original': citation,
                                'formatted': f"Error: {str(e)}",
                                'source': None,
                                'success': False
                            })
                    
                    # Display results
                    with results_container:
                        st.divider()
                        st.markdown("### Results")
                        
                        success_count = sum(1 for r in processed_results if r['success'])
                        st.markdown(f"**Processed:** {success_count}/{len(processed_results)} successful")
                        
                        for i, result in enumerate(processed_results):
                            with st.expander(f"Citation {i+1}: {result['original'][:50]}..."):
                                if result['success']:
                                    st.markdown("**Original:**")
                                    st.text(result['original'])
                                    st.markdown("**Formatted:**")
                                    st.code(result['formatted'], language=None)
                                    if result['source']:
                                        st.caption(f"Source: {result['source']}")
                                else:
                                    st.error(result['formatted'])
                        
                        # Download button for results
                        output_text = "\n\n".join([
                            f"Original: {r['original']}\nFormatted: {r['formatted']}"
                            for r in processed_results
                        ])
                        
                        st.download_button(
                            "📥 Download Results",
                            data=output_text,
                            file_name="citations_processed.txt",
                            mime="text/plain"
                        )
                        
            except Exception as e:
                st.error(f"Error processing document: {e}")
    
    else:
        st.info("👆 Upload a .docx file to get started")


# =============================================================================
# Footer
# =============================================================================

st.divider()
st.caption("CiteFlex Pro • Powered by Crossref, OpenAlex, Semantic Scholar, PubMed, and more")
