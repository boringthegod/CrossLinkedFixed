import logging
import threading
from time import sleep
from bs4 import BeautifulSoup
from unidecode import unidecode
from urllib.parse import urlparse
from crosslinked.logger import Log
from datetime import datetime, timedelta

from camoufox.sync_api import Camoufox

csv = logging.getLogger('cLinked_csv')


class Timer(threading.Thread):
    def __init__(self, timeout):
        threading.Thread.__init__(self)
        self.start_time = None
        self.running = None
        self.timeout = timeout

    def run(self):
        self.running = True
        self.start_time = datetime.now()
        logging.debug("Thread Timer: Started")

        while self.running:
            if (datetime.now() - self.start_time) > timedelta(seconds=self.timeout):
                self.stop()
            sleep(0.05)

    def stop(self):
        logging.debug("Thread Timer: Stopped")
        self.running = False


class CrossLinked:
    def __init__(self, search_engine, target, timeout, conn_timeout=3, proxies=[], jitter=0):
        self.results = []
        self.url = {
            'google': 'https://www.google.com/search?q=site:linkedin.com/in+"{}"&num=100&start={}',
            'bing': 'http://www.bing.com/search?q="{}"+site:linkedin.com/in&first={}'
        }
        self.runtime = datetime.now().strftime('%m-%d-%Y %H:%M:%S')
        self.search_engine = search_engine
        self.conn_timeout = conn_timeout  # en secondes
        self.timeout = timeout
        self.target = target
        self.jitter = jitter

    def search(self):
        search_timer = Timer(self.timeout)
        search_timer.start()

        with Camoufox(headless=True) as browser:
            while search_timer.running:
                try:
                    url = self.url[self.search_engine].format(self.target, len(self.results))
                    page = browser.new_page()
                    response = page.goto(url, timeout=self.conn_timeout * 100000)
                    
                    if response is None:
                        Log.warn("Aucune réponse pour l'URL: {}".format(url))
                        page.close()
                        break

                    http_code = response.status
                    if http_code != 200:
                        Log.info("{:<3} {} ({})".format(len(self.results), url, http_code))
                        Log.warn("Réponse non 200, fin de la recherche ({})".format(http_code))
                        page.close()
                        break

                    content = page.content()
                    resp = type('Response', (), {'status_code': http_code, 'content': content})
                    
                    self.page_parser(resp)
                    Log.info("{:<3} {} ({})".format(len(self.results), url, http_code))
                    page.close()
                    sleep(self.jitter)
                except KeyboardInterrupt:
                    Log.warn("Interruption clavier détectée, fin de la recherche...")
                    break

        search_timer.stop()
        return self.results

    def page_parser(self, resp):
        for link in extract_links(resp):
            try:
                self.results_handler(link)
            except Exception as e:
                Log.warn("Erreur lors du parsing de {} - {}".format(link.get('href'), e))

    def link_parser(self, url, link):
        u = {'url': url}
        u['text'] = unidecode(link.text.split("|")[0].split("...")[0])
        u['title'] = self.parse_linkedin_title(u['text'])
        u['name'] = self.parse_linkedin_name(u['text'])
        return u

    def parse_linkedin_title(self, data):
        try:
            title = data.split("-")[1].split('https:')[0]
            return title.split("...")[0].split("|")[0].strip()
        except Exception:
            return 'N/A'

    def parse_linkedin_name(self, data):
        try:
            name = data.split("-")[0].strip()
            return unidecode(name).lower()
        except Exception:
            return False

    def results_handler(self, link):
        url = str(link.get('href')).lower()

        if not extract_subdomain(url).endswith('linkedin.com'):
            return False
        elif 'linkedin.com/in' not in url:
            return False

        data = self.link_parser(url, link)
        if data['name']:
            self.log_results(data)

    def log_results(self, d):
        if d in self.results:
            return
        elif 'linkedin.com' in d['name']:
            return

        self.results.append(d)
        logging.debug("name: {:25} RawTxt: {}".format(d['name'], d['text']))
        csv.info('"{}","{}","{}","{}","{}","{}"'.format(
            self.runtime, self.search_engine, d['name'], d['title'], d['url'], d['text']
        ))


def extract_links(resp):
    links = []
    soup = BeautifulSoup(resp.content, 'lxml')
    for link in soup.find_all('a'):
        links.append(link)
    return links


def extract_subdomain(url):
    return urlparse(url).netloc
