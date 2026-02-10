import asyncio
import json
import logging
import httpx
from datetime import datetime
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Standard browser headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

async def scrape_tapology(client, url, promotion_name):
    logger.info(f"Scraping Tapology for {promotion_name}: {url}")
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
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
        return events
    except Exception as e:
        logger.error(f"Failed to load {url}: {e}")
        return []

async def scrape_espn(client, url):
    promotion_name = "Boxing"
    logger.info(f"Scraping ESPN Boxing: {url}")
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        article_body = soup.select_one('.article-body')
        if not article_body:
            logger.error("Could not find article body on ESPN")
            return []
            
        current_year = datetime.now().year
        headers = article_body.find_all('h3')
        
        for header in headers:
            header_text = header.get_text(strip=True)
            if ':' not in header_text:
                continue
                
            date_part, location_part = header_text.split(':', 1)
            date_part = date_part.strip()
            location = location_part.strip()
            
            ul = header.find_next_sibling('ul')
            if not ul:
                continue
                
            for li in ul.find_all('li'):
                text = li.get_text(strip=True)
                if text.lower().startswith("title fight:"):
                    text = text[len("title fight:"):].strip()
                
                fight_name = text.split(',', 1)[0].strip()
                full_dt = f"{date_part}, {current_year}"
                
                events.append({
                    "event_name": fight_name,
                    "date_and_time": full_dt,
                    "location": location,
                    "promotion": promotion_name
                })
        logger.info(f"Scraped {len(events)} events from ESPN")
        return events
    except Exception as e:
        logger.error(f"Failed to load ESPN: {e}")
        return []

async def main():
    urls = [
        ("https://www.tapology.com/fightcenter/promotions/1-ultimate-fighting-championship-ufc", "UFC"),
        ("https://www.tapology.com/fightcenter/promotions/6299-zuffa-boxing-zb", "Zuffa"),
        ("https://www.tapology.com/fightcenter/promotions/1969-professional-fighters-league-pfl", "PFL"),
        ("https://www.espn.com/boxing/story/_/id/12508267/boxing-schedule", "Boxing")
    ]
    
    all_events = []
    
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        tasks = []
        for url, promo in urls:
            if "tapology.com" in url:
                tasks.append(scrape_tapology(client, url, promo))
            elif "espn.com" in url:
                tasks.append(scrape_espn(client, url))
        
        results = await asyncio.gather(*tasks)
        for events in results:
            all_events.extend(events)
        
    with open('upcoming_events.json', 'w', encoding='utf-8') as f:
        json.dump(all_events, f, indent=4, ensure_ascii=False)
        
    logger.info(f"Scraped {len(all_events)} events total. Saved to upcoming_events.json")

if __name__ == "__main__":
    asyncio.run(main())
