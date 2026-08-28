import smtplib
import requests
import json
import logging
import os
import re
from xml.etree import ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Set

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- KONFIGURACJA MAILOWO-SYSTEMOWA ---
EMAIL_TO = "savanteris@wp.pl"
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "twój_mail_nadawcy@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "twój_app_password")

SEEN_OFFERS_FILE = "seen_offers.json"

CRITERIA = {
    "roles": ["devops", "sre", "cloud", "site reliability", "platform engineer"],
    "keywords": ["aws", "devops", "terraform", "kubernetes", "github", "bitbucket"],
    "workplace_types": ["remote", "hybrid"],
    "allowed_cities": ["warszawa", "warsaw"],
    "excluded_companies": ["sii"]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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

# --- SCRAPERY / KOLEKTORY ---

class JJITFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://api.justjoin.it/v2/user-panel/offers"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", [])
                return [{
                    "id": f"jjit_{item.get('id')}",
                    "title": item.get('title'),
                    "company": item.get('company_name'),
                    "url": f"https://justjoin.it/offers/{item.get('id')}",
                    "workplace": item.get('workplace_type'),
                    "city": item.get('city'),
                    "source": "JustJoin.it",
                    "skills": [s.get("name", "").lower() for s in item.get("skills", [])]
                } for item in data]
        except Exception as e:
            logging.error(f"JJIT Error: {e}")
        return []

class NoFluffJobsFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://nofluffjobs.com/api/search/posting"
        payload = {"rawSearch": "devops cloud sre aws terraform kubernetes"}
        try:
            r = requests.post(url, json=payload, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                postings = r.json().get("postings", [])
                return [{
                    "id": f"nfj_{item.get('id')}",
                    "title": item.get('title'),
                    "company": item.get('name'),
                    "url": f"https://nofluffjobs.com/pl/job/{item.get('url')}",
                    "workplace": "remote" if item.get("fullyRemote") else "hybrid",
                    "city": item.get("location", {}).get("places", [{}])[0].get("city", ""),
                    "source": "NoFluffJobs",
                    "skills": [s.lower() for s in item.get("tiles", {}).get("values", [])]
                } for item in postings]
        except Exception as e:
            logging.error(f"NFJ Error: {e}")
        return []

class RemotiveFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://remotive.com/api/remote-jobs?category=devops"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                jobs = r.json().get("jobs", [])
                return [{
                    "id": f"remotive_{item.get('id')}",
                    "title": item.get('title'),
                    "company": item.get('company_name'),
                    "url": item.get('url'),
                    "workplace": "remote",
                    "city": "Global Remote",
                    "source": "Remotive (Global)",
                    "skills": [s.lower() for s in item.get("tags", [])]
                } for item in jobs]
        except Exception as e:
            logging.error(f"Remotive Error: {e}")
        return []

class BulldogjobFetcher:
    """Kolektor ofert z serwisu Bulldogjob"""
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://bulldogjob.pl/api/v1/jobs?page=1&perPage=50&roles=devops,cloud"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                jobs = r.json().get("data", [])
                results = []
                for item in jobs:
                    environment = [e.lower() for e in item.get("environment", [])]
                    results.append({
                        "id": f"bulldog_{item.get('id')}",
                        "title": item.get('title'),
                        "company": item.get('company', {}).get('name'),
                        "url": item.get('canonicalUrl'),
                        "workplace": "remote" if item.get("remote") else "hybrid",
                        "city": item.get("city", ""),
                        "source": "Bulldogjob",
                        "skills": environment
                    })
                return results
        except Exception as e:
            logging.error(f"Bulldogjob Error: {e}")
        return []

class PracujPlFetcher:
    """Kolektor ofert z serwisu Pracuj.pl (REST API)"""
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://www.pracuj.pl/api/offers?kw=devops%20aws%20terraform&pn=1"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                offers = r.json().get("offers", [])
                results = []
                for item in offers:
                    work_types = [wt.lower() for wt in item.get("workModels", [])]
                    workplace = "remote" if "zdalna" in work_types else "hybrid"
                    results.append({
                        "id": f"pracuj_{item.get('groupId')}",
                        "title": item.get('jobTitle'),
                        "company": item.get('companyName'),
                        "url": item.get('offerUrl'),
                        "workplace": workplace,
                        "city": item.get("displayWorkplace", ""),
                        "source": "Pracuj.pl",
                        "skills": [s.lower() for s in item.get("technologies", [])]
                    })
                return results
        except Exception as e:
            logging.error(f"Pracuj.pl Error: {e}")
        return []

class LinkedInFetcher:
    """Kolektor ofert z publicznego kanału LinkedIn Jobs RSS"""
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://www.linkedin.com/jobs/search/?keywords=devops%20aws&location=Poland&f_WT=2&redirect=false"
        # Używamy lekkiego parsera zapytań publicznych LinkedIn
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                # Wyszukiwanie linków i tytułów z kodu źródłowego oferty
                matches = re.findall(r'<a class="base-card__full-link[^"]*" href="([^"]+)".*?<span class="sr-only">\s*([^<]+)\s*</span>', r.text, re.DOTALL)
                results = []
                for url_match, title in matches[:15]:
                    job_id_match = re.search(r'-(\d+)\?', url_match)
                    job_id = job_id_match.group(1) if job_id_match else str(hash(url_match))
                    results.append({
                        "id": f"linkedin_{job_id}",
                        "title": title.strip(),
                        "company": "LinkedIn Company",
                        "url": url_match.split("?")[0],
                        "workplace": "remote",
                        "city": "Poland / Remote",
                        "source": "LinkedIn Jobs",
                        "skills": []
                    })
                return results
        except Exception as e:
            logging.error(f"LinkedIn Error: {e}")
        return []

# --- VALIDACJA OFERT ---

def is_matching(offer: Dict) -> bool:
    company = offer.get("company", "").lower()
    if any(ex in company for ex in CRITERIA["excluded_companies"]):
        return False

    title = offer.get("title", "").lower()
    skills = " ".join(offer.get("skills", [])).lower()
    searchable_text = f"{title} {skills}"

    # Rola
    if not any(role in title for role in CRITERIA["roles"]):
        return False

    # Słowa kluczowe (przynajmniej jedno musi się zgadzać)
    if not any(kw in searchable_text for kw in CRITERIA["keywords"]):
        return False

    # Lokalizacja / Tryb
    workplace = offer.get("workplace", "").lower()
    city = str(offer.get("city", "")).lower()

    if "remote" in workplace or "remote" in city or "zdalna" in workplace:
        return True
    elif "hybrid" in workplace or "hybryda" in workplace:
        return any(c in city for c in CRITERIA["allowed_cities"])
    
    return False

# --- WYSYŁANIE WIADOMOŚCI E-MAIL ---

def send_email_digest(matched_offers: List[Dict]) -> None:
    if not matched_offers:
        logging.info("Brak nowych ofert do wysłania.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 Job Agent: Znaleziono {len(matched_offers)} nowych ofert IT"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    html_content = f"<h2>Znalezione nowe oferty dla Ciebie ({len(matched_offers)}):</h2><ul>"
    for o in matched_offers:
        html_content += f"""
        <li style="margin-bottom: 12px;">
            <strong><a href="{o['url']}">{o['title']}</a></strong> w <b>{o['company']}</b><br/>
            <span>Źródło: {o['source']} | Tryb: {o['workplace']} ({o['city']})</span>
        </li>
        """
    html_content += "</ul>"

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        logging.info(f"E-mail z ofertami pomyślnie wysłany na {EMAIL_TO}")
    except Exception as e:
        logging.error(f"Błąd podczas wysyłania maila: {e}")

# --- MAIN ---

def main():
    seen_offers = load_seen_offers()
    all_offers = []
    
    # Pobieranie ze wszystkich źródeł
    all_offers.extend(JJITFetcher.fetch())
    all_offers.extend(NoFluffJobsFetcher.fetch())
    all_offers.extend(RemotiveFetcher.fetch())
    all_offers.extend(BulldogjobFetcher.fetch())
    all_offers.extend(PracujPlFetcher.fetch())
    all_offers.extend(LinkedInFetcher.fetch())

    new_matches = []
    for offer in all_offers:
        if offer["id"] not in seen_offers and is_matching(offer):
            new_matches.append(offer)
            seen_offers.add(offer["id"])

    if new_matches:
        send_email_digest(new_matches)
        save_seen_offers(seen_offers)
    else:
        logging.info("Brak nowych unikalnych ofert spełniających kryteria.")

if __name__ == "__main__":
    main()