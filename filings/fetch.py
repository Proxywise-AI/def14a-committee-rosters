#!/usr/bin/env python3
"""Download the 27 filings named in manifest.json from sec.gov into this folder as <key>.htm.

The SEC asks automated clients to identify themselves: set SEC_USER_AGENT to
"Your Name your@email" (https://www.sec.gov/os/accessing-edgar-data) and keep
to a few requests per second. The files are the filings' primary HTML documents
as EDGAR serves them; images referenced by the HTML are not downloaded.
"""
import json, os, sys, time, urllib.request

here = os.path.dirname(os.path.abspath(__file__))
ua = os.environ.get("SEC_USER_AGENT", "")
if "@" not in ua:
    # sec.gov answers 403 to a client that does not identify itself with a
    # contact address; a name alone is not enough.
    sys.exit("set SEC_USER_AGENT to 'Your Name your@email' first (SEC fair-access policy: a contact address is required)")
for entry in json.load(open(os.path.join(here, "manifest.json"))):
    out = os.path.join(here, entry["key"] + ".htm")
    if os.path.exists(out):
        print("have", entry["key"]); continue
    req = urllib.request.Request(entry["url"], headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip; data = gzip.decompress(data)
    open(out, "wb").write(data)
    print("fetched", entry["key"], len(data), "bytes")
    time.sleep(0.4)
