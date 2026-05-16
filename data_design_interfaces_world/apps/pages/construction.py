"""Streamlit page wrapper for the construction app."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_construction import main
main()
