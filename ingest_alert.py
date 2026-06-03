import requests
import sqlite3
import json
import os
import sys
from duckduckgo_search import DDGS
import re

# Placeholder for PDF extraction - using a common library if available
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

class CitationIngestor:
    def __init__(self, db_path='citations.db'):
        self.db_path = db_path

    def search_crossref(self, title):
        print(f"Searching Crossref for: {title}")
        url = f"https://api.crossref.org/works?query.title={requests.utils.quote(title)}&rows=1"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                items = data.get('message', {}).get('items', [])
                if items:
                    return items[0]
        except Exception as e:
            print(f"Crossref error: {e}")
        return None

    def search_semantic_scholar(self, title):
        print(f"Searching Semantic Scholar for: {title}")
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(title)}&limit=1&fields=title,authors,abstract,openAccessPdf,externalIds"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                data_list = data.get('data', [])
                if data_list:
                    return data_list[0]
        except Exception as e:
            print(f"Semantic Scholar error: {e}")
        return None

    def search_arxiv(self, title):
        print(f"Searching arXiv for: {title}")
        url = f"http://export.arxiv.org/api/query?search_query=ti:{requests.utils.quote(title)}&max_results=1"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Basic regex to extract link from XML if not using a full parser
                match = re.search(r'<id>(http://arxiv.org/abs/.*?)</id>', response.text)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"arXiv error: {e}")
        return None

    def search_unpaywall(self, doi):
        if not doi: return None
        print(f"Searching Unpaywall for DOI: {doi}")
        email = "your-email@illinois.edu" # Placeholder as requested
        url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Unpaywall error: {e}")
        return None

    def search_duckduckgo_pdf(self, title):
        print(f"Searching DuckDuckGo for PDF: {title}")
        try:
            with DDGS() as ddgs:
                results = ddgs.text(f'"{title}" filetype:pdf', max_results=3)
                return [r['href'] for r in results if r['href'].endswith('.pdf')]
        except Exception as e:
            print(f"DuckDuckGo search error: {e}")
        return []

    def download_pdf(self, url):
        print(f"Attempting to download PDF from: {url}")
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                with open("temp.pdf", "wb") as f:
                    f.write(response.content)
                return "temp.pdf"
        except Exception as e:
            print(f"Download error: {e}")
        return None

    def extract_text_from_pdf(self, pdf_path):
        if not PyPDF2:
            print("PyPDF2 not installed. Cannot extract text.")
            return ""
        text = ""
        try:
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text()
        except Exception as e:
            print(f"PDF extraction error: {e}")
        return text

    def evaluate_with_llm(self, title, context):
        """
        Placeholder for Local LLM Engine.
        """
        print(f"Evaluating citation for: {title}")
        
        full_text = f"{title}\n{context}"
        keywords = ["Delta", "DeltaAI", "NCSA", "OAC-2005572", "OAC-2320345"]
        found_keywords = [k for k in keywords if k.lower() in full_text.lower()]
        
        # False positive checks
        false_positives = ["delta variant", "delta function", "river delta", "delta dense matter"]
        is_false_positive = any(fp in full_text.lower() for fp in false_positives)

        if found_keywords and not is_false_positive:
            status = 'Pending'
            reasoning = f"Potential match found. Triggers: {', '.join(found_keywords)}."
            usage_context = f"Mentioned in: {title}" 
        else:
            status = 'Rejected'
            reasoning = "Does not mention Delta/DeltaAI supercomputers or is a false positive."
            usage_context = ""

        return status, reasoning, usage_context

    def upsert_citation(self, data):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
            INSERT INTO citations (
                title, system, alert_trigger, status, reasoning, usage_context, 
                uiuc_affiliated, uiuc_authors_depts, award_number, doi_or_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title) DO UPDATE SET
                doi_or_url = excluded.doi_or_url,
                status = CASE WHEN citations.doi_or_url LIKE '%arxiv.org%' AND excluded.doi_or_url LIKE '%doi.org%' THEN 'Pending' ELSE citations.status END
            ''', (
                data['title'], data['system'], data['alert_trigger'], data['status'], 
                data['reasoning'], data['usage_context'], data['uiuc_affiliated'], 
                data['uiuc_authors_depts'], data['award_number'], data['doi_or_url']
            ))
            conn.commit()
            print(f"Successfully upserted: {data['title']}")
        except Exception as e:
            print(f"Database error: {e}")
        finally:
            conn.close()

    def process_alert(self, title, trigger):
        print(f"Processing alert: {title} (Trigger: {trigger})")
        
        # 1. Document Discovery
        crossref_data = self.search_crossref(title)
        ss_data = self.search_semantic_scholar(title)
        arxiv_url = self.search_arxiv(title)
        
        doi = crossref_data.get('DOI') if crossref_data else None
        doi_url = f"https://doi.org/{doi}" if doi else (arxiv_url if arxiv_url else "")
        
        # 2. PDF Retrieval
        pdf_url = None
        if doi:
            unpaywall_data = self.search_unpaywall(doi)
            if unpaywall_data and unpaywall_data.get('best_oa_location'):
                pdf_url = unpaywall_data['best_oa_location'].get('url_for_pdf')
        
        if not pdf_url and ss_data and ss_data.get('openAccessPdf'):
            pdf_url = ss_data['openAccessPdf'].get('url')
            
        if not pdf_url:
            ddg_pdfs = self.search_duckduckgo_pdf(title)
            if ddg_pdfs:
                pdf_url = ddg_pdfs[0]

        # 3. Context Extraction
        context = ""
        if pdf_url:
            pdf_path = self.download_pdf(pdf_url)
            if pdf_path:
                context = self.extract_text_from_pdf(pdf_path)
                if os.path.exists(pdf_path): os.remove(pdf_path)
        
        if not context and ss_data:
            context = ss_data.get('abstract', "")

        # 4. Evaluation
        status, reasoning, usage_context = self.evaluate_with_llm(title, context)
        
        # 5. Metadata extraction (Mock UIUC check)
        uiuc_affiliated = 1 if "illinois.edu" in context.lower() or "urbana-champaign" in context.lower() else 0
        
        system = 'Unknown'
        if 'deltaai' in trigger.lower(): system = 'DeltaAI'
        elif 'delta' in trigger.lower(): system = 'Delta'
        
        award_number = ""
        if "OAC-2005572" in context or "2005572" in context: award_number = "OAC-2005572"
        elif "OAC-2320345" in context or "2320345" in context: award_number = "OAC-2320345"

        data = {
            'title': title,
            'system': system,
            'alert_trigger': trigger,
            'status': status,
            'reasoning': reasoning,
            'usage_context': usage_context,
            'uiuc_affiliated': uiuc_affiliated,
            'uiuc_authors_depts': "", # Would be extracted by LLM
            'award_number': award_number,
            'doi_or_url': doi_url
        }
        
        self.upsert_citation(data)

if __name__ == "__main__":
    if len(sys.argv) > 2:
        title = sys.argv[1]
        trigger = sys.argv[2]
        ingestor = CitationIngestor()
        ingestor.process_alert(title, trigger)
    else:
        print("Usage: python3 ingest_alert.py \"Paper Title\" \"Trigger Phrase\"")
