#!/usr/bin/env python3
"""
Company Information Web Scraper
Truthful, resilient extraction system for business intelligence

Usage:
    python scraper.py https://www.example.com
    python scraper.py https://www.example.com --output result.json
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import logging
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Set
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CompanyScraper:
    """
    Extracts structured company information from public websites.
    
    Core Principles:
    - Never hallucinate data
    - Clearly distinguish: found vs inferred vs not_found
    - Handle errors gracefully
    - Respect scraping guidelines (max 10-15 pages)
    """
    
    def __init__(self, max_pages: int = 15, timeout: int = 10):
        self.max_pages = max_pages
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.visited_urls: Set[str] = set()
        self.errors: List[Dict] = []
        self.data = {}
        
    def fetch_page(self, url: str) -> Optional[str]:
        """Safely fetch a page with timeout and error handling."""
        if url in self.visited_urls or len(self.visited_urls) >= self.max_pages:
            return None
            
        try:
            logger.info(f"Fetching: {url}")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            self.visited_urls.add(url)
            return response.text
        except requests.Timeout:
            error = f"Timeout fetching {url}"
            logger.warning(error)
            self.errors.append({"url": url, "error": error, "type": "timeout"})
            return None
        except requests.RequestException as e:
            error = f"Error fetching {url}: {str(e)}"
            logger.warning(error)
            self.errors.append({"url": url, "error": str(e), "type": "request_error"})
            return None
    
    def extract_identity(self, soup: BeautifulSoup, base_url: str) -> Dict:
        """Extract company identity information."""
        identity = {
            "company_name": {"value": "not_found", "classification": "not_found"},
            "website_url": {"value": base_url, "classification": "found"},
            "tagline": {"value": "not_found", "classification": "not_found"}
        }
        
        # Try to extract company name from title
        if soup.title and soup.title.string:
            title_text = soup.title.string.split('|')[0].strip()
            identity["company_name"] = {"value": title_text, "classification": "found"}
        
        # Try h1 tags
        h1_list = soup.find_all('h1', limit=1)
        if h1_list:
            h1_text = h1_list[0].get_text().strip()
            if len(h1_text) < 100 and h1_text != identity["company_name"]["value"]:
                identity["company_name"] = {"value": h1_text, "classification": "found"}
        
        # Look for meta description (often contains tagline)
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            identity["tagline"] = {"value": meta_desc.get('content').strip()[:200], "classification": "found"}
        
        return identity
    
    def extract_contact_info(self, soup: BeautifulSoup) -> Dict:
        """Extract contact information from page."""
        contact = {
            "emails": {"value": [], "classification": "found" if [] else "not_found"},
            "phones": {"value": [], "classification": "found" if [] else "not_found"},
            "addresses": {"value": [], "classification": "found" if [] else "not_found"},
            "social_media": {"value": {}, "classification": "inferred"}
        }
        
        text = soup.get_text()
        
        # Find email addresses
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = list(set(re.findall(email_pattern, text)))
        if emails:
            contact["emails"]["value"] = emails[:10]
            contact["emails"]["classification"] = "found"
        
        # Find phone patterns
        phone_pattern = r'(\+?\d{1,3}[-\.\s]?)?(\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4,6}|\+\d{1,3}[-\s]?\d{4,}\d{3,})'
        phones = list(set(re.findall(phone_pattern, text)))
        if phones:
            contact["phones"]["value"] = [p for p in phones if len(str(p)) > 5][:5]
            contact["phones"]["classification"] = "found"
        
        # Find social media links
        social_patterns = {
            'linkedin': r'linkedin\.com/company/[\w-]+',
            'twitter': r'twitter\.com/[\w]+',
            'facebook': r'facebook\.com/[\w]+',
            'instagram': r'instagram\.com/[\w]+',
            'youtube': r'youtube\.com/[/@\w]+'
        }
        
        for social, pattern in social_patterns.items():
            matches = re.findall(pattern, text)
            if matches:
                contact["social_media"]["value"][social] = f"https://{matches[0]}"
        
        if contact["social_media"]["value"]:
            contact["social_media"]["classification"] = "found"
        
        return contact
    
    def extract_business_info(self, soup: BeautifulSoup) -> Dict:
        """Extract business-related information."""
        business = {
            "description": {"value": "not_found", "classification": "not_found"},
            "products": {"value": [], "classification": "not_found"},
            "target_segments": {"value": [], "classification": "inferred"}
        }
        
        # Try to find about section
        text = soup.get_text()
        paragraphs = soup.find_all('p')
        
        if paragraphs:
            for para in paragraphs[:3]:
                para_text = para.get_text().strip()
                if len(para_text) > 50 and len(para_text) < 500:
                    business["description"]["value"] = para_text
                    business["description"]["classification"] = "found"
                    break
        
        return business
    
    def detect_key_pages(self, base_url: str, soup: BeautifulSoup) -> Dict[str, Dict]:
        """Detect key pages like About, Contact, Products, etc."""
        key_pages = {
            'about': {"value": "not_found", "classification": "not_found"},
            'products': {"value": "not_found", "classification": "not_found"},
            'pricing': {"value": "not_found", "classification": "not_found"},
            'contact': {"value": "not_found", "classification": "not_found"},
            'careers': {"value": "not_found", "classification": "not_found"},
            'investors': {"value": "not_found", "classification": "not_found"}
        }
        
        page_keywords = {
            'about': ['about', 'company', 'who-we-are', 'our-story', 'info'],
            'products': ['products', 'solutions', 'services', 'offerings'],
            'pricing': ['pricing', 'plans', 'packages', 'cost'],
            'contact': ['contact', 'get-in-touch', 'support', 'reach-us'],
            'careers': ['careers', 'jobs', 'hiring', 'work-with-us', 'join'],
            'investors': ['investor', 'ir', 'financial', 'shareholders'],
        }
        
        links = soup.find_all('a', href=True)
        
        for link in links:
            href = link.get('href', '').lower()
            text = link.get_text().lower()
            
            for page_type, keywords in page_keywords.items():
                for keyword in keywords:
                    if keyword in href or keyword in text:
                        if key_pages[page_type]["value"] == "not_found":
                            full_url = urljoin(base_url, link.get('href'))
                            key_pages[page_type]["value"] = full_url
                            key_pages[page_type]["classification"] = "found"
        
        return key_pages
    
    def scrape(self, url: str) -> Dict:
        """Main scraping method."""
        logger.info(f"Starting scrape of {url}")
        
        # Normalize URL
        if not url.startswith('http'):
            url = f'https://{url}'
        
        # Fetch homepage
        html = self.fetch_page(url)
        if not html:
            return {
                "error": "Failed to fetch main page",
                "url": url,
                "status": "failed"
            }
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract data
        data = {
            "metadata": {
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "pages_visited": len(self.visited_urls),
                "errors": self.errors,
                "scrape_status": "success" if not self.errors else "partial_success"
            },
            "identity": self.extract_identity(soup, url),
            "contact": self.extract_contact_info(soup),
            "business": self.extract_business_info(soup),
            "key_pages": self.detect_key_pages(url, soup)
        }
        
        logger.info(f"Scrape complete. Pages visited: {len(self.visited_urls)}")
        return data


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Company Information Web Scraper',
        epilog='Example: python scraper.py https://www.example.com --output result.json'
    )
    parser.add_argument('url', help='Company website URL to scrape')
    parser.add_argument('--output', '-o', help='Output JSON file (default: print to console)')
    parser.add_argument('--max-pages', type=int, default=15, help='Max pages to crawl (default: 15)')
    parser.add_argument('--timeout', type=int, default=10, help='Request timeout in seconds (default: 10)')
    
    args = parser.parse_args()
    
    # Initialize scraper
    scraper = CompanyScraper(max_pages=args.max_pages, timeout=args.timeout)
    
    # Run scraper
    result = scraper.scrape(args.url)
    
    # Output results
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"Results saved to {args.output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
