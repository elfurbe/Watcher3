import core
import logging
from core.helpers import Url
from xml.etree.ElementTree import fromstring
from xmljson import yahoo
logging = logging.getLogger(__name__)

def base_url():
    url = core.CONFIG['Indexers']['Torrent']['torrentz2']['url']
    if not url:
        url = 'https://torrentz2.is'
    elif url[-1] == '/':
        url = url[:-1]
    return url

def search(imdbid, term, ignore_if_imdbid_cap = False):
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info('Performing backlog search on Torrentz2 for {}.'.format(imdbid))

    host = base_url()
    url = '{}/feed?f={}'.format(host, term)

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
        logging.error('Torrentz2 search failed.', exc_info=True)
        return []


def get_rss():
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info('Fetching latest RSS from Torrentz2.')

    host = base_url()
    url = '{}/feed?f=movies'.format(host)

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
        logging.error('Torrentz2 RSS fetch failed.', exc_info=True)
        return []


def _parse(xml, imdbid):
    logging.info('Parsing Torrentz2 results.')

    try:
        channel = yahoo.data(fromstring(xml))['rss']['channel']
        items = channel['item'] if 'item' in channel else []
    except Exception as e:
        logging.error('Unexpected XML format from Torrentz2.', exc_info=True)
        return []

    if isinstance(items, dict):
        # fix for parsing rss with one item only
        items = [items]

    results = []
    for i in items:
        result = {}
        try:                                                              
            if not i['title']:                                            
                continue
            desc = i['description'].split(' ')
            hash_ = desc[-1]

            m = (1024 ** 2) if desc[2] == 'MB' else (1024 ** 3)

            result['score'] = 0
            result['size'] = int(desc[1]) * m
            result['status'] = 'Available'
            result['pubdate'] = None
            result['title'] = i['title']
            result['imdbid'] = imdbid
            result['indexer'] = 'Torrentz2'
            result['info_link'] = i['link']
            result['torrentfile'] = core.providers.torrent.magnet(hash_, i['title'])
            result['guid'] = hash_
            result['type'] = 'magnet'
            result['downloadid'] = None
            result['seeders'] = int(desc[4])
            result['leechers'] = int(desc[6])
            result['download_client'] = None
            result['freeleech'] = 0

            results.append(result)
        except Exception as e:
            logging.error('Error parsing Torrentz2 XML.', exc_info=True)
            continue

    logging.info('Found {} results from Torrentz2.'.format(len(results)))
    return results
