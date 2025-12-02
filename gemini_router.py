"""
citeflex/gemini_router.py

Gemini AI-powered router for ambiguous citation queries.

This is Layer 2 in the hybrid architecture:
1. Layer 1: Pattern detection (free, fast) - handles 70%+ of queries
2. Layer 2: Gemini router (paid, smart) - handles ambiguous queries
3. Layer 3: Specialized search engines
4. Layer 4: Formatting

The Gemini router is only called when:
- Pattern detection confidence is low (<0.5)
- The query is ambiguous (could be multiple types)
- Explicit disambiguation is needed

This keeps API costs low while improving accuracy for edge cases.
"""

import os
import json
from typing import Optional, Tuple, Dict, Any

from .models import CitationType, DetectionResult
from .config import GEMINI_API_KEY


# Gemini model configuration
GEMINI_MODEL = "gemini-1.5-flash"  # Fast and cheap for classification
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiRouter:
    """
    AI-powered citation type router using Google's Gemini API.
    
    Only used when pattern detection is uncertain.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self._session = None
    
    @property
    def session(self):
        """Lazy-load requests session."""
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session
    
    @property
    def is_available(self) -> bool:
        """Check if Gemini API is configured."""
        return bool(self.api_key)
    
    def classify(self, query: str, hints: Optional[Dict[str, Any]] = None) -> Optional[DetectionResult]:
        """
        Use Gemini to classify an ambiguous query.
        
        Args:
            query: The raw citation query
            hints: Optional hints from pattern detection (e.g., partial matches)
            
        Returns:
            DetectionResult with type, confidence, and hints
        """
        if not self.is_available:
            return None
        
        try:
            response = self._call_gemini(query, hints)
            if response:
                return self._parse_response(response, query)
        except Exception as e:
            print(f"[GeminiRouter] Error: {e}")
        
        return None
    
    def _call_gemini(self, query: str, hints: Optional[Dict[str, Any]] = None) -> Optional[dict]:
        """Make API call to Gemini."""
        url = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent?key={self.api_key}"
        
        # Build the prompt
        prompt = self._build_prompt(query, hints)
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for consistent classification
                "maxOutputTokens": 256,
                "responseMimeType": "application/json"
            }
        }
        
        response = self.session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            # Extract the generated text
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    text = parts[0].get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        print(f"[GeminiRouter] Failed to parse response: {text[:100]}")
        else:
            print(f"[GeminiRouter] API error: {response.status_code}")
        
        return None
    
    def _build_prompt(self, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        """Build the classification prompt."""
        hint_text = ""
        if hints:
            hint_text = f"\nHints from pattern detection: {json.dumps(hints)}"
        
        return f'''You are a citation classifier. Analyze this query and determine what type of source it refers to.

Query: "{query}"{hint_text}

Classify into exactly ONE of these types:
- JOURNAL: Academic journal article, research paper, scholarly publication
- BOOK: Book, monograph, edited volume, textbook
- LEGAL: Court case, legal opinion, statute, regulation
- INTERVIEW: Oral interview, personal communication
- NEWSPAPER: News article from newspaper or magazine
- GOVERNMENT: Government document, report, official publication
- MEDICAL: Medical/clinical article, PubMed source
- URL: Generic website or online source
- UNKNOWN: Cannot determine type

Respond with JSON only:
{{
    "type": "TYPE_NAME",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "extracted_info": {{
        "title": "if identifiable",
        "authors": ["if identifiable"],
        "year": "if identifiable"
    }}
}}'''
    
    def _parse_response(self, response: dict, query: str) -> DetectionResult:
        """Parse Gemini response into DetectionResult."""
        type_str = response.get("type", "UNKNOWN").upper()
        confidence = float(response.get("confidence", 0.5))
        
        # Map string to CitationType
        type_map = {
            "JOURNAL": CitationType.JOURNAL,
            "BOOK": CitationType.BOOK,
            "LEGAL": CitationType.LEGAL,
            "INTERVIEW": CitationType.INTERVIEW,
            "NEWSPAPER": CitationType.NEWSPAPER,
            "GOVERNMENT": CitationType.GOVERNMENT,
            "MEDICAL": CitationType.MEDICAL,
            "URL": CitationType.URL,
            "UNKNOWN": CitationType.UNKNOWN,
        }
        
        citation_type = type_map.get(type_str, CitationType.UNKNOWN)
        
        # Build hints from extracted info
        hints = response.get("extracted_info", {})
        hints["gemini_reasoning"] = response.get("reasoning", "")
        hints["gemini_classified"] = True
        
        return DetectionResult(
            citation_type=citation_type,
            confidence=confidence,
            cleaned_query=query,
            hints=hints
        )
    
    def enhance_search(self, query: str, citation_type: CitationType) -> Optional[str]:
        """
        Use Gemini to enhance/clean a search query.
        
        This can:
        - Extract the core title from a messy reference
        - Identify author names
        - Remove noise words
        
        Args:
            query: The original query
            citation_type: The detected type
            
        Returns:
            Enhanced/cleaned query for search, or None if API unavailable
        """
        if not self.is_available:
            return None
        
        try:
            url = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent?key={self.api_key}"
            
            prompt = f'''Extract the key search terms from this {citation_type.name.lower()} reference.

Reference: "{query}"

Return JSON with the most important terms for finding this source:
{{
    "search_query": "cleaned search terms",
    "title_fragment": "if identifiable",
    "author_fragment": "if identifiable",
    "year": "if identifiable"
}}'''
            
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 128,
                    "responseMimeType": "application/json"
                }
            }
            
            response = self.session.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    try:
                        result = json.loads(text)
                        return result.get("search_query", query)
                    except:
                        pass
        except Exception as e:
            print(f"[GeminiRouter] enhance_search error: {e}")
        
        return None


# Singleton instance
_gemini_router: Optional[GeminiRouter] = None


def get_gemini_router() -> GeminiRouter:
    """Get or create the Gemini router singleton."""
    global _gemini_router
    if _gemini_router is None:
        _gemini_router = GeminiRouter()
    return _gemini_router


def gemini_classify(query: str, hints: Optional[Dict[str, Any]] = None) -> Optional[DetectionResult]:
    """
    Convenience function to classify a query using Gemini.
    
    Returns None if Gemini is not available or fails.
    """
    router = get_gemini_router()
    if router.is_available:
        return router.classify(query, hints)
    return None


def gemini_enhance(query: str, citation_type: CitationType) -> Optional[str]:
    """
    Convenience function to enhance a search query using Gemini.
    
    Returns None if Gemini is not available or fails.
    """
    router = get_gemini_router()
    if router.is_available:
        return router.enhance_search(query, citation_type)
    return None
