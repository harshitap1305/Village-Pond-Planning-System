"""
pytest configuration and shared fixtures.
Fixtures will be added here as modules are implemented.
"""

import os
import sys

# Ensure src/ is on the Python path for all tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
