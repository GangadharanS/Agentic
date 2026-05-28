"""Inject ../ReAct on sys.path so we can reuse its modules."""
import sys
from pathlib import Path

_REACT = Path(__file__).resolve().parent.parent / "ReAct"
if str(_REACT) not in sys.path:
    sys.path.insert(0, str(_REACT))
