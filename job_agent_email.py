class JJITFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://justjoin.it/api/offers"
        headers = {
            **BASE_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://justjoin.it/all-locations/devops",
            "Version": "2"
        }
        try:
            r = requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
            if r.status_code == 200:
                data = r.json()
                # Jeśli API zwraca obiekt słownikowy zamiast listy
                if isinstance(data, dict):
                    data = data.get("data", [])
                
                results = []
                for item in data:
                    title = item.get('title', '')
                    category = str(item.get('categoryId', item.get('category_id', ''))).lower()
                    skills = [s.get("name", "").lower() for s in item.get("skills", [])]
                    
                    # Filtrowanie devops na poziomie rekordów JJIT
                    if "devops" in category or "devops" in title.lower() or any("devops" in s for s in skills):
                        results.append({
                            "id": f"jjit_{item.get('id')}",
                            "title": title,
                            "company": item.get('companyName', item.get('company_name', '')),
                            "url": f"https://justjoin.it/offers/{item.get('slug', item.get('id'))}",
                            "workplace": str(item.get('workplaceType', '')),
                            "city": item.get('city', ''),
                            "source": "JustJoin.it",
                            "skills": skills,
                            "published_at": item.get("publishedAt")
                        })
                return results
            else:
                logging.warning(f"JJIT zwrócił kod statusu: {r.status_code}")
        except Exception as e:
            logging.error(f"JJIT Error: {e}")
        return []


class NoFluffJobsFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://nofluffjobs.com/api/search/posting"
        payload = {
            "category": ["devops", "architecture", "sysadmin"],
            "rawSearch": "devops",
            "page": 1
        }
        headers = {
            **BASE_HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://nofluffjobs.com/pl/devops"
        }
        try:
            r = requests.post(url, json=payload, headers=headers, impersonate="chrome120", timeout=15)
            if r.status_code == 200:
                postings = r.json().get("postings", [])
                results = []
                for item in postings:
                    tiles = [s.lower() for s in item.get("tiles", {}).get("values", [])]
                    posted_ts = item.get("posted")
                    posted_sec = posted_ts / 1000.0 if posted_ts else None
                    results.append({
                        "id": f"nfj_{item.get('id')}",
                        "title": item.get('title'),
                        "company": item.get('name'),
                        "url": f"https://nofluffjobs.com/pl/job/{item.get('url')}",
                        "workplace": "remote" if item.get("fullyRemote") else "hybrid",
                        "city": item.get("location", {}).get("places", [{}])[0].get("city", ""),
                        "source": "NoFluffJobs",
                        "skills": tiles,
                        "published_at": posted_sec
                    })
                return results
            else:
                logging.warning(f"NFJ zwrócił kod statusu: {r.status_code}")
        except Exception as e:
            logging.error(f"NFJ Error: {e}")
        return []


class RelocateMeFetcher:
    @staticmethod
    def fetch() -> List[Dict]:
        url = "https://relocate.me/search?query=devops"
        headers = {
            **BASE_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
        try:
            r = requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
            if r.status_code == 200:
                # Elastyczny regex wyciągający linki i nazwy stanowisk
                matches = re.findall(r'<a[^>]*href="(/jobs/[^"]+)"[^>]*>([^<]+)</a>', r.text)
                results = []
                for link, title in matches:
                    clean_title = title.strip()
                    if clean_title and any(k in clean_title.lower() for k in ["devops", "cloud", "sre", "infrastructure", "engineer"]):
                        results.append({
                            "id": f"relocate_{hash(link)}",
                            "title": clean_title,
                            "company": "EU Employer (Relocation)",
                            "url": f"https://relocate.me{link}",
                            "workplace": "relocation package",
                            "city": "Europe",
                            "source": "Relocate.me (EU)",
                            "skills": [],
                            "published_at": None
                        })
                return results
            else:
                logging.warning(f"Relocate.me zwrócił kod statusu: {r.status_code}")
        except Exception as e:
            logging.error(f"Relocate.me Error: {e}")
        return []