import core
from xml.etree.ElementTree import fromstring
from xmljson import yahoo
import logging
from core.helpers import Url
import re

logging = logging.getLogger(__name__)

def base_url():
    url = core.CONFIG['Indexers']['Torrent']['limetorrents']['url']
    if not url:
        url = 'https://www.limetorrents.info'
    elif url[-1] == '/':
        url = url[:-1]
    return url

def search(imdbid, term, ignore_if_imdbid_cap = False):
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info(f'Performing backlog search on LimeTorrents for {imdbid}.')

    host = base_url()
    url = f'{host}/searchrss/{term}'

    try:
        if proxy_enabled and core.proxy.whitelist(host) is True:
            response = Url.open(url, proxy_bypass=True).text
        else:
            response = Url.open(url).text

        if response:
            return _parse(response, imdbid)
        else:
            return []
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('LimeTorrent search failed.', exc_info=True)
        return []


def get_rss():
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info('Fetching latest RSS from ')

    host = base_url()
    url = f'{host}/rss/16/'

    try:
        if proxy_enabled and core.proxy.whitelist(host) is True:
            response = Url.open(url, proxy_bypass=True).text
        else:
            response = Url.open(url).text

        if response:
            return _parse(response, None)
        else:
            return []
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('LimeTorrent RSS fetch failed.', exc_info=True)
        return []


def _parse(xml, imdbid):
    logging.info('Parsing LimeTorrents results.')

    try:
        rss = yahoo.data(fromstring(xml))['rss']['channel']
    except Exception as e:
        logging.error('Unexpected XML format from ', exc_info=True)
        return []

    if 'item' not in rss:
        logging.info("No result found in LimeTorrents")
        return []

    host = base_url()
    results = []
    for i in rss['item']:
        result = {}
        try:
            result['score'] = 0
            result['size'] = int(i['size'])
            result['status'] = 'Available'
            result['pubdate'] = None
            result['title'] = i['title']
            result['imdbid'] = imdbid
            result['indexer'] = 'LimeTorrents'
            if i['link'][0] == '/':
                result['info_link'] = host + i['link']
            else: # some proxies have wrong link url (https:https://...)
                result['info_link'] = re.sub(r'^(https:)+//', 'https://', i['link'])
            result['guid'] = i['enclosure']['url'].split('.')[-2].split('/')[-1].lower()
            if re.search(r'https?://itorrents\.org/', i['enclosure']['url']):
                result['torrentfile'] = core.providers.torrent.magnet(result['guid'], result['title'])
                result['type'] = 'magnet'
            else:
                result['torrentfile'] = i['enclosure']['url']
                result['type'] = 'torrent'
            result['downloadid'] = None
            result['freeleech'] = 0
            result['download_client'] = None

            # use 2 regular exprssions
            # search has Seeds: X , Leechers Y
            # rss has Seeds: X<br />Leechers: Y<br />
            desc = i['description']
            matches = re.findall("Seeds:? *([0-9]+)", desc)
            if matches:
                result['seeders'] = int(matches[0])
            else:
                result['seeders'] = 0

            matches = re.findall("Leechers:? *([0-9]+)", desc)
            if matches:
                result['leechers'] = int(matches[0])
            else:
                result['leechers'] = 0

            results.append(result)
        except Exception as e:
            logging.error('Error parsing LimeTorrents XML.', exc_info=True)
            continue

    logging.info(f'Found {len(results)} results from Limetorrents.')
    return results
