import smtplib
import json
import logging
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Set
import xml.etree.ElementTree as ET
from playwright.async_api import async_playwright
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

EMAIL_TO = "savanteris@wp.pl"
SEEN_OFFERS_FILE = "seen_offers.json"
MAX_DAYS_OLD = 7

CRITERIA = {
    "core_tech": ["aws", "terraform", "kubernetes", "k8s", "azure", "gcp", "cloud"],
    "supporting_tech": ["github", "bitbucket", "docker", "ansible", "helm", "ci/cd", "python", "bash", "linux"],
    "valid_roles": [
        "devops", "cloud", "sre", "site reliability", "platform", 
        "infrastructure", "inżynier chmury", "system administrator", "sysadmin"
    ],
    "blacklisted_terms": [
        "junior", "trainee", "staż", "intern", "helpdesk", "support", 
        "frontend", "react", "vue", "angular", "android", "ios", "qa", "tester", "php"
    ],
    "excluded_companies": ["sii"]
}

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}

def load_seen_offers() -> Set[str]:
    try:
        with open(SEEN_OFFERS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen_offers(seen_offers: Set[str]) -> None:
    with open(SEEN_OFFERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_offers), f)

def is_within_last_days(date_epoch_or_iso, days=MAX_DAYS_OLD) -> bool:
    if not date_epoch_or_iso:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        if isinstance(date_epoch_or_iso, (int, float)):
            dt = datetime.fromtimestamp(date_epoch_or_iso, tz=timezone.utc)
            return dt >= cutoff
        elif isinstance(date_epoch_or_iso, str):
            dt = datetime.fromisoformat(date_epoch_or_iso.replace("Z", "+00:00"))
            return dt >= cutoff
    except Exception:
        pass
    return True

# --- PLAYWRIGHT FETCHERS (DLA CLOUDFLARE) ---

async def fetch_jjit() -> List[Dict]:
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BASE_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        try:
            await page.goto("https://justjoin.it/job-offers/devops", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            
            try:
                cookie_btn = await page.query_selector("#cookiescript_accept")
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            links = await page.query_selector_all('a[href*="/offers/"]')
            seen_hrefs = set()

            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href or href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)

                    title_elem = await link.query_selector("h2, h3, [class*='title']")
                    if title_elem:
                        title = await title_elem.inner_text()
                        offer_id = href.split("/")[-1]
                        
                        results.append({
                            "id": f"jjit_{offer_id}",
                            "title": title.strip(),
                            "company": "JustJoin Employer",
                            "url": f"https://justjoin.it{href}" if href.startswith("/") else href,
                            "workplace": "remote/hybrid",
                            "city": "Polska/Remote",
                            "source": "JustJoin.it",
                            "skills": ["devops"],
                            "published_at": None
                        })
                except Exception:
                    continue
        except Exception as e:
            logging.error(f"JJIT Playwright Error: {e}")
        finally:
            await browser.close()
    return results

async def fetch_nfj() -> List[Dict]:
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=BASE_HEADERS["User-Agent"])
        page = await context.new_page()
        try:
            await page.goto("https://nofluffjobs.com/pl/devops", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            
            cards = await page.query_selector_all("a.posting-list-item")
            for card in cards:
                try:
                    title_elem = await card.query_selector("h3")
                    company_elem = await card.query_selector("footer span, .posting-title__company")
                    href = await card.get_attribute("href")
                    
                    if title_elem and href:
                        title = await title_elem.inner_text()
                        company = await company_elem.inner_text() if company_elem else "NoFluffJobs Employer"
                        offer_id = href.split("/")[-1]
                        
                        results.append({
                            "id": f"nfj_{offer_id}",
                            "title": title.strip(),
                            "company": company.strip(),
                            "url": f"https://nofluffjobs.com{href}" if href.startswith("/") else href,
                            "workplace": "remote/hybrid",
                            "city": "Polska/Remote",
                            "source": "NoFluffJobs",
                            "skills": ["devops"],
                            "published_at": None
                        })
                except Exception:
                    continue
        except Exception as e:
            logging.error(f"NFJ Playwright Error: {e}")
        finally:
            await browser.close()
    return results

# --- OTWARTE REST API / RSS ---

class WeWorkRemotelyFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"
        try:
            r = requests.get(url, headers=BASE_HEADERS, timeout=15)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                results = []
                for item in root.findall(".//item"):
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    guid = item.findtext("guid", link)
                    company = "Remote Company"
                    if ":" in title:
                        parts = title.split(":", 1)
                        company = parts[0].strip()
                        title = parts[1].strip()

                    results.append({
                        "id": f"wwr_{hash(guid)}",
                        "title": title,
                        "company": company,
                        "url": link,
                        "workplace": "remote",
                        "city": "Worldwide / EU",
                        "source": "WeWorkRemotely",
                        "skills": [],
                        "published_at": None
                    })
                return results
        except Exception as e:
            logging.error(f"WeWorkRemotely Error: {e}")
        return []

class ArbeitnowFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://www.arbeitnow.com/api/job-board-api"
        try:
            r = requests.get(url, headers=BASE_HEADERS, timeout=15)
            if r.status_code == 200:
                jobs = r.json().get("data", [])
                results = []
                for item in jobs:
                    tags = [t.lower() for t in item.get("tags", [])]
                    results.append({
                        "id": f"arbeitnow_{item.get('slug')}",
                        "title": item.get("title"),
                        "company": item.get("company_name"),
                        "url": item.get("url"),
                        "workplace": "remote" if item.get("remote") else "on-site",
                        "city": item.get("location", "Europe"),
                        "source": "Arbeitnow (EU)",
                        "skills": tags,
                        "published_at": item.get("created_at")
                    })
                return results
        except Exception as e:
            logging.error(f"Arbeitnow Error: {e}")
        return []

class RemotiveFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://remotive.com/api/remote-jobs?category=devops"
        try:
            r = requests.get(url, headers=BASE_HEADERS, timeout=15)
            if r.status_code == 200:
                jobs = r.json().get("jobs", [])
                results = []
                for item in jobs:
                    tags = [t.lower() for t in item.get("tags", [])]
                    results.append({
                        "id": f"remotive_{item.get('id')}",
                        "title": item.get("title"),
                        "company": item.get("company_name"),
                        "url": item.get("url"),
                        "workplace": "remote",
                        "city": item.get("candidate_required_location", "Worldwide/EU"),
                        "source": "Remotive (EU/Global)",
                        "skills": tags,
                        "published_at": item.get("publication_date")
                    })
                return results
        except Exception as e:
            logging.error(f"Remotive Error: {e}")
        return []

# --- FILTRACJA I EMAIL ---

def is_matching(offer: Dict) -> bool:
    if not is_within_last_days(offer.get("published_at"), days=MAX_DAYS_OLD):
        return False

    company = str(offer.get("company", "")).lower()
    if any(ex in company for ex in CRITERIA["excluded_companies"]):
        return False

    title = str(offer.get("title", "")).lower()
    skills = " ".join(offer.get("skills", [])).lower()
    full_text = f"{title} {skills}"

    if any(black in full_text for black in CRITERIA["blacklisted_terms"]):
        return False

    has_valid_role = any(role in title for role in CRITERIA["valid_roles"])
    score = 2 if has_valid_role else 0
        
    for tech in CRITERIA["core_tech"]:
        if tech in full_text:
            score += 1

    return score >= 2

def send_email_digest(matched_offers: List[Dict]) -> None:
    if not matched_offers:
        return

    host = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip() or "smtp.gmail.com"
    port_val = os.getenv("SMTP_PORT", "587").strip()
    port = int(port_val) if port_val.isdigit() else 587
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()

    if not user or not password:
        logging.error("Brak danych SMTP_USER lub SMTP_PASSWORD w Secrets!")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 Job Agent: Znaleziono {len(matched_offers)} nowych ofert"
    msg["From"] = user
    msg["To"] = EMAIL_TO

    html_content = f"<h2>Znalezione nowe oferty ({len(matched_offers)}):</h2><ul>"
    for o in matched_offers:
        html_content += f"""
        <li style="margin-bottom: 12px;">
            <strong><a href="{o['url']}">{o['title']}</a></strong> w <b>{o['company']}</b><br/>
            <span>Źródło: <b>{o['source']}</b> | Tryb: {o['workplace']} ({o['city']})</span>
        </li>
        """
    html_content += "</ul>"

    msg.attach(MIMEText(html_content, "html"))

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(user, password)
                server.sendmail(user, EMAIL_TO, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(user, password)
                server.sendmail(user, EMAIL_TO, msg.as_string())

        logging.info(f"E-mail z ofertami pomyślnie wysłany na {EMAIL_TO}")
    except Exception as e:
        logging.error(f"Błąd podczas wysyłania maila: {e}")

async def main_async():
    seen_offers = load_seen_offers()
    all_offers = []

    logging.info("Pobieranie ofert z JustJoin.it przez Playwright...")
    jjit_offers = await fetch_jjit()
    logging.info(f"Pobrano {len(jjit_offers)} ofert z JustJoin.it")
    all_offers.extend(jjit_offers)

    logging.info("Pobieranie ofert z NoFluffJobs przez Playwright...")
    nfj_offers = await fetch_nfj()
    logging.info(f"Pobrano {len(nfj_offers)} ofert z NoFluffJobs")
    all_offers.extend(nfj_offers)

    wwr = WeWorkRemotelyFetcher.fetch()
    logging.info(f"Pobrano {len(wwr)} ofert z WeWorkRemotely")
    all_offers.extend(wwr)

    arbeit = ArbeitnowFetcher.fetch()
    logging.info(f"Pobrano {len(arbeit)} ofert z Arbeitnow (EU)")
    all_offers.extend(arbeit)

    remotive = RemotiveFetcher.fetch()
    logging.info(f"Pobrano {len(remotive)} ofert z Remotive")
    all_offers.extend(remotive)

    new_matches = []
    for offer in all_offers:
        if offer["id"] not in seen_offers and is_matching(offer):
            new_matches.append(offer)
            seen_offers.add(offer["id"])

    logging.info(f"Łącznie dopasowano {len(new_matches)} nowych ofert spełniających kryteria.")

    if new_matches:
        send_email_digest(new_matches)
        save_seen_offers(seen_offers)
    else:
        logging.info("Brak nowych unikalnych ofert spełniających kryteria.")

if __name__ == "__main__":
    asyncio.run(main_async())