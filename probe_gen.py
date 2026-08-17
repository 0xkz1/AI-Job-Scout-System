import json
import os
from run import make_safe_name, detect_role_type
from cv_generator import generate_cv
from cover_letter_generator import save_cover_letter
from matcher import generate_match_report

with open('10_output/_analyzed.json') as f:
    data = json.load(f)

for job in data:
    if 'wordsmith' in job.get('company', '').lower():
        match = job.get('match', {})
        base = make_safe_name(job.get('company', 'company'), job.get('title', 'job'))
        
        match_filename = f"{base}"
        cv_name = f"{base}_CV"
        cl_name = f"{base}_CL"
        
        cv_filename_md = f"{cv_name}.md"
        cl_filename_md = f"{cl_name}.md"
        
        role_type = detect_role_type(job.get('title', ''), job.get('description', ''))
        cv = generate_cv(
            role_type=role_type, 
            job_title=job.get('title', ''), 
            company=job.get('company', ''),
            job_description=job.get('description', ''),
            match_filename=match_filename,
            cl_filename=cl_name
        )
        with open(cv_filename_md, "w") as f:
            f.write(cv)
            
        save_cover_letter(
            job.get('title', ''),
            job.get('company', ''),
            job.get('location', 'Edinburgh'),
            job.get('description', ''),
            ".",
            match_filename=match_filename,
            cv_filename=cv_name
        )
        
        report = generate_match_report(job, match, cv_filename=cv_filename_md, cl_filename=cl_filename_md)
        with open(f"{match_filename}.md", "w") as f:
            f.write(report)
        print("Done!")
        break
