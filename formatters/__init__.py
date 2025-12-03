"""
citeflex/formatters/__init__.py

Citation formatters package.
"""

from formatters.base import (
    BaseFormatter,
    register_formatter,
    get_formatter,
    format_citation,
)
from formatters.chicago import ChicagoFormatter
from formatters.apa import APAFormatter
from formatters.mla import MLAFormatter
from formatters.bluebook import BluebookFormatter
from formatters.oscola import OSCOLAFormatter

__all__ = [
    'BaseFormatter',
    'register_formatter', 
    'get_formatter',
    'format_citation',
    'ChicagoFormatter',
    'APAFormatter',
    'MLAFormatter',
    'BluebookFormatter',
    'OSCOLAFormatter',
]
