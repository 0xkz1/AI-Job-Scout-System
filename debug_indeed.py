import asyncio
from playwright.async_api import async_playwright
from urllib.parse import quote_plus

async def test():
    base_url = 'https://uk.indeed.com'
    search_url = f'{base_url}/jobs?q={quote_plus("Web Developer")}&l={quote_plus("Remote")}'
    
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
        
        print(f'Going to: {search_url}')
        await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Check page title and content
        title = await page.title()
        print(f'Page title: {title}')
        
        # Try to find job cards
        cards = await page.query_selector_all('div.job_seen_beacon')
        print(f'Found {len(cards)} job_seen_beacon cards')
        
        if len(cards) == 0:
            # Try alternative selectors
            alt_cards = await page.query_selector_all('[data-jk]')
            print(f'Found {len(alt_cards)} data-jk elements')
            
            # Get page content for debugging
            content = await page.content()
            print(f'Page content length: {len(content)}')
            # Save to file for inspection
            with open('/tmp/indeed_debug.html', 'w') as f:
                f.write(content)
            print('Saved page content to /tmp/indeed_debug.html')
        
        await browser.close()

asyncio.run(test())