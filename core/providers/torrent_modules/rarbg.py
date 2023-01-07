import datetime
import core
import logging
import time
from core.helpers import Url
import json

logging = logging.getLogger(__name__)

'''
https://torrentapi.org/apidocs_v2.txt

This api is limited to one request every 2 seconds.
'''

timeout = None
_api_token = None
_token_timeout = datetime.datetime.now()

def base_url():
    url = core.CONFIG['Indexers']['Torrent']['rarbg']['url']
    if not url:
        url = 'https://www.torrentapi.org'
    elif url[-1] == '/':
        url = url[:-1]
    return url

def _token():
    ''' Gets/sets token and monitors token timeout

    Returns str rarbg token
    '''
    global _api_token
    global _token_timeout

    if not _api_token:
        _api_token = _get_token()
    else:
        now = datetime.datetime.now()
        if (now - _token_timeout).total_seconds() > 900:
            _api_token = _get_token()
            _token_timeout = now
    return _api_token


def search(imdbid, term, ignore_if_imdbid_cap = False):
    ''' Search api for movie
    imdbid (str): imdb id #

    Returns list of dicts of parsed releases
    '''
    global timeout

    if ignore_if_imdbid_cap:
        return []
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    host = base_url()
    logging.info(f'Performing backlog search on Rarbg for {imdbid}.')
    if timeout:
        now = datetime.datetime.now()
        while timeout > now:
            time.sleep(1)
            now = datetime.datetime.now()

    try:
        url = f'{host}/pubapi_v2.php?token={_token()}&mode=search&search_imdb={imdbid}&category=14;48;17;44;45;47;50;51;52;42;46;54&format=json_extended&app_id=Watcher'

        timeout = datetime.datetime.now() + datetime.timedelta(seconds=2)

        if proxy_enabled and core.proxy.whitelist(host) is True:
            response = Url.open(url, proxy_bypass=True)
        else:
            response = Url.open(url)

        if response.status_code != 200:
            return [] # no need to log anything, Url.open already has logged a warning
        else:
            results = json.loads(response.text).get('torrent_results')
            if results:
                return _parse(results, imdbid=imdbid)
            else:
                logging.info('Nothing found on Rarbg')
                return []
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Rarbg search failed.', exc_info=True)
        return []


def get_rss():
    ''' Gets latest rss feed from api

    Returns list of dicts of parsed releases
    '''
    global timeout

    host = base_url()
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']

    logging.info('Fetching latest RSS from ')
    if timeout:
        now = datetime.datetime.now()
        while timeout > now:
            time.sleep(1)
            now = datetime.datetime.now()

    try:
        url = f'{host}/pubapi_v2.php?token={_token()}&mode=list&category=movies&format=json_extended&app_id=Watcher'
        timeout = datetime.datetime.now() + datetime.timedelta(seconds=2)

        if proxy_enabled and core.proxy.whitelist(host) is True:
            response = Url.open(url, proxy_bypass=True)
        else:
            response = Url.open(url)

        if response.status_code != 200:
            return [] # no need to log anything, Url.open already has logged a warning
        else:
            results = json.loads(response.text).get('torrent_results')
            if results:
                return _parse(results)
            else:
                logging.info('Nothing found in Rarbg RSS.')
                return []
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Rarbg RSS fetch failed, empty feed.', exc_info=False)
        return []


def _get_token():
    ''' Get api access token

    Returns str or None
    '''
    logging.info('Getting RarBG access token.')
    host = base_url()
    url = f'{host}/pubapi_v2.php?get_token=get_token&app_id=Watcher'

    try:
        result = json.loads(Url.open(url).text)
        token = result.get('token')
        return token
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Failed to get Rarbg token.', exc_info=True)
        raise RarbgTokenError(str(e))


def _parse(results, imdbid=None):
    ''' Parse api response
    results (list): dicts of releases

    Returns list of dicts
    '''

    logging.info(f'Parsing {len(results)} Rarbg results.')
    item_keep = ('size', 'pubdate', 'title', 'indexer', 'info_link', 'guid', 'torrentfile', 'resolution', 'type', 'seeders', 'leechers')

    parsed_results = []

    for result in results:
        result['indexer'] = 'Rarbg'
        if result['info_page']:
            result['info_link'] = result['info_page'] + '&app_id=Watcher'
        result['torrentfile'] = result['download']
        result['guid'] = result['download'].split('&')[0].split(':')[-1]
        result['type'] = 'magnet'
        result['pubdate'] = None

        result = {k: v for k, v in result.items() if k in item_keep}

        result['imdbid'] = imdbid or result.get('episode_info', {}).get('imdb')
        result['status'] = 'Available'
        result['score'] = 0
        result['downloadid'] = None
        result['freeleech'] = 0
        result['download_client'] = None
        parsed_results.append(result)

    logging.info(f'Found {len(parsed_results)} results from rarbg')
    return parsed_results


class RarbgTokenError(Exception):
    ''' Raised when a Rarbg token cannot be retrieved '''
    def __init__(self, msg=None):
        self.msg = msg if msg else 'Failed to retrieve new token from Rarbg\'s torrentapi.org.'
