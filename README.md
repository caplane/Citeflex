# CiteFlex Pro 📚

Transform messy references into perfectly formatted citations.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.28+-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Multi-Source Search**: Searches Crossref, OpenAlex, Semantic Scholar, PubMed, Google Books, and more
- **Smart Detection**: Automatically identifies citation types (journal, book, legal, interview, newspaper, government, medical)
- **5 Citation Styles**: Chicago Manual of Style, APA 7, MLA 9, Bluebook, OSCOLA
- **Famous Cases Cache**: Instant lookup for 65+ landmark legal cases
- **AI-Powered Routing**: Optional Gemini integration for ambiguous queries
- **Document Processing**: Bulk processing of Word documents with hyperlink insertion
- **Free Tier**: Works without any API keys (Crossref, OpenAlex, Open Library are free)

## Architecture

```
User Query: "caplan trains brains"
              │
              ▼
┌─────────────────────────────┐
│ Layer 1: Pattern Detection  │ ← Free, instant (handles 70%+ of queries)
│ (regex-based type routing)  │
└─────────────────────────────┘
              │
              ▼ (if low confidence)
┌─────────────────────────────┐
│ Layer 2: Gemini AI Router   │ ← Optional, for ambiguous queries
│ (smart classification)      │
└─────────────────────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Layer 3: Specialized Search │
│ • Journal → Semantic Scholar → Crossref → OpenAlex → Google CSE
│ • Medical → PubMed → Crossref
│ • Legal → Famous Cases → CourtListener
│ • Book → Google Books → Open Library
└─────────────────────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Layer 4: Formatting         │
│ Chicago / APA / MLA /       │
│ Bluebook / OSCOLA           │
└─────────────────────────────┘
```

## Quick Start

### Local Development

```bash
# Clone the repository
git clone https://github.com/yourusername/citeflex.git
cd citeflex

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

### Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

1. Click the button above or create a new Railway project
2. Connect your GitHub repository
3. Add environment variables (optional - see `.env.example`)
4. Deploy!

## Environment Variables

The system works **without any API keys**. Optional keys enhance features:

| Variable | Purpose | Required |
|----------|---------|----------|
| `GOOGLE_CSE_API_KEY` | Google Custom Search (JSTOR/Scholar fallback) | No |
| `GOOGLE_CSE_ID` | Your Search Engine ID | No |
| `GEMINI_API_KEY` | AI-powered query classification | No |
| `SEMANTIC_SCHOLAR_API_KEY` | Higher rate limits | No |
| `PUBMED_API_KEY` | Higher rate limits for medical | No |
| `COURTLISTENER_API_KEY` | Legal case search | No |

## Usage

### Single Citation

```python
from citeflex import get_citation

metadata, citation = get_citation("caplan trains brains", "Chicago Manual of Style")
print(citation)
```

### All 5 Citation Styles

```python
from citeflex import get_citation

for style in ["Chicago", "APA 7", "MLA 9", "Bluebook", "OSCOLA"]:
    metadata, citation = get_citation("Loving v. Virginia", style)
    print(f"{style}: {citation}")
```

### Document Processing

```python
from citeflex import process_document, process_citations

# Process a Word document
results = process_document("paper.docx", style="APA 7", output_path="formatted.docx")

# Process a list
results = process_citations(["Brown v. Board", "Loving v. Virginia"], style="Bluebook")
```

## Project Structure

```
citeflex/
├── __init__.py           # Public API
├── app.py                # Streamlit web interface
├── models.py             # Data structures
├── config.py             # Configuration
├── detectors.py          # Pattern detection
├── extractors.py         # Local extraction
├── router.py             # Orchestration
├── gemini_router.py      # AI classification
├── document_processor.py # Word processing
├── engines/
│   ├── academic.py       # Crossref, OpenAlex, Semantic Scholar, PubMed
│   ├── legal.py          # Famous Cases, CourtListener
│   └── google_cse.py     # Google CSE, Books, Open Library
└── formatters/
    ├── chicago.py        # Chicago Manual of Style
    ├── apa.py            # APA 7th Edition
    ├── mla.py            # MLA 9th Edition
    ├── bluebook.py       # Bluebook (US legal)
    └── oscola.py         # OSCOLA (UK legal)
```

## Citation Styles

| Style | Use Case |
|-------|----------|
| **Chicago** | History, humanities |
| **APA 7** | Psychology, social sciences |
| **MLA 9** | Literature, arts |
| **Bluebook** | US legal documents |
| **OSCOLA** | UK legal documents |

## License

MIT License

## Credits

Built with: Crossref, OpenAlex, Semantic Scholar, PubMed, CourtListener, Open Library, Google Books
