import asyncio
import json
import logging
import httpx
import re
from datetime import datetime, timedelta
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

def parse_event_date(date_str):
    """
    Parses various date formats and returns (datetime_obj, formatted_str).
    Returns (None, original_str) if parsing fails.
    """
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current_year = now.year
    
    # Remove day names (Monday, etc.) and ordinal suffixes (st, nd, rd, th)
    clean = re.sub(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*', '', date_str).strip()
    clean = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', clean)
    clean = clean.replace('.', '').strip()
    clean = re.sub(r'\s+', ' ', clean)
    
    dt = None
    
    # Try parsing with year if 4 digits are present
    if re.search(r'\b\d{4}\b', clean):
        for fmt in ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"]:
            try:
                dt = datetime.strptime(clean, fmt)
                break
            except ValueError:
                continue
    
    # Try parsing without year
    if not dt:
        for fmt in ["%B %d", "%b %d"]:
            try:
                dt = datetime.strptime(clean, fmt)
                dt = dt.replace(year=current_year)
                # If the date is more than 6 months in the past, it might be for next year
                # but usually sports scrapers for "Upcoming" events don't have this ambiguity 
                # or they specify the year. We'll stick to current year for now.
                break
            except ValueError:
                continue
                
    if not dt:
        return None, date_str
        
    # Return normalized format
    return dt, dt.strftime("%A, %B %d")

def split_date_time(dt_str):
    if not dt_str or dt_str == "N/A":
        return "N/A", "N/A"
    
    # Handle common "at" separator: "Saturday, February 7th at 5:00 PM"
    if " at " in dt_str:
        date_part, time_part = dt_str.split(" at ", 1)
        return date_part.strip(), time_part.strip()
        
    # Regex to find time: e.g., "3:00 AM ET", "12:00 PM", "7:30 PM"
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)(?:\s+\w+)?)', dt_str)
    if time_match:
        time_part = time_match.group(1).strip()
        date_part = dt_str[:time_match.start()].strip(", ")
        return date_part, time_part
        
    # If no time found, it's just a date
    return dt_str.strip(), "N/A"

def format_boxing_date(date_str):
    # This is now handled by parse_event_date, but keeping a wrapper if needed
    _, formatted = parse_event_date(date_str)
    return formatted

async def scrape_tapology(client, url, promotion_name):
    logger.info(f"Scraping Tapology for {promotion_name}: {url}")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    is_results_page = "schedule=results" in url
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        
        # Handle both promotion pages and FightCenter search pages
        if "fightcenter?" in url:
            rows = soup.select('.fightcenterEvents div[data-controller="bout-toggler"]')
            if not rows:
                rows = soup.select('.fcEventList div[data-controller="bout-toggler"]')
        else:
            rows = soup.select('div[data-controller="bout-toggler"]')
            
        logger.info(f"Found {len(rows)} potential events for {promotion_name}")

        
        for row in rows:
            try:
                # In FightCenter, name might be deeper
                name_elem = row.select_one('.promotion a[href^="/fightcenter/events/"]')
                if not name_elem:
                    # Fallback for promotion pages
                    name_elem = row.select_one('.promotion a')
                
                if not name_elem:
                    continue
                    
                name = name_elem.get_text(strip=True)
                event_url = name_elem.get('href', '')
                if event_url and event_url.startswith('/'):
                    event_url = f"https://www.tapology.com{event_url}"
                
                # Zuffa exclusion for Boxing list
                if promotion_name == "Boxing":
                    if "zuffa" in name.lower():
                        logger.info(f"Excluding Zuffa boxing event: {name}")
                        continue
                    
                    # Also check the promotion link if available
                    promo_link = row.select_one('a[href^="/fightcenter/promotions/"]')
                    if promo_link:
                        promo_text = promo_link.get_text(strip=True).lower()
                        img = promo_link.select_one('img')
                        promo_alt = img.get('alt', '').lower() if img else ""
                        if "zuffa" in promo_text or "zuffa" in promo_alt or "zuffa" in promo_link.get('href', '').lower():
                            logger.info(f"Excluding Zuffa boxing event by promotion: {name}")
                            continue

                # Find the span that looks like a date/time
                date_time_raw = "N/A"
                for span in row.select('.promotion span'):
                    text = span.get_text(strip=True)
                    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    if any(day in text for day in days):
                        date_time_raw = text
                        break
                
                event_date_raw, event_time = split_date_time(date_time_raw)
                
                dt, event_date = parse_event_date(event_date_raw)
                
                # Filter logic: Results page gets 'this month', others get 'upcoming'
                if dt:
                    is_this_month = (dt.month == today.month and dt.year == today.year)
                    is_future = (dt >= today)
                    
                    if not (is_this_month or is_future):
                        continue
                
                # Detection of Title Fight and Netflix label
                row_text = row.get_text(" ", strip=True)
                is_title_fight = "Title Fight" in row_text
                is_netflix = "Netflix" in row_text

                # Detect if it's a boxing event (excluding Zuffa which should be kept)
                is_generic_boxing = (promotion_name == "Boxing" or 
                                    ("boxing" in name.lower() and "zuffa" not in name.lower()))

                # For generic boxing, only add events that are either a Title Fight or on Netflix
                if is_generic_boxing and not is_title_fight and not is_netflix:
                    continue
                
                # For "Other", only add events that are on Netflix
                if promotion_name == "Other" and not is_netflix:
                    continue

                # Location - Try to get city name
                geo_spans = row.select('.geography span')
                location = "N/A"
                venue_keywords = ['arena', 'stadium', 'center', 'apex', 'pavilion', 'hall', 'garden', 'theatre', 'club', 'house', 'lawn', 'field', 'dome', 'complex', 'square', 'park', 'apogee']
                
                for s in geo_spans:
                    # Skip sport tag
                    if 'sport' in s.get('class', []):
                        continue
                        
                    t = s.get_text(strip=True)
                    # Skip empty, flag icons, or venue names
                    if t and not s.find('img') and len(t) > 1:
                        if not any(kw in t.lower() for kw in venue_keywords):
                            # Locations often have a comma, or are just names
                            # Avoid picking up "Boxing & MMA" if it wasn't caught by .sport class
                            if "Boxing" in t or "MMA" in t:
                                continue
                            location = t
                            break
                
                # If still N/A, fallback to first available text in geography that isn't sport
                if location == "N/A":
                    geo_elem = row.select_one('.geography')
                    if geo_elem:
                        # Find all text parts and pick the one that looks like a location
                        parts = [p.strip() for p in geo_elem.get_text(" • ").split("•")]
                        for p in parts:
                            if p and "Boxing" not in p and "MMA" not in p and len(p) > 2:
                                location = p.split(',')[0].strip()
                                break
                
                events.append({
                    "event_name": name,
                    "date": event_date,
                    "time": event_time,
                    "location": location,
                    "promotion": promotion_name,
                    "url": event_url
                })
            except Exception as e:
                logger.error(f"Error parsing Tapology row: {e}")
        return events, len(rows)
    except Exception as e:
        logger.error(f"Failed to load {url}: {e}")
        return [], 0


async def main():
    urls = [
        ("https://www.tapology.com/fightcenter/promotions/1-ultimate-fighting-championship-ufc", "UFC"),
        ("https://www.tapology.com/fightcenter/promotions/6299-zuffa-boxing-zb", "Zuffa"),
        ("https://www.tapology.com/fightcenter/promotions/1969-professional-fighters-league-pfl", "PFL"),
        ("https://www.tapology.com/fightcenter?sport=boxing&group=tv", "Boxing"),
        ("https://www.tapology.com/fightcenter?sport=boxing&group=tv&schedule=results", "Boxing"),
        ("https://www.tapology.com/fightcenter?sport=mma&group=tv&schedule=results", "Other"),
        ("https://www.tapology.com/fightcenter?sport=mma&group=tv", "Other")
    ]
    
    all_events = []
    
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for original_url, promo in urls:
            if "tapology.com" not in original_url:
                continue
                
            if original_url.endswith("&group=tv"):
                page = 1
                while True:
                    url = f"{original_url}&page={page}" if page > 1 else original_url
                    events, row_count = await scrape_tapology(client, url, promo)
                    all_events.extend(events)
                    if row_count == 0:
                        break
                    page += 1
            else:
                events, _ = await scrape_tapology(client, original_url, promo)
                all_events.extend(events)   
        
    with open('upcoming_events.json', 'w', encoding='utf-8') as f:
        json.dump(all_events, f, indent=4, ensure_ascii=False)
        
    logger.info(f"Scraped {len(all_events)} events total. Saved to upcoming_events.json")

if __name__ == "__main__":
    asyncio.run(main())
