"""
Patient-facing Pygame application (new architecture).

Importing this package makes the project root importable so the game adapters
can reuse the existing `screens.base.BaseScreen` / `constants` / `games.*`
modules exactly the way the real games do -- that shared contract is the seam
the real games drop into.
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
