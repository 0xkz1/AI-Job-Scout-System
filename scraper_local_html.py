"""
Scrapes job data from locally saved HTML files in 00_saved/*.html using html2text and Ollama.
"""

import os
import glob
import json
import requests
import html2text
from datetime import datetime
import re

SAVED_DIR = os.path.join(os.path.dirname(__file__), "00_saved")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf")

def extract_job_from_text(text: str) -> dict:
    prompt = f"""
You are an expert data extractor. Extract the job listing details from the following text (which was converted from HTML).
Extract the following fields:
- title (string)
- company (string)
- location (string)
- description (string) - The full job description text.

Respond ONLY with valid JSON in this exact format:
{{
  "title": "Job Title",
  "company": "Company Name",
  "location": "Location",
  "description": "Full job description text..."
}}

Text:
{text[:8000]}
"""
    payload = {
        "model": OLLAMA_MODEL,
        "system": "You are a helpful assistant that outputs only valid JSON.",
        "prompt": prompt,
        "stream": False
    }
    
    try:
        resp = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=120)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                data = json.loads(match.group())
                return data
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"Error calling Ollama: {e}")
        return None

def main():
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    
    html_files = glob.glob(os.path.join(SAVED_DIR, "*.html"))
    if not html_files:
        print("No .html files found in 00_saved/")
        return
        
    jobs = []
    
    for filepath in html_files:
        print(f"Processing {os.path.basename(filepath)}...")
        with open(filepath, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        text_content = h.handle(html_content)
        if not text_content.strip():
            continue
            
        job_data = extract_job_from_text(text_content)
        if job_data:
            job_data["url"] = "" 
            job_data["source"] = "local_html"
            job_data["source_site"] = "Local HTML"
            job_data["scraped_at"] = datetime.now().isoformat()
            job_data["snippet"] = job_data.get("description", "")[:500]
            jobs.append(job_data)
            print(f"  -> Extracted: {job_data.get('title')} at {job_data.get('company')}")
        else:
            print(f"  -> Failed to extract job from {os.path.basename(filepath)}")
            
    if jobs:
        output_file = os.path.join(SAVED_DIR, "local_html_jobs.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(jobs)} jobs to {output_file}")
        
if __name__ == "__main__":
    main()
