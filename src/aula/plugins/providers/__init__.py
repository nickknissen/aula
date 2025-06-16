"""
Aula data provider implementations.

This package contains concrete implementations of the Provider interface
for various Aula data sources.
"""

# Import provider classes to ensure they're registered
from .biblioteket import BiblioteketProvider
from .minuddannelse import MinUddanelseProvider

__all__ = [
    'BiblioteketProvider',
    'MinUddanelseProvider',
]
