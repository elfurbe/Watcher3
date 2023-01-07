from xml.etree.ElementTree import fromstring
from xmljson import yahoo
import core
from core.helpers import Url
from core.providers.base import NewzNabProvider
from core.providers import torrent_modules  # noqa
import logging

logging = logging.getLogger(__name__)


trackers = '&tr='.join(('udp://tracker.leechers-paradise.org:6969',
                       'udp://zer0day.ch:1337',
                       'udp://tracker.coppersurfer.tk:6969',
                       'udp://public.popcorn-tracker.org:6969',
                       'udp://open.demonii.com:1337/announce',
                       'udp://tracker.openbittorrent.com:80',
                       'udp://tracker.coppersurfer.tk:6969',
                       'udp://glotorrents.pw:6969/announce',
                       'udp://tracker.opentrackr.org:1337/announce',
                       'udp://torrent.gresille.org:80/announce',
                       'udp://p4p.arenabg.com:1337',
                       'udp://tracker.leechers-paradise.org:6969'
                       ))


def magnet(hash_, title):
    ''' Creates magnet link
    hash_ (str): base64 formatted torrent hash
    title (str): name of the torrent

    Formats as magnet uri and adds trackers

    Returns str margnet uri
    '''

    return f'magnet:?xt=urn:btih:{hash_}&dn={title}&tr={trackers}'


class Torrent(NewzNabProvider):

    def __init__(self):
        self.feed_type = 'torrent'
        return

    def search_all(self, imdbid, title, year, ignore_if_imdbid_cap = False):
        ''' Performs backlog search for all indexers.
        imdbid (str): imdb id #
        title (str): movie title
        year (str/int): year of movie release

        Returns list of dicts with sorted release information.
        '''

        torz_indexers = core.CONFIG['Indexers']['TorzNab'].values()

        results = []

        term = Url.normalize(f'{title} {year}')

        for indexer in torz_indexers:
            if indexer[2] is False:
                continue
            url_base = indexer[0]
            logging.info(f'Searching TorzNab indexer {url_base}')
            if url_base[-1] != '/':
                url_base = url_base + '/'
            apikey = indexer[1]
            no_year = indexer[3]

            caps = core.sql.torznab_caps(url_base)
            if not caps:
                caps = self._get_caps(url_base, apikey)
                if caps is None:
                    logging.error(f'Unable to get caps for {url_base}')
                    continue

            if 'imdbid' in caps:
                if ignore_if_imdbid_cap:
                    return results
                logging.info(f'{url_base} supports imdbid search.')
                r = self.search_newznab(url_base, apikey, 'movie', imdbid=imdbid)
            else:
                logging.info(f'{url_base} does not support imdbid search, using q={term}')
                r = self.search_newznab(url_base, apikey, 'search', q=term, imdbid=imdbid)
                if not r and no_year:
                    logging.info(f'{url_base} does not find anything, trying without year, using q={title}')
                    r = self.search_newznab(url_base, apikey, 'search', q=title, imdbid=imdbid)
            for i in r:
                results.append(i)

        for indexer, settings in core.CONFIG['Indexers']['Torrent'].items():
            if settings['enabled']:
                if not hasattr(torrent_modules, indexer):
                    logging.warning(f'Torrent indexer {indexer} enabled but not found in torrent_modules.')
                    continue
                else:
                    for i in getattr(torrent_modules, indexer).search(imdbid, term, ignore_if_imdbid_cap):
                        if i not in results:
                            results.append(i)

        for indexer, indexerobject in core.CONFIG['Indexers']['PrivateTorrent'].items():
            if indexerobject['enabled']:
                if not hasattr(torrent_modules, indexer):
                    logging.warning(f'Torrent indexer {indexer} enabled but not found in torrent_modules.')
                    continue
                else:
                    for i in getattr(torrent_modules, indexer).search(imdbid, term, ignore_if_imdbid_cap):
                        if i not in results:
                            results.append(i)

        return results

    def get_rss(self):
        ''' Gets rss from all torznab providers and individual providers

        Returns list of dicts of latest movies
        '''

        logging.info('Syncing Torrent indexer RSS feeds.')

        results = []

        results = self._get_rss()

        for indexer, settings in core.CONFIG['Indexers']['Torrent'].items():
            if settings['enabled']:
                if not hasattr(torrent_modules, indexer):
                    logging.warning(f'Torrent indexer {indexer} enabled but not found in torrent_modules.')
                    continue
                else:
                    for i in getattr(torrent_modules, indexer).get_rss():
                        if i not in results:
                            results.append(i)
        return results

    def _get_caps(self, url_base, apikey):
        ''' Gets caps for indexer url
        url_base (str): url of torznab indexer
        apikey (str): api key for indexer

        Gets indexer caps from CAPS table

        Returns list of caps
        '''

        logging.info(f'Getting caps for {url_base}')

        url = f'{url_base}api?apikey={apikey}&t=caps'

        try:
            xml = Url.open(url).text

            caps = yahoo.data(fromstring(xml))['caps']['searching']['movie-search']['supportedParams']

            core.sql.write('CAPS', {'url': url_base, 'caps': caps})
        except Exception as e:
            logging.warning('', exc_info=True)
            return None

        return caps.split(',')
