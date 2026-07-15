#!/usr/bin/env python3
"""Test Reed page source to find job description extraction approach."""
import urllib.request
import re
import sys

url = "https://www.reed.co.uk/jobs/product-design-engineer-ai-native-products/56964373"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
})

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)

print(f"HTML length: {len(html)}")

# Check for JSON-LD (Schema.org JobPosting)
ld_matches = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
print(f"JSON-LD blocks found: {len(ld_matches)}")
for i, block in enumerate(ld_matches[:3]):
    print(f"\n--- JSON-LD block {i+1} ---")
    print(block[:600])

# Check for __NEXT_DATA__
if "__NEXT_DATA__" in html:
    print("\n✅ Found __NEXT_DATA__")
    idx = html.find("__NEXT_DATA__")
    print(html[idx:idx+500])
else:
    print("\n❌ No __NEXT_DATA__")

# Check for jobDescription key
lower = html.lower()
if "jobdescription" in lower:
    idx = lower.find("jobdescription")
    print(f"\n✅ Found 'jobDescription' at index {idx}")
    print(html[max(0, idx-30):idx+300])
else:
    print("\n❌ No 'jobDescription' key found")

# Print a sample of the HTML to understand structure
print("\n--- HTML sample (first 2000 chars) ---")
print(html[:2000])
