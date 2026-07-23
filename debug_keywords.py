import asyncio
from playwright.async_api import async_playwright
from urllib.parse import quote_plus

async def test(keyword, location):
    base_url = 'https://uk.indeed.com'
    search_url = f'{base_url}/jobs?q={quote_plus(keyword)}&l={quote_plus(location)}'
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage'],
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1440, 'height': 900},
            locale='en-GB',
            timezone_id='Europe/London',
        )
        page = await context.new_page()
        
        await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        
        cards = await page.query_selector_all('div.job_seen_beacon')
        print(f'{keyword} in {location}: {len(cards)} cards')
        
        await browser.close()

tests = [
    ('Creative Technologist', 'Edinburgh'),
    ('Creative Technologist', 'Glasgow'),
    ('Creative Technologist', 'Remote'),
    ('Web Developer', 'Edinburgh'),
    ('Web Developer', 'Glasgow'),
    ('Web Developer', 'Remote'),
    ('Technical Artist', 'Edinburgh'),
    ('Technical Artist', 'Glasgow'),
    ('Technical Artist', 'Remote'),
]

for kw, loc in tests:
    asyncio.run(test(kw, loc))