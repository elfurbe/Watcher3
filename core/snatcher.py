import logging
import datetime
import urllib.parse
import core
from core import plugins
from core import downloaders
from core.helpers import Torrent
from core.library import Manage

logging = logging.getLogger(__name__)

'''
Handles snatching search results. This includes choosing the best result,
    retreiving the link, and sending it to the download client.

Clarification notes:

When snatching a torrent, the download id should *always* be the torrent hash.
When snatching NZBs use the client-supplied download id if possible. If the client
    does not return a download id use None.

'''


def grab_all():
    ''' Grabs best result for all movies in library

    Automatically determines which movies can be grabbed or re-grabbed and
        executes get_best_release() to find best result then sends release
        dict to download()

    Returns bool (False is no movies to grab, True if any movies were attempted)
    '''
    logging.info('Running automatic snatcher for all movies.')

    today = datetime.datetime.today()
    keepsearching = core.CONFIG['Search']['keepsearching']
    keepsearchingscore = core.CONFIG['Search']['keepsearchingscore']
    keepsearchingdays = core.CONFIG['Search']['keepsearchingdays']
    keepsearchingdelta = datetime.timedelta(days=keepsearchingdays)

    movies = core.sql.get_user_movies()
    if not movies:
        return False
    for movie in movies:
        status = movie['status']
        if status == 'Disabled':
            logging.debug('{} is Disabled, skipping.'.format(movie['title']))
            continue
        title = movie['title']
        year = movie['year']

        if status == 'Found':
            logging.info(f'{title} status is Found. Running automatic snatcher.')
            best_release = get_best_release(movie)
            if best_release:
                download(best_release)
            continue

        if status == 'Finished' and keepsearching is True:
            finished_date = movie['finished_date']
            if not finished_date:
                continue
            finished_date_obj = datetime.datetime.strptime(finished_date, '%Y-%m-%d')
            if finished_date_obj + keepsearchingdelta >= today:
                minscore = (movie.get('finished_score') or 0) + keepsearchingscore
                logging.info(f'{title} {year} was marked Finished on {finished_date}. Checking for a better release (min score {minscore}).')
                best = get_best_release(movie, minscore=minscore)
                if best:
                    download(best)
                continue
            else:
                continue
        else:
            continue
    logging.info('######### Automatic search/snatch complete #########')


def get_best_release(movie, minscore=0, ignore_guid=None):
    ''' Grabs the best scoring result that isn't 'Bad'
    movie (dict): movie info from local db
    minscore (int): minimum acceptable score for best release   <optional - default 0>

    Picks the best release that is available and above minscore threshold

    Returns dict of search result from local database
    '''

    logging.info('Selecting best release for {}'.format(movie['title']))

    try:
        imdbid = movie['imdbid']
        quality = movie['quality']
        year = movie['year']
        title = movie['title']
        release_date = movie['release_date']
    except Exception as e:  # noqa
        logging.error('Invalid movie data.', exc_info=True)
        return {}

    search_results = core.sql.get_search_results(imdbid, quality)
    if not search_results:
        logging.warning(f'Unable to automatically grab {imdbid}, no results.')
        return {}

    # Filter out any results we don't want to grab
    search_results = [i for i in search_results if i['type'] != 'import']
    if ignore_guid:
        search_results = [i for i in search_results if i['guid'] != ignore_guid]
    if not core.CONFIG['Downloader']['Sources']['usenetenabled']:
        search_results = [i for i in search_results if i['type'] != 'nzb']
    if not core.CONFIG['Downloader']['Sources']['torrentenabled']:
        search_results = [i for i in search_results if i['type'] not in ('torrent', 'magnet')]

    if not search_results:
        logging.warning(f'Unable to automatically grab {imdbid}, no results available for enabled download client.')
        return {}

    # Check if we are past the 'waitdays'
    today = datetime.datetime.today()
    release_weeks_old = (today - datetime.datetime.strptime(release_date, '%Y-%m-%d')).days / 7

    wait_days = core.CONFIG['Search']['waitdays']
    earliest_found = min([x['date_found'] for x in search_results])
    date_found = datetime.datetime.strptime(earliest_found, '%Y-%m-%d')
    if (today - date_found).days < wait_days:
        if core.CONFIG['Search']['skipwait'] and release_weeks_old > core.CONFIG['Search']['skipwaitweeks']:
                logging.info(f'{title} released {release_weeks_old} weeks ago, skipping wait and grabbing immediately.')
        else:
            logging.info(f'Earliest found result for {imdbid} is {date_found}, waiting {wait_days} days to grab best result.')
            return {}

    # Since seach_results comes back in order of score we can go through in
    # order until we find the first Available result and grab it.
    for result in search_results:
        result = dict(result)  # TODO why?
        status = result['status']
        result['year'] = year

        if status == 'Available' and result['score'] > minscore:
            logging.info('{} is best available result for {}'.format(result['title'], title))
            return result
        # if doing a re-search, if top ranked result is Snatched we have nothing to do.
        elif status in ('Snatched', 'Finished'):
            logging.info(f'Top-scoring release for {imdbid} has already been snatched.')
            return {}
        else:
            continue

    logging.warning(f'No Available results for {imdbid}.')
    return None


def download(data):
    ''' Sends release to download client
    data (dict): search result from local database

    Sends data to helper method snatch_nzb or snatch_torrent based on download type

    Executes snatched plugins if successful

    Returns dict from helper method snatch_nzb or snatch_torrent
    '''
    logging.info('Sending {} to download client.'.format(data['title']))

    if data['type'] == 'import':
        return {'response': False, 'error': 'Cannot download imports.'}

    imdbid = data['imdbid']
    resolution = data['resolution']
    kind = data['type']
    info_link = urllib.parse.quote(data['info_link'], safe='')
    indexer = data['indexer']
    title = data['title']
    year = data['year']

    if data['type'] == 'nzb':
        if core.CONFIG['Downloader']['Sources']['usenetenabled']:
            response = snatch_nzb(data)
        else:
            return {'response': False, 'message': 'NZB submitted but nzb snatching is disabled.'}

    if data['type'] in ('torrent', 'magnet'):
        if core.CONFIG['Downloader']['Sources']['torrentenabled']:
            response = snatch_torrent(data)
            if not response['response']:
                for result in core.sql.get_single_search_result('guid', data['guid'], all_indexers=True):
                    if result['indexer'] != indexer:
                        response = snatch_torrent(result)
                        if response['response'] is True:
                            break
        else:
            return {'response': False, 'message': 'Torrent submitted but torrent snatching is disabled.'}

    if response['response'] is True:
        download_client = response['download_client']
        downloadid = response['downloadid']

        plugins.snatched(title, year, imdbid, resolution, kind, download_client, downloadid, indexer, info_link)
        return response
    else:
        return response


def snatch_nzb(data):
    ''' Sends nzb to download client
    data (dict): search result from local database

    Returns dict {'response': True, 'message': 'lorem impsum'}
    '''
    guid = data['guid']
    imdbid = data['imdbid']
    title = data['title']

    for client, config in core.CONFIG['Downloader']['Usenet'].items():
        if config['enabled']:
            logging.info(f'Sending nzb to {client}')

            response = getattr(downloaders, client).add_nzb(data)

            if response['response']:
                logging.info(f'Successfully sent {title} to {client}.')

                db_update = {'downloadid': response['downloadid'], 'download_client': client}
                core.sql.update_multiple_values('SEARCHRESULTS', db_update, 'guid', guid)

                if update_status_snatched(guid, imdbid):
                    return {'response': True, 'message': f'Sent to {client}.', 'download_client': client, 'downloadid': response['downloadid']}
                else:
                    return {'response': False, 'error': 'Could not mark search result as Snatched.'}
            else:
                return response


def snatch_torrent(data):
    ''' Sends torrent or magnet to download client
    data (dict): search result from local database

    Returns dict {'response': True, 'message': 'lorem impsum'}
    '''
    guid = data['guid']
    imdbid = data['imdbid']
    title = data['title']
    kind = data['type']

    if urllib.parse.urlparse(guid).netloc:
        # if guid is not a url and not hash we'll have to get the hash now
        guid_ = Torrent.get_hash(data['torrentfile'])
        if not guid_:
            # torrent url may redirect to magnet uri
            guid_, magnet = Torrent.get_hash_and_magnet(data['torrentfile'])
            if magnet:
                data['torrentfile'] = magnet
                core.sql.update('SEARCHRESULTS', 'torrentfile', magnet, 'guid', guid)

        if guid_:
            core.sql.update('SEARCHRESULTS', 'guid', guid_.lower(), 'guid', guid)
            guid = guid_
        else:
            return {'response': False, 'error': 'Unable to get torrent hash from indexer.'}

    for client, config in core.CONFIG['Downloader']['Torrent'].items():
        if config['enabled']:
            logging.info(f'Sending {kind} to {client}')

            response = getattr(downloaders, client).add_torrent(data)

            if response['response']:
                logging.info(f'Successfully sent {title} to {client}.')

                db_update = {'downloadid': response['downloadid'], 'download_client': client}
                core.sql.update_multiple_values('SEARCHRESULTS', db_update, 'guid', guid)

                if update_status_snatched(guid, imdbid):
                    return {'response': True, 'message': f'Sent to {client}.', 'download_client': client, 'downloadid': response['downloadid']}
                else:
                    return {'response': False, 'error': 'Could not mark search result as Snatched.'}
            else:
                return response
    else:
        return {'response': False, 'error': 'No download client enabled.'}


def update_status_snatched(guid, imdbid):
    ''' Sets status to Snatched
    guid (str): guid for download link
    imdbid (str): imdb id #

    Updates MOVIES, SEARCHRESULTS, and MARKEDRESULTS to 'Snatched'

    Returns bool
    '''
    logging.info(f'Updating {imdbid} to Snatched.')

    if not Manage.searchresults(guid, 'Snatched'):
        logging.error('Unable to update search result status to Snatched.')
        return False

    if not Manage.markedresults(guid, 'Snatched', imdbid=imdbid):
        logging.error('Unable to store marked search result as Snatched.')
        return False

    if not Manage.movie_status(imdbid):
        logging.error('Unable to update movie status to Snatched.')
        return False

    return True
