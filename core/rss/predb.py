import logging
import xml.etree.ElementTree as ET

import core
from core.helpers import Url
from stringscore import liquidmetal as lm

logging = logging.getLogger(__name__)


def check_all():
    ''' Checks all movies for predb status

    Simply loops through MOVIES table and executes backlog_search if
        predb column is not '1'

    Returns bool
    '''

    logging.info('Checking predb.me for new available releases.')

    movies = core.sql.get_user_movies()
    if not movies:
        return False

    backlog_movies = [i for i in movies if i['predb_backlog'] != '1' and i['status'] not in ('Disabled', 'Finished')]
    rss_movies = [i for i in movies if i['predb_backlog'] == '1' and i['predb'] != 'found' and i['status'] != 'Disabled']

    if backlog_movies:
        logging.info('Performing predb backlog search for {}'.format(', '.join(i['title'] for i in backlog_movies)))
        for movie in backlog_movies:
            backlog_search(movie)

    if rss_movies:
        _search_rss(rss_movies)


def backlog_search(movie):
    ''' Searches predb for releases and marks row in MOVIES
    data (dict): data from row in MOVIES

    'data' requires key 'title', 'year', 'imdbid'

    Searches predb backlog for releases. Marks row predb:'found' and status:'Wanted'
        if found. Marks predb_backlog:1 as long as predb url request doesn't fail.

    Returns dict movie info after updating with predb results
    '''

    title = movie['title']
    year = str(movie['year'])
    title_year = f'{title} {year}'
    imdbid = movie['imdbid']

    logging.info(f'Checking predb.me for verified releases for {title}.')

    predb_titles = _search_db(title_year)

    db_update = {'predb_backlog': 1}

    if predb_titles:
        if _fuzzy_match(predb_titles, title, year):
            logging.info(f'{title} {year} found on predb.me.')
            db_update['predb'] = 'found'

    movie.update(db_update)
    core.sql.update_multiple_values('MOVIES', db_update, 'imdbid', imdbid)

    return movie


def _search_db(title_year):
    ''' Helper for backlog_search
    title_year (str): movie title and year 'Black Swan 2010'

    Returns list of found predb entries
    '''

    title_year = Url.normalize(title_year, ascii_only=True)

    categories = 'movies'
    if core.CONFIG['Search'].get('predb_unknown'):
        categories += ',unknown'
    url = f'http://predb.me/?cats={categories}&search={title_year}&rss=1'

    try:
        response = Url.open(url).text
        results_xml = response.replace('&', '%26')
        items = _parse_predb_xml(results_xml)
        return items
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Predb.me search failed.', exc_info=True)
        return []


def _search_rss(movies):
    ''' Search rss feed for applicable releases
    movies: list of dicts of movies

    If found, marks movie in database as predb:'found' and status:'Wanted'

    Does not return
    '''

    logging.info('Checking predb rss for {}'.format(', '.join(i['title'] for i in movies)))

    try:
        categories = 'movies'
        if core.CONFIG['Search'].get('predb_unknown'):
            categories += ',unknown'
        feed = Url.open(f'https://predb.me/?cats={categories}&rss=1').text
        items = _parse_predb_xml(feed)

        for movie in movies:
            title = movie['title']
            year = str(movie['year'])
            imdbid = movie['imdbid']

            if _fuzzy_match(items, title, year):
                logging.info(f'{title} {year} found on predb.me RSS.')
                core.sql.update('MOVIES', 'predb', 'found', 'imdbid', imdbid)
                continue
    except Exception as e:
        logging.error('Unable to read predb rss.', exc_info=True)


def _parse_predb_xml(feed):
    ''' Helper function to parse predb xmlrpclib
    feed (str): rss feed text

    Returns list of items with 'title' in tag
    '''

    root = ET.fromstring(feed)

    # This so ugly, but some newznab sites don't output json.
    items = []
    for item in root.iter('item'):
        for i_c in item:
            if i_c.tag == 'title':
                items.append(i_c.text)
    return items


def _fuzzy_match(predb_titles, title, year):
    ''' Fuzzy matches title with predb titles
    predb_titles (list): titles in predb response
    title (str): title to match to rss titles
    year (str): year of movie release

    Checks for any fuzzy match over 60%

    Returns bool
    '''

    movie = Url.normalize(f'{title}.{year}', ascii_only=True).replace(' ', '.')
    for pdb in predb_titles:
        if year not in pdb:
            continue
        pdb = pdb.split(year)[0] + year
        match = lm.score(pdb.replace(' ', '.'), movie) * 100
        if match > 60:
            logging.debug(f'{pdb} matches {movie} at {int(match)}%')
            return True
    return False
