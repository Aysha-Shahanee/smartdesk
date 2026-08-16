"""Local setup helper: py -3 configure_status_mapping.py PROJECT_ID mapping.json"""

import argparse
import json

from .status_mapping import set_status_mapping


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", help="GitHub ProjectV2 node ID")
    parser.add_argument("mapping_file", help="JSON object of option name -> logical state")
    args = parser.parse_args()
    with open(args.mapping_file, encoding="utf-8") as source:
        mapping = json.load(source)
    set_status_mapping(args.project_id, mapping)
    print(f"Configured {len(mapping)} status options for {args.project_id}")


if __name__ == "__main__":
    main()
