"""Streamlit page wrapper for the consumption app."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_consommation import main
main()
