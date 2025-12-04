import os
import sys
import json
import requests
from dotenv import load_dotenv

"""
Quick Bright Data trigger test
- Uses BRIGHTDATA_URL and BRIGHTDATA_API_KEY from .env
- Sends 2 sample keywords (override via CLI args)
- Prints status code and JSON/text response

Usage (PowerShell):
  .\.venv\Scripts\Activate.ps1
  python scripts\test_brightdata.py "pizza near me" "coffee shop"

If no args provided, defaults to two test keywords.
"""

def main():
    load_dotenv()

    url = os.getenv("BRIGHTDATA_URL", "").strip()
    api_key = os.getenv("BRIGHTDATA_API_KEY", "").strip()

    if not url or not api_key:
        print("ERROR: Missing BRIGHTDATA_URL or BRIGHTDATA_API_KEY in environment.")
        sys.exit(1)

    # Collect keywords from args or use defaults
    args = sys.argv[1:]
    if len(args) >= 1:
        keywords = args
    else:
        keywords = [
            "test one",
            "test two",
        ]

    # Build payload similar to app/email_scraper client
    payload = {
        "input": [
            {
                "url": "https://www.google.com/",
                "keyword": kw,
                "language": "",
                "uule": "",
                "brd_mobile": "",
            }
            for kw in keywords
        ]
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print("POST", url)
    print("Payload:", json.dumps(payload)[:500] + ("..." if len(json.dumps(payload)) > 500 else ""))

    try:
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        print("Status:", resp.status_code)
        ct = resp.headers.get("Content-Type", "")
        text = resp.text
        try:
            data = resp.json()
            print("JSON:")
            print(json.dumps(data, indent=2)[:4000])
        except Exception:
            print("Response (text):")
            print(text[:4000])

        # quick helper: show snapshot_id if present
        try:
            data = resp.json()
            sid = data.get("snapshot_id") if isinstance(data, dict) else None
            if sid:
                print(f"\nOK: snapshot_id = {sid}")
            else:
                print("\nNo snapshot_id in response — check dataset input schema/permissions.")
        except Exception:
            pass

    except requests.RequestException as e:
        print("Request error:", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
