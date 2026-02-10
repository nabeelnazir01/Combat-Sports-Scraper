import asyncio
import json
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def scrape_tapology(browser, url, promotion_name):
    logger.info(f"Scraping Tapology for {promotion_name}: {url}")
    # Use a real user agent
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    try:
        # Increase timeout and use a less strict wait
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Wait for a specific element that indicates the list is loaded
        try:
            await page.wait_for_selector('a[href*="/fightcenter/events/"]', timeout=20000)
        except:
            logger.warning(f"Timeout waiting for event links on {url}, continuing anyway...")
        
        # Scroll down slightly to trigger lazy loading if any
        await page.evaluate("window.scrollBy(0, 500)")
        await asyncio.sleep(2)
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        events = []
        rows = soup.select('div[data-controller="bout-toggler"]')
        logger.info(f"Found {len(rows)} potential events for {promotion_name}")
        
        for row in rows:
            try:
                name_elem = row.select_one('.promotion a')
                if not name_elem:
                    continue
                    
                name = name_elem.get_text(strip=True)
                
                # Find the span that looks like a date/time
                date_time = "N/A"
                for span in row.select('.promotion span'):
                    text = span.get_text(strip=True)
                    # Simple heuristic: date strings usually contain a day of week
                    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    if any(day in text for day in days):
                        date_time = text
                        break
                
                # Location
                venue_elem = row.select_one('.geography span.hidden.md\\:inline:nth-of-type(1)')
                city_elem = row.select_one('.geography span.hidden.md\\:inline:nth-of-type(2)')
                
                venue = venue_elem.get_text(strip=True) if venue_elem else ""
                city = city_elem.get_text(strip=True) if city_elem else ""
                location = f"{venue}, {city}".strip(", ")
                
                events.append({
                    "event_name": name,
                    "date_and_time": date_time,
                    "location": location,
                    "promotion": promotion_name
                })
            except Exception as e:
                logger.error(f"Error parsing Tapology row: {e}")
    except Exception as e:
        logger.error(f"Failed to load {url}: {e}")
    finally:
        await page.close()
        await context.close()
    return events

async def scrape_boxlive(browser, url):
    promotion_name = "Boxing"
    logger.info(f"Scraping Box.live: {url}")
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3) # Wait for JS to render
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
    
        events = []
        # Find all date headers and cards in order
        current_date = "N/A"
        # We'll look at all elements that could be headers or cards
        all_elements = soup.find_all(['h3', 'h2', 'div'])
        for el in all_elements:
            # Check if it's a date header
            if el.name in ['h3', 'h2']:
                txt = el.get_text().strip()
                if any(day in txt for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']):
                    current_date = txt
            
            # Check if it contains a schedule card
            if 'schedule-card' in el.get('class', []):
                try:
                    name_elem = el.select_one('.schedule-card__view-btn')
                    name = name_elem.get('title') or name_elem.get_text(strip=True) if name_elem else "Unknown Fight"
                    
                    # Location
                    loc_elem = el.select_one('.schedule-card__content__place')
                    location = loc_elem.get_text(strip=True) if loc_elem else "N/A"
                    
                    # Time - check for .localtime
                    time_elem = el.select_one('.localtime')
                    time_str = time_elem.get_text(strip=True) if time_elem else ""
                    
                    full_dt = f"{current_date} {time_str}".strip()
                    
                    events.append({
                        "event_name": name,
                        "date_and_time": full_dt,
                        "location": location,
                        "promotion": promotion_name
                    })
                except Exception as e:
                    logger.error(f"Error parsing Box.live card: {e}")
    except Exception as e:
        logger.error(f"Failed to load Box.live: {e}")
    finally:
        await page.close()
        await context.close()
    return events

async def main():
    urls = [
        ("https://www.tapology.com/fightcenter/promotions/1-ultimate-fighting-championship-ufc", "UFC"),
        ("https://www.tapology.com/fightcenter/promotions/6299-zuffa-boxing-zb", "Zuffa"),
        ("https://www.tapology.com/fightcenter/promotions/1969-professional-fighters-league-pfl", "PFL"),
        ("https://box.live/upcoming-fights-schedule/", "Boxing")
    ]
    
    all_events = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for url, promo in urls:
            if "tapology.com" in url:
                events = await scrape_tapology(browser, url, promo)
                all_events.extend(events)
            elif "box.live" in url:
                events = await scrape_boxlive(browser, url)
                all_events.extend(events)
                
        await browser.close()
        
    # Output to JSON
    with open('upcoming_events.json', 'w', encoding='utf-8') as f:
        json.dump(all_events, f, indent=4, ensure_ascii=False)
        
    logger.info(f"Scraped {len(all_events)} events total. Saved to upcoming_events.json")

if __name__ == "__main__":
    asyncio.run(main())
