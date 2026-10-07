"""
pytest configuration — ensures the project root is on sys.path so
`pytest tests/` works from any working directory.
"""
import sys
from pathlib import Path

# Insert the project root (parent of /tests/) at the front of sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
