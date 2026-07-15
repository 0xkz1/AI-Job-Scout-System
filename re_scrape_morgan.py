import json
import os
import asyncio
from scraper_reed import _fetch_reed_description_sync
from matcher import analyze_match, generate_match_report
from analyzer import analyze_job
from run import load_config, make_safe_name
from cv_generator import generate_cv, detect_role_type
from cover_letter_generator import save_cover_letter

def fix_morgan():
    config = load_config()
    with open("10_output/_analyzed.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        
    for job in data:
        if "Morgan McKinley" in job.get("company", ""):
            print("Found Morgan McKinley! Current description length:", len(job.get("description", "")))
            
            url = job["url"]
            print(f"Fetching description from: {url}")
            desc = _fetch_reed_description_sync(url)
            print(f"Fetched description length: {len(desc)}")
            
            if len(desc) > 100:
                job["description"] = desc
                # Re-run job classification
                job = analyze_job(job)
                
                # Re-run match analysis (which will generate summaries and context score via LLM)
                match = analyze_match(job, config)
                job["match"] = match
                print("New composite score:", match["composite_score"])
                
                # Setup directories
                output_dir = "10_output"
                match_dir = os.path.join(output_dir, "00_matches")
                cv_dir = os.path.join(output_dir, "10_cvs")
                letter_dir = os.path.join(output_dir, "10_cover-letters")
                
                base = make_safe_name(job['company'], job['title'])
                match_filename = f"{base}"
                cv_name = f"{base}_CV"
                cl_name = f"{base}_CL"
                
                cv_filename_md = f"{cv_name}.md"
                cl_filename_md = f"{cl_name}.md"
                
                # Generate CV
                cv_path = os.path.join(cv_dir, cv_filename_md)
                role_type = detect_role_type(job.get('title', ''), job.get('description', ''))
                cv = generate_cv(
                    role_type=role_type, 
                    job_title=job.get('title', ''), 
                    company=job.get('company', ''),
                    job_description=job.get('description', ''),
                    match_filename=match_filename,
                    cl_filename=cl_name
                )
                with open(cv_path, "w", encoding="utf-8") as f_cv:
                    f_cv.write(cv)
                print(f"Updated CV: {cv_path}")
                
                # Generate Cover Letter
                save_cover_letter(
                    job.get('title', ''),
                    job.get('company', ''),
                    job.get('location', 'Edinburgh'),
                    job.get('description', ''),
                    letter_dir,
                    match_filename=match_filename,
                    cv_filename=cv_name
                )
                print("Updated Cover Letter!")
                
                # Generate Match Report
                report = generate_match_report(job, match, cv_filename=cv_filename_md, cl_filename=cl_filename_md)
                report_path = os.path.join(match_dir, f"{match_filename}.md")
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write(report)
                print(f"Updated Match Report: {report_path}")
                break
            else:
                print("Failed to fetch description.")
                
    # Save back to database
    with open("10_output/_analyzed.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Database updated!")

if __name__ == "__main__":
    fix_morgan()
