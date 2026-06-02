import sys
from pathlib import Path

MAIL_SECRETARY_ROOT = Path(__file__).resolve().parents[1]
root_path = str(MAIL_SECRETARY_ROOT)
if root_path not in sys.path:
    sys.path.insert(0, root_path)
