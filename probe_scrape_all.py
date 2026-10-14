import asyncio
import yaml
from scraper_indeed import scrape_indeed_all

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)
cfg['max_pages_per_search'] = 5

jobs = asyncio.run(scrape_indeed_all(cfg))
print(f'Total jobs: {len(jobs)}')
for j in jobs[:5]:
    print(f'  {j["title"]} @ {j["company"]} in {j["location"]}')