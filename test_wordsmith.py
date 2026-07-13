import json
import os
from run import make_safe_name, detect_role_type, load_config
from cv_generator import generate_cv
from cover_letter_generator import save_cover_letter
from matcher import generate_match_report, analyze_match
from analyzer import analyze_job

def run_test():
    # Load config
    config = load_config()
    
    # Try multiple database files or fallback to saved url list raw job
    data = []
    paths = ['10_output/_analyzed_full.json', '10_output/_analyzed.json']
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    break
            except Exception:
                pass
                
    job = None
    for j in data:
        if 'wordsmith' in j.get('company', '').lower():
            job = j
            print(f"Found {job.get('company')} in processed database!")
            break
            
    if not job:
        # Load from raw url list
        raw_path = '00_saved/url_list_jobs.json'
        if os.path.exists(raw_path):
            with open(raw_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
            for j in raw_data:
                if 'wordsmith' in j.get('company', '').lower():
                    # Need to analyze and match it dynamically
                    print(f"Found {j.get('company')} in raw staging file. Running analysis...")
                    job = analyze_job(j)
                    job["match"] = analyze_match(job, config)
                    break

    if not job:
        print("Error: Wordsmith job not found in processed database or raw staging file!")
        return

    os.makedirs('wordsmith_test_output', exist_ok=True)
    
    match = job.get('match', {})
    base = make_safe_name(job.get('company', 'company'), job.get('title', 'job'))
    
    match_filename = f"{base}"
    cv_name = f"{base}_CV"
    cl_name = f"{base}_CL"
    
    cv_filename_md = f"{cv_name}.md"
    cl_filename_md = f"{cl_name}.md"
    
    # Generate CV
    role_type = detect_role_type(job.get('title', ''), job.get('description', ''))
    cv = generate_cv(
        role_type=role_type, 
        job_title=job.get('title', ''), 
        company=job.get('company', ''),
        job_description=job.get('description', ''),
        match_filename=match_filename,
        cl_filename=cl_name
    )
    cv_path = os.path.join('wordsmith_test_output', cv_filename_md)
    with open(cv_path, "w", encoding='utf-8') as f:
        f.write(cv)
    print(f"Generated CV: {cv_path}")
        
    # Generate CL
    cl_path = save_cover_letter(
        job.get('title', ''),
        job.get('company', ''),
        job.get('location', 'Edinburgh'),
        job.get('description', ''),
        'wordsmith_test_output',
        match_filename=match_filename,
        cv_filename=cv_name
    )
    print(f"Generated CL: {cl_path}")
    
    # Generate Match Report
    report = generate_match_report(job, match, cv_filename=cv_filename_md, cl_filename=cl_filename_md)
    report_path = os.path.join('wordsmith_test_output', f"{match_filename}.md")
    with open(report_path, "w", encoding='utf-8') as f:
        f.write(report)
    print(f"Generated Match Report: {report_path}")
    
    print("\nTest completed.")

if __name__ == "__main__":
    run_test()
