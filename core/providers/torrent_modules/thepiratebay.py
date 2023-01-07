import logging
import core
from datetime import datetime
from core.helpers import Url
import json
import re

def base_url():
    url = core.CONFIG['Indexers']['Torrent']['thepiratebay']['url']
    if not url:
        url = 'https://www.thepiratebay.org'
    else:
        url = re.sub(r'/$', '', url) + '/newapi'
    return url

def search(imdbid, term, ignore_if_imdbid_cap = False):
    if ignore_if_imdbid_cap:
        return []
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info(f'Performing backlog search on ThePirateBay for {imdbid}.')

    host = base_url()
    url = f'{host}/q.php?q={imdbid}'
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
        logging.error('ThePirateBay search failed.', exc_info=True)
        return []


def get_rss():
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info('Fetching latest RSS from ThePirateBay.')

    host = base_url()
    url = f'{host}/q.php?q=category:201'
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
        logging.error('ThePirateBay RSS fetch failed.', exc_info=True)
        return []


def _parse(response, imdbid):
    logging.info('Parsing ThePirateBay results.')

    # proxies may require to set base_url to https://host/newapi/, but info_link must link to https://host/
    rows = json.loads(response)
    if len(rows) == 1 and re.match(r'0*$', rows[0].get('info_hash')):
        logging.info('Nothing found on ThePirateBay')
        return []

    host = re.sub(r'(https?://[^/]*).*', r'\1', base_url())
    results = []
    for row in rows:
        result = {}
        try:
            result['title'] = row['name']
            result['score'] = 0
            result['size'] = int(row['size'])
            result['status'] = 'Available'
            result['pubdate'] = datetime.fromtimestamp(int(row['added']))
            result['imdbid'] = imdbid
            result['indexer'] = 'ThePirateBay'
            result['info_link'] = '{}/description.php?id={}'.format(host, row['id'])
            result['guid'] = row['info_hash'].lower()
            result['torrentfile'] = core.providers.torrent.magnet(result['guid'], result['title'])
            result['type'] = 'magnet'
            result['downloadid'] = None
            result['download_client'] = None
            result['seeders'] = int(row['seeders'])
            result['leechers'] = int(row['leechers'])
            result['freeleech'] = 0

            results.append(result)
        except Exception as e:
            logging.error('Error parsing ThePirateBay JSON.', exc_info=True)
            continue

    logging.info(f'Found {len(results)} results from ThePirateBay.')
    return results
