import smtplib
import requests
import json
import logging
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Set

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- KONFIGURACJA MAILOWO-SYSTEMOWA ---
EMAIL_TO = "savanteris@wp.pl"
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

SEEN_OFFERS_FILE = "seen_offers.json"

# --- PROFIL: MID/SENIOR DEVOPS & CLOUD ENGINEER ---
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
    "allowed_cities": ["warszawa", "warsaw", "poland", "polska"],
    "excluded_companies": ["sii"]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache"
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

# --- SKUTECZNE KOLEKTORY OFERT ---

class JJITFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        # Publiczny skonsolidowany endpoint wyszukiwania JustJoin.it
        url = "https://api.justjoin.it/v2/user-panel/offers?category=devops&sortBy=published&sortOrder=desc&perPage=50"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json().get("data", [])
                results = []
                for item in data:
                    title = item.get('title', '')
                    skills = [s.get("name", "").lower() for s in item.get("skills", [])]
                    results.append({
                        "id": f"jjit_{item.get('id')}",
                        "title": title,
                        "company": item.get('companyName', item.get('company_name', '')),
                        "url": f"https://justjoin.it/offers/{item.get('slug', item.get('id'))}",
                        "workplace": str(item.get('workplaceType', '')),
                        "city": item.get('city', ''),
                        "source": "JustJoin.it",
                        "skills": skills
                    })
                return results
            else:
                logging.warning(f"JJIT zwrócił status: {r.status_code}")
        except Exception as e:
            logging.error(f"JJIT Error: {e}")
        return []

class NoFluffJobsFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://nofluffjobs.com/api/search/posting"
        payload = {
            "category": ["devops"],
            "rawSearch": "devops"
        }
        headers = {**HEADERS, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code == 200:
                postings = r.json().get("postings", [])
                results = []
                for item in postings:
                    tiles = [s.lower() for s in item.get("tiles", {}).get("values", [])]
                    results.append({
                        "id": f"nfj_{item.get('id')}",
                        "title": item.get('title'),
                        "company": item.get('name'),
                        "url": f"https://nofluffjobs.com/pl/job/{item.get('url')}",
                        "workplace": "remote" if item.get("fullyRemote") else "hybrid",
                        "city": item.get("location", {}).get("places", [{}])[0].get("city", ""),
                        "source": "NoFluffJobs",
                        "skills": tiles
                    })
                return results
            else:
                logging.warning(f"NFJ zwrócił status: {r.status_code}")
        except Exception as e:
            logging.error(f"NFJ Error: {e}")
        return []

class BulldogjobFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://bulldogjob.pl/api/v1/jobs?page=1&perPage=50&keyword=devops"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                jobs = r.json().get("data", [])
                results = []
                for item in jobs:
                    env = [e.lower() for e in item.get("environment", [])]
                    skills = [s.get("name", "").lower() for s in item.get("technologies", [])]
                    results.append({
                        "id": f"bulldog_{item.get('id')}",
                        "title": item.get('title', ''),
                        "company": item.get('company', {}).get('name', ''),
                        "url": item.get('canonicalUrl', ''),
                        "workplace": "remote" if item.get("remote") else "hybrid",
                        "city": item.get("city", ""),
                        "source": "Bulldogjob",
                        "skills": env + skills
                    })
                return results
            else:
                logging.warning(f"Bulldogjob zwrócił status: {r.status_code}")
        except Exception as e:
            logging.error(f"Bulldogjob Error: {e}")
        return []

class LinkedInFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=DevOps&location=Poland&start=0"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                matches = re.findall(r'<a class="base-card__full-link[^"]*" href="([^"]+)".*?<span class="sr-only">\s*([^<]+)\s*</span>', r.text, re.DOTALL)
                results = []
                for url_match, title in matches[:15]:
                    job_id_match = re.search(r'-(\d+)\?', url_match)
                    job_id = job_id_match.group(1) if job_id_match else str(hash(url_match))
                    results.append({
                        "id": f"linkedin_{job_id}",
                        "title": title.strip(),
                        "company": "LinkedIn Offer",
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

# --- WERYFIKACJA I FILTRACJA OFERT ---

def is_matching(offer: Dict) -> bool:
    company = str(offer.get("company", "")).lower()
    if any(ex in company for ex in CRITERIA["excluded_companies"]):
        return False

    title = str(offer.get("title", "")).lower()
    skills = " ".join(offer.get("skills", [])).lower()
    full_text = f"{title} {skills}"

    if any(black in full_text for black in CRITERIA["blacklisted_terms"]):
        return False

    has_valid_role = any(role in title for role in CRITERIA["valid_roles"])
    
    score = 0
    if has_valid_role:
        score += 2
        
    for tech in CRITERIA["core_tech"]:
        if tech in full_text:
            score += 1

    for tech in CRITERIA["supporting_tech"]:
        if tech in full_text:
            score += 1

    # Wystarczy obecność roli + 1 technologii lub samo dopasowanie słów kluczowych
    if score < 2:
        return False

    return True

# --- WYSYŁANIE E-MAILA ---

def send_email_digest(matched_offers: List[Dict]) -> None:
    if not matched_offers:
        logging.info("Brak nowych ofert do wysłania.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 Job Agent: Znaleziono {len(matched_offers)} nowych ofert IT"
    msg["From"] = SMTP_USER
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
    
    sources = [
        ("JustJoin.it", JJITFetcher),
        ("NoFluffJobs", NoFluffJobsFetcher),
        ("Bulldogjob", BulldogjobFetcher),
        ("LinkedIn", LinkedInFetcher),
    ]

    for name, fetcher in sources:
        fetched = fetcher.fetch()
        logging.info(f"Pobrano {len(fetched)} ofert z serwisu: {name}")
        all_offers.extend(fetched)

    new_matches = []
    for offer in all_offers:
        if offer["id"] not in seen_offers and is_matching(offer):
            new_matches.append(offer)
            seen_offers.add(offer["id"])

    logging.info(f"Łącznie dopasowano {len(new_matches)} nowych ofert po filtracji.")

    if new_matches:
        send_email_digest(new_matches)
        save_seen_offers(seen_offers)
    else:
        logging.info("Brak nowych unikalnych ofert spełniających kryteria.")

if __name__ == "__main__":
    main()