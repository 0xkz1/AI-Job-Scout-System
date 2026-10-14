import json
import os
from matcher import analyze_match, save_match_report, _ollama_job_summary, _ollama_context_score
from run import load_config, make_safe_name

def update_high_matches():
    config = load_config()
    with open("10_output/_analyzed.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        
    updated = False
    for job in data:
        match = job.get("match", {})
        score = match.get("composite_score", 0)
        
        # We only want to update jobs that have 50%+ score and don't have a summary yet
        if score >= 0.5 and not match.get("summary_en") and job.get("description"):
            print(f"Updating {job['company']} - {job['title']} (Score: {score})...")
            
            # Re-run the match analysis to get the new LLM context score and summary
            new_match = analyze_match(job, config)
            job["match"] = new_match
            
            # Re-generate the markdown report. Via save_match_report, not
            # generate_match_report directly: the renderer defaults
            # expired/applied to False and carried to None, so calling it raw
            # and writing the result clears hand-ticked checkboxes and drops
            # the cv_pdf/cl_pdf/cv_review/cl_review links. save_match_report
            # reads all of them off the file it is about to overwrite.
            base_name = make_safe_name(job['company'], job['title'])
            cv_filename = f"{base_name}_CV.md"
            cl_filename = f"{base_name}_CL.md"

            save_match_report(job, new_match, "10_output/00_matches",
                              cv_filename=cv_filename, cl_filename=cl_filename)


            updated = True
            
    if updated:
        with open("10_output/_analyzed.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Updated existing high-match jobs successfully!")
    else:
        print("No high-match jobs needed updating.")

if __name__ == "__main__":
    update_high_matches()
