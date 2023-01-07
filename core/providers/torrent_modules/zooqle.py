import logging
import datetime
import xml.etree.ElementTree as ET
import core
from core.helpers import Url

logging = logging.getLogger(__name__)

'''
Does not supply rss feed -- backlog searches only.
'''

def base_url():
    url = core.CONFIG['Indexers']['Torrent']['zooqle']['url']
    if not url:
        url = 'https://zooqle.com'
    elif url[-1] == '/':
        url = url[:-1]
    return url

def search(imdbid, term, ignore_if_imdbid_cap = False):
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info('Searching Zooqle for {}.'.format(term))

    host = base_url()
    url = '{}/search?q={}&fmt=rss'.format(host, term)

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
        logging.error('Zooqle search failed.', exc_info=True)
        return []


def get_rss():
    return []


def _parse(xml, imdbid):
    logging.info('Parsing Zooqle results.')

    tree = ET.fromstring(xml)

    items = tree[0].findall('item')

    results = []
    for i in items:
        result = {}
        try:
            result['score'] = 0

            size, suffix = i.find('description').text.strip().split(', ')[-1].split(' ')
            m = (1024 ** 2) if suffix == 'MB' else (1024 ** 3)
            result['size'] = int(float(size.replace(',', '')) * m)

            result['status'] = 'Available'

            pd = i.find('pubDate').text
            result['pubdate'] = datetime.datetime.strftime(datetime.datetime.strptime(pd, '%a, %d %b %Y %H:%M:%S %z'), '%d %b %Y')

            result['title'] = i.find('title').text
            result['imdbid'] = imdbid
            result['indexer'] = 'Zooqle'
            result['info_link'] = i.find('guid').text
            result['torrentfile'] = i[9].text
            result['guid'] = i[8].text.lower()
            result['type'] = 'magnet'
            result['downloadid'] = None
            result['freeleech'] = 0
            result['download_client'] = None
            result['seeders'] = int(i[10].text)
            result['leechers'] = int(i[11].text)

            results.append(result)
        except Exception as e:
            logging.error('Error parsing Zooqle XML.', exc_info=True)
            continue

    logging.info('Found {} results from Zooqle.'.format(len(results)))
    return results
