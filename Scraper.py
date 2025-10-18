import requests
from bs4 import BeautifulSoup
import json
import time
import os
import re

class AllergenScraper:
    def __init__(self, rate_limit_delay=2, max_retries=3):
        """
        Initialize the scraper with rate limiting and retry settings.
        
        Args:
            rate_limit_delay: Seconds to wait between requests (prevents server overload)
            max_retries: Number of retry attempts for failed requests
        """
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        self.allergen_data = []
        self.failed_urls = []
        
    def get_all_allergen_links(self):
        """
        Fetches the main database page and extracts all individual allergen
        page links.
        """
        main_url = "https://www.contactdermatitisinstitute.com/database.php"
        base_url = "https://www.contactdermatitisinstitute.com"
        
        print(f"Fetching main database page from {main_url}...")
        
        try:
            response = requests.get(main_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all <a> tags with class "item" inside the "search-results" div
            links = soup.select("div.search-results a.item")
            
            allergen_urls = []
            for link in links:
                href = link.get('href')
                if href:
                    # Create the full, absolute URL
                    full_url = f"{base_url}/{href.lstrip('/')}"
                    if full_url not in allergen_urls:
                        allergen_urls.append(full_url)
                        
            print(f"Found {len(allergen_urls)} unique allergen links.\n")
            return allergen_urls

        except requests.RequestException as e:
            print(f"Error fetching main page: {e}")
            return []

    def extract_section_content(self, soup, section_title):
        """
        Extract content from a specific section based on the h3 title.
        Returns the text content after the h3 tag.
        """
        h3_tags = soup.find_all('h3')
        for h3 in h3_tags:
            if section_title.lower() in h3.get_text().lower():
                # Find the next <p> tag after this h3
                p_tag = h3.find_next('p')
                if p_tag:
                    return p_tag.get_text(strip=True)
        return None

    def extract_product_categories(self, soup):
        """
        Extract product categories from the product-list div.
        """
        product_list = soup.find('div', class_='product-list')
        categories = []
        
        if product_list:
            h4_tags = product_list.find_all('h4')
            for h4 in h4_tags:
                category = h4.get_text(strip=True)
                if category:
                    categories.append(category)
        
        return categories

    def extract_clinician_note(self, soup):
        """
        Extract the clinician's point of view section.
        """
        clinician_h3 = None
        h3_tags = soup.find_all('h3')
        
        for h3 in h3_tags:
            if 'clinician' in h3.get_text().lower():
                clinician_h3 = h3
                break
        
        if clinician_h3:
            # Find the next <p> tag or div with note class
            note_div = clinician_h3.find_next('div', class_='note')
            if note_div:
                # Get all text content from the note div
                note_text = note_div.get_text(strip=True)
                return note_text if note_text else None
            
            p_tag = clinician_h3.find_next('p')
            if p_tag:
                return p_tag.get_text(strip=True)
        
        return None

    def get_allergen_details(self, url, attempt=1):
        """
        Scrapes a single allergen page for its name and other details.
        Includes retry logic with exponential backoff.
        """
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. Get the allergen name
            name_tag = soup.select_one("h1.topic-name")
            allergen_name = name_tag.get_text(strip=True) if name_tag else "Name Not Found"
            
            # 2. Get "Where is it found?" section
            where_found = self.extract_section_content(soup, "Where is")
            
            # 3. Get "How can you avoid contact?" / Alternative names section
            other_names = []
            intro_p = soup.find('p', string=lambda t: t and 'Avoid products that list any of the following names' in t)
            
            if intro_p:
                names_p_tag = intro_p.find_next_sibling('p')
                
                if names_p_tag:
                    # Find all <br> tags and split by them to preserve multi-line names
                    br_tags = names_p_tag.find_all('br')
                    
                    if br_tags:
                        items = []
                        current_item = []
                        
                        for element in names_p_tag.children:
                            if element.name == 'br':
                                if current_item:
                                    items.append(''.join(current_item).strip())
                                current_item = []
                            elif isinstance(element, str):
                                text = element.strip()
                                if text:
                                    current_item.append(text)
                            else:
                                text = element.get_text().strip()
                                if text:
                                    current_item.append(text)
                        
                        if current_item:
                            items.append(''.join(current_item).strip())
                        
                        for item in items:
                            clean_name = item.strip().lstrip('•').strip()
                            if clean_name and not clean_name.startswith('<!--'):
                                other_names.append(clean_name)
                    else:
                        all_names_text = names_p_tag.get_text(separator='\n')
                        raw_names_list = all_names_text.split('\n')
                        
                        for name in raw_names_list:
                            clean_name = name.strip().strip('•').strip()
                            if clean_name:
                                other_names.append(clean_name)
            
            # 4. Get product categories
            product_categories = self.extract_product_categories(soup)
            
            # 5. Get clinician's note
            clinician_note = self.extract_clinician_note(soup)
            
            return {
                "allergen_name": allergen_name,
                "where_found": where_found,
                "other_names": other_names,
                "product_categories": product_categories,
                "clinician_note": clinician_note,
                "url": url
            }

        except requests.RequestException as e:
            if attempt < self.max_retries:
                wait_time = 2 ** attempt
                print(f"  ⚠️  Attempt {attempt}/{self.max_retries} failed: {e}")
                print(f"  ⏳ Retrying in {wait_time} seconds...", end=" ")
                time.sleep(wait_time)
                print("Now retrying...")
                return self.get_allergen_details(url, attempt + 1)
            else:
                print(f"  ❌ All {self.max_retries} attempts failed for {url}")
                return None

    def load_existing_data(self):
        """Load existing allergen data from JSON file if it exists."""
        if os.path.exists("allergens.json"):
            try:
                with open("allergens.json", 'r') as f:
                    self.allergen_data = json.load(f)
                print(f"✅ Loaded {len(self.allergen_data)} existing allergens from allergens.json\n")
                return True
            except json.JSONDecodeError:
                print("⚠️  allergens.json exists but is corrupted. Starting fresh.\n")
                self.allergen_data = []
                return False
        return False

    def load_failed_urls(self):
        """Load previously failed URLs if they exist."""
        if os.path.exists("failed_urls.txt"):
            try:
                with open("failed_urls.txt", 'r') as f:
                    self.failed_urls = [line.strip() for line in f if line.strip()]
                print(f"✅ Loaded {len(self.failed_urls)} previously failed URLs\n")
                return True
            except Exception as e:
                print(f"⚠️  Error loading failed_urls.txt: {e}\n")
                return False
        return False

    def save_data(self):
        """Save allergen data to JSON file."""
        with open("allergens.json", 'w') as f:
            json.dump(self.allergen_data, f, indent=2)

    def save_failed_urls(self):
        """Save failed URLs to file for later retry."""
        with open("failed_urls.txt", 'w') as f:
            for url in self.failed_urls:
                f.write(url + "\n")

    def scrape_allergens(self, urls):
        """
        Scrape allergens with rate limiting to prevent server overload.
        """
        total = len(urls)
        scraped_count = 0
        
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{total}] Scraping {url}...")
            details = self.get_allergen_details(url)
            
            if details:
                # Check if this allergen is already in the data
                if not any(item['url'] == url for item in self.allergen_data):
                    self.allergen_data.append(details)
                    scraped_count += 1
                else:
                    print(f"  ℹ️  Already in database, skipping.\n")
                
                # Remove from failed list if it was there
                if url in self.failed_urls:
                    self.failed_urls.remove(url)
            else:
                # Add to failed list if not already there
                if url not in self.failed_urls:
                    self.failed_urls.append(url)
            
            # Rate limiting to prevent server overload
            if i < total:
                print(f"⏰ Rate limiting ({self.rate_limit_delay}s delay)...\n")
                time.sleep(self.rate_limit_delay)
        
        return scraped_count

    def run(self, retry_only=False):
        """
        Main scraping workflow.
        
        Args:
            retry_only: If True, only retry failed URLs. If False, scrape all allergens.
        """
        print("=" * 70)
        print("🔬 ALLERGEN DATABASE SCRAPER")
        print("=" * 70)
        print(f"⏰ Rate limit delay: {self.rate_limit_delay}s")
        print(f"🔄 Max retries: {self.max_retries}\n")
        
        # Load existing data
        self.load_existing_data()
        
        if retry_only:
            print("🔄 RETRY MODE - Only retrying failed URLs\n")
            # Load previously failed URLs
            self.load_failed_urls()
            
            if not self.failed_urls:
                print("✅ No failed URLs to retry!\n")
                return
            
            urls_to_scrape = self.failed_urls.copy()
        else:
            print("📥 FULL MODE - Fetching all allergen URLs from database\n")
            # Get all allergen links
            urls_to_scrape = self.get_all_allergen_links()
            
            if not urls_to_scrape:
                print("❌ No allergen links found. Exiting.")
                return
        
        # Scrape the allergens
        print(f"🚀 Starting scrape of {len(urls_to_scrape)} allergens...\n")
        scraped_count = self.scrape_allergens(urls_to_scrape)
        
        # Save progress
        self.save_data()
        self.save_failed_urls()
        
        # Print summary
        print("\n" + "=" * 70)
        print("✅ SCRAPING PHASE COMPLETE!")
        print("=" * 70)
        print(f"✅ Allergens in database: {len(self.allergen_data)}")
        print(f"📝 Newly scraped this run: {scraped_count}")
        print(f"❌ Failed allergens: {len(self.failed_urls)}")
        print(f"💾 Data saved to: allergens.json")
        
        if self.failed_urls:
            print(f"📋 Failed URLs saved to: failed_urls.txt\n")
            print("📋 FAILED ALLERGENS:")
            for url in self.failed_urls[:10]:
                print(f"  - {url}")
            if len(self.failed_urls) > 10:
                print(f"  ... and {len(self.failed_urls) - 10} more\n")
        
        # If there are still failed URLs, offer to retry at the end
        if self.failed_urls:
            print("=" * 70)
            print("🔄 FINAL RETRY ATTEMPT")
            print("=" * 70)
            print(f"Retrying {len(self.failed_urls)} failed URLs...\n")
            
            # Reset failed URLs for final attempt
            failed_before_final = self.failed_urls.copy()
            self.failed_urls = []
            
            scraped_count = self.scrape_allergens(failed_before_final)
            
            # Save final progress
            self.save_data()
            self.save_failed_urls()
            
            print("\n" + "=" * 70)
            print("✅ FINAL RETRY COMPLETE!")
            print("=" * 70)
            print(f"✅ Total allergens in database: {len(self.allergen_data)}")
            print(f"📝 Recovered in final retry: {scraped_count}")
            print(f"❌ Still failing: {len(self.failed_urls)}")
            
            if self.failed_urls:
                print(f"\n⚠️  These {len(self.failed_urls)} allergens continue to fail:")
                for url in self.failed_urls:
                    print(f"  - {url}")


def main():
    """Main entry point."""
    import sys
    
    # Check for --retry-only flag
    retry_only = "--retry-only" in sys.argv
    
    # Create scraper instance with 2 second rate limiting (adjust as needed)
    scraper = AllergenScraper(rate_limit_delay=2, max_retries=3)
    
    try:
        scraper.run(retry_only=retry_only)
    except KeyboardInterrupt:
        print("\n\n⚠️  Scraping interrupted by user!")
        scraper.save_data()
        scraper.save_failed_urls()
        print("✅ Progress saved. You can resume with: python scrape.py --retry-only")

if __name__ == "__main__":
    main()