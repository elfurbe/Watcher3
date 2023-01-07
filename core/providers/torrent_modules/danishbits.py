import core
import logging
from core.helpers import Url
import json

logging = logging.getLogger(__name__)


def search(imdbid, term, ignore_if_imdbid_cap = False):
    ''' Search api for movie
    imdbid (str): imdb id #

    Returns list of dicts of parsed releases
    '''

    if ignore_if_imdbid_cap:
        return []
    proxy_enabled = core.CONFIG['Server']['Proxy']['enabled']
    username = core.CONFIG['Indexers']['PrivateTorrent']['danishbits']['username']
    passkey = core.CONFIG['Indexers']['PrivateTorrent']['danishbits']['passkey']

    logging.info(f'Performing backlog search on DanishBits for {imdbid}.')

    try:
        url = f'https://danishbits.org/couchpotato.php?user={username}&passkey={passkey}&imdbid={imdbid}'

        if proxy_enabled and core.proxy.whitelist('https://danishbits.org') is True:
            response = Url.open(url, proxy_bypass=True, expose_user_agent=True).text
        else:
            response = Url.open(url, expose_user_agent=True).text

        responseobject = json.loads(response)
        results = responseobject.get('results')

        if results:
            return _parse(results, imdbid=imdbid)
        else:
            logging.info('Nothing found on DanishBits')
            errormsg = responseobject.get('error')
            if errormsg:
                logging.info(f'Error message: {errormsg}')
            return []
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('DanishBits search failed.', exc_info=True)
        return []


def _parse(results, imdbid=None):
    ''' Parse api response
    results (list): dicts of releases

    Returns list of dicts
    '''

    logging.info(f'Parsing {len(results)} DanishBits results.')
    parsed_results = []

    for result in results:
        parsed_result = {}
        parsed_result['indexer'] = 'DanishBits'
        parsed_result['info_link'] = result['details_url']
        parsed_result['torrentfile'] = result['download_url']
        parsed_result['guid'] = result['torrent_id']
        parsed_result['type'] = 'torrent'
        parsed_result['pubdate'] = result['publish_date']
        parsed_result['seeders'] = result['seeders']
        parsed_result['leechers'] = result['leechers']
        parsed_result['size'] = result['size'] * 1000000

        parsed_result['imdbid'] = result['imdb_id']
        parsed_result['status'] = 'Available'
        parsed_result['score'] = 0
        parsed_result['downloadid'] = None
        parsed_result['freeleech'] = result.get('freeleech')
        parsed_result['download_client'] = None
        parsed_result['title'] = result['release_name']
        parsed_results.append(parsed_result)

    logging.info(f'Found {len(parsed_results)} results from DanishBits')
    return parsed_results
