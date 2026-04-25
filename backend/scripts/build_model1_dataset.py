#!/usr/bin/env python3
"""
Runner script to build the Model 1 features dataset.

Usage:
    python scripts/build_model1_dataset.py
    python scripts/build_model1_dataset.py /path/to/smartdesk.db
"""

import sys
from pathlib import Path

# Add backend to path so we can import app modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.ml.model1_features import build_dataset


def main():
    # Determine database path
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Default to backend/smartdesk.db
        db_path = backend_dir / "smartdesk.db"
    
    db_path = str(db_path)
    
    print("=" * 70)
    print("SmartDesk Model 1 Dataset Builder")
    print("=" * 70)
    print(f"Database: {db_path}")
    print()
    
    # Build dataset
    try:
        build_dataset(db_path)
        print()
        print("=" * 70)
        print("[✓] Dataset build successful!")
        print("=" * 70)
    except Exception as e:
        print(f"[✗] Error building dataset: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
