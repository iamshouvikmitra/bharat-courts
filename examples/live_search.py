#!/usr/bin/env python3
"""Live example: search the eCourts judgment portal.

Usage:
    cd bharat-courts
    pip install -e ".[ocr]"
    python examples/live_search.py                     # default: search "constitution"
    python examples/live_search.py "right to privacy"  # custom search

Note: The judgment portal requires manual CAPTCHA solving (OCR doesn't work
reliably on its CAPTCHAs). You'll be shown a CAPTCHA image path to open,
then prompted to type the text.
"""

import asyncio
import sys

from bharat_courts.judgments.client import JudgmentSearchClient


async def search_judgments(search_text: str):
    async with JudgmentSearchClient() as client:
        print(f"Searching for '{search_text}'...")
        print("(You will be prompted to solve a CAPTCHA)\n")

        result = await client.search(search_text)

        if not result.items:
            print("No results found.")
            return

        print(f"Found {result.total_count} judgments (showing {len(result.items)}):\n")
        for j in result.items:
            print(f"  {j.title}")
            print(f"    {j.case_number} — {j.court_name}")
            print(f"    Date: {j.judgment_date}")
            if j.judges:
                print(f"    Judges: {', '.join(j.judges)}")
            if j.pdf_url:
                print(f"    PDF: {j.pdf_url}")
            print()


def main():
    search_text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "constitution"
    print("=== bharat-courts Judgment Search Example ===")
    print("Portal: judgments.ecourts.gov.in\n")
    asyncio.run(search_judgments(search_text))


if __name__ == "__main__":
    main()
