"""bulk_analyze_cloud.py
One-shot: analyze all unanalyzed jobs (skill extraction + context scoring)
via a cheap cloud LLM (Mistral) instead of local Ollama.

Usage:
  source /home/kz003/.hermes/.env
  ANALYSIS_PROVIDER=mistral CLOUD_MODEL=mistral-small-latest python3 bulk_analyze_cloud.py

This is ~10-50x faster than Ollama for the initial bulk pass.
After this, switch back to ANALYSIS_PROVIDER=ollama for detailed CV/CL work.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Project root
ROOT = Path("/media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System")
sys.path.insert(0, str(ROOT))

from analyzer import analyze_job, extract_skills_ollama
from matcher import analyze_match

ANALYZED_PATH = ROOT / "10_output" / "_analyzed.json"
BACKUP_PATH = ROOT / "10_output" / "_analyzed_pre_cloud.json"
MATCHES_DIR = ROOT / "10_output" / "00_matches"

MAX_WORKERS = 3  # parallel API calls
SAVE_EVERY = 50  # save progress every N jobs

def load_analyzed() -> list[dict]:
    with open(ANALYZED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_analyzed(data: list[dict], path=None):
    path = path or ANALYZED_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def has_context_score(job: dict) -> bool:
    """Check if this job already has a proper LLM context score."""
    match = job.get("match", {})
    ctx = match.get("context", {})
    score = ctx.get("score", 0) if isinstance(ctx, dict) else 0
    # TF-IDF scores are typically < 0.3; LLM scores are > 0.3 or have reasoning
    has_reasoning = bool(ctx.get("reasoning", "")) if isinstance(ctx, dict) else False
    return score > 0.3 or (score > 0 and has_reasoning)

def has_llm_skills(job: dict) -> bool:
    """Check if job already has LLM-extracted skills (not just keyword)."""
    skills = job.get("analysis", {}).get("skills", [])
    # LLM-extracted skills typically have 5+ items with proper casing
    return len(skills) >= 5

def process_job(job: dict) -> dict:
    """Run LLM analysis on a single job. Returns updated job dict."""
    url = job.get("url", "")
    title = job.get("title", "")
    description = job.get("description", "") or job.get("snippet", "")
    
    skip_reason = None
    if not description or len(description.strip()) < 100:
        skip_reason = "no description"
    
    if skip_reason:
        return {"index": None, "url": url, "title": title, "status": "skipped", "reason": skip_reason}
    
    try:
        # Step 1: LLM-enhanced skill extraction
        skills = job.get("analysis", {}).get("skills", [])
        if len(skills) < 3 and description.strip():
            llm_skills = extract_skills_ollama(title, description)
            if llm_skills:
                skills = sorted(set(skills + llm_skills))
                if "analysis" not in job:
                    job["analysis"] = {}
                job["analysis"]["skills"] = skills
        
        # Step 2: Context scoring via _ollama_context_score (now uses call_llm)
        ctx = None
        from matcher import _ollama_context_score, _load_persona_summary
        persona = _load_persona_summary()
        if persona and description.strip():
            ctx = _ollama_context_score(description, persona)
            if ctx and "score" in ctx:
                if "match" not in job:
                    job["match"] = {}
                job["match"]["context"] = ctx
        
        return {"index": None, "url": url, "title": title, "status": "done", "skills": len(skills), "context_score": ctx.get("score", 0) if ctx else None}
    
    except Exception as e:
        return {"index": None, "url": url, "title": title, "status": "error", "error": str(e)}

def main():
    print(f"Provider: {os.environ.get('ANALYSIS_PROVIDER', 'ollama')}", flush=True)
    print(f"Model: {os.environ.get('CLOUD_MODEL', 'default')}", flush=True)
    print(f"Max workers: {MAX_WORKERS}", flush=True)
    print(flush=True)
    
    # Backup original
    if not BACKUP_PATH.exists():
        import shutil
        shutil.copy(ANALYZED_PATH, BACKUP_PATH)
        print(f"📦 Backed up to {BACKUP_PATH}", flush=True)
    else:
        print(f"📦 Backup already exists at {BACKUP_PATH}", flush=True)
    
    analyzed = load_analyzed()
    print(f"Loaded {len(analyzed)} jobs from _analyzed.json", flush=True)
    
    # Find jobs needing LLM analysis
    todo = []
    for job in analyzed:
        needs_ctx = not has_context_score(job)
        needs_skills = not has_llm_skills(job)
        has_desc = bool(job.get("description", "") or job.get("snippet", "")) and len((job.get("description", "") or job.get("snippet", "")).strip()) >= 100
        
        if has_desc and (needs_ctx or needs_skills):
            todo.append(job)
    
    print(f"Jobs needing LLM analysis: {len(todo)} / {len(analyzed)}", flush=True)
    print(f"  - Already done (context scofed): {sum(1 for j in analyzed if has_context_score(j))}", flush=True)
    print(f"  - No description: {sum(1 for j in analyzed if not (j.get('description', '') or j.get('snippet', '')).strip())}", flush=True)
    print(flush=True)
    
    if not todo:
        print("✅ All jobs already analyzed!", flush=True)
        return
    
    # Verify API connectivity
    try:
        from llm_client import call_llm
        test = call_llm(
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=10,
            temperature=0,
        )
        print(f"✅ API test: {test.strip()}", flush=True)
    except Exception as e:
        print(f"❌ API test failed: {e}", flush=True)
        print("Did you source the .env? Try:", flush=True)
        print("  source /home/kz003/.hermes/.env && ANALYSIS_PROVIDER=mistral CLOUD_MODEL=mistral-small-latest python3 bulk_analyze_cloud.py", flush=True)
        return
    
    print(flush=True)
    
    # Process with parallel workers
    done_count = 0
    error_count = 0
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_job, job): job for job in todo}
        
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            done_count += 1
            
            if result["status"] == "error":
                error_count += 1
                print(f"  ❌ [{done_count}/{len(todo)}] {result['title'][:40]:40s} — ERROR: {result.get('error', '')[:60]}", flush=True)
            elif result["status"] == "done":
                score_str = f"score={result['context_score']:.2f}" if result.get("context_score") is not None else "no-ctx"
                print(f"  ✅ [{done_count}/{len(todo)}] {result['title'][:40]:40s} — {result['skills']}skills, {score_str}", flush=True)
            else:
                print(f"  ⏭️ [{done_count}/{len(todo)}] {result['title'][:40]:40s} — {result.get('reason', 'skipped')}", flush=True)
            
            # Periodic save
            if done_count % SAVE_EVERY == 0:
                save_analyzed(analyzed)
                elapsed = time.time() - start_time
                print(f"  💾 Saved at {done_count}/{len(todo)} ({elapsed:.0f}s elapsed, ~{elapsed/done_count:.1f}s/job avg)", flush=True)
    
    # Final save
    save_analyzed(analyzed)
    elapsed = time.time() - start_time
    print(flush=True)
    print(f"✅ Complete: {done_count} jobs processed in {elapsed:.0f}s", flush=True)
    print(f"   Errors: {error_count}", flush=True)
    print(f"   Saved to {ANALYZED_PATH}", flush=True)

if __name__ == "__main__":
    main()
