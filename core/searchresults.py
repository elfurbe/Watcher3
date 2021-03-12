import logging
import datetime
import PTN

from base64 import b16encode
import core
from core.helpers import Url
import json
import re

logging = logging.getLogger(__name__)


def score(releases, imdbid=None, imported=False):
    ''' Scores and filters scene releases
    releases (list): dicts of release metadata to score
    imdbid (str): imdb identification number                    <optional -default None>
    impored (bool): indicate if search result is faked import   <optional -default False>

    If imported is True imdbid can be ignored. Otherwise imdbid is required.

    If imported, uses modified 'base' quality profile so releases
        cannot be filtered out.

    Iterates over the list and filters movies based on Words.
    Scores movie based on reslution priority, title match, and
        preferred words,

    Word groups are split in to a list of lists:
    [['word'], ['word2', 'word3'], 'word4']

    Adds 'score' key to each dict in releases and applies score.

    Returns list of result dicts
    '''
    if len(releases) == 0:
        logging.info('No releases to score.')
        return releases

    logging.info('Scoring {} releases.'.format(len(releases)))

    if imdbid is None and imported is False:
        logging.warning('Imdbid required if result is not library import.')
        return releases

    year = None
    title = None

    if imported:
        logging.debug('Releases are of origin "Import", using custom default quality profile.')
        titles = []
        check_size = False
        movie_details = {}
        filters = {'requiredwords': '', 'preferredwords': '', 'ignoredwords': ''}
   
        quality = core.CONFIG['Quality']['Profiles'][core.config.default_profile()]
        #quality = import_quality()
   
        category = {'requiredwords': '', 'preferredwords': '', 'ignoredwords': ''}
    else:
        movie_details = core.sql.get_movie_details('imdbid', imdbid)
        quality_profile = movie_details['quality']
        category_name = movie_details['category']
        logging.debug('Scoring based on quality profile {}'.format(quality_profile))
        check_size = True
        year = movie_details.get('year')
        title = movie_details.get('title').lower()

        quality = core.CONFIG['Quality']['Profiles'][core.config.default_profile()]

        if category_name in core.CONFIG['Categories']:
            category = core.CONFIG['Categories'][category_name]
        else:
            category = {'requiredwords': '', 'preferredwords': '', 'ignoredwords': ''}

        filters = json.loads(movie_details['filters'])

    sources = quality['Sources']

    required_groups = words_to_list(quality['requiredwords']) + words_to_list(filters['requiredwords']) + words_to_list(category['requiredwords'])
    preferred_groups = words_to_list(quality['preferredwords']) + words_to_list(filters['preferredwords']) + words_to_list(category['preferredwords'])
    ignored_groups = words_to_list(quality['ignoredwords']) + words_to_list(filters['ignoredwords']) + words_to_list(category['ignoredwords'])
    if movie_details.get('download_language'):
        lang_names = [lang.lower() for lang in core.config.lang_names(movie_details.get('download_language'))]
        logging.debug('remove {} names from ignored groups: {}'.format(movie_details['download_language'], lang_names))
        ignored_groups = [group for group in ignored_groups if not ' '.join(group).lower() in lang_names]
    else:
        lang_names = []

    # Begin scoring and filtering
    reset(releases)
    if ignored_groups and ignored_groups != ['']:
        if title:
            ignored_groups = [word_group for word_group in ignored_groups if not all(word in title for word in word_group)]
            logging.debug('ignored groups not in movie title: {}'.format(ignored_groups))
        releases = remove_ignored(releases, ignored_groups)

    if required_groups and required_groups != ['']:
        releases = keep_required(releases, required_groups)

    if core.CONFIG['Search']['retention'] > 0 and any(i['type'] == 'nzb' for i in releases):
        releases = retention_check(releases)

    if any(i['type'] in ('torrent', 'magnet') for i in releases):
        if core.CONFIG['Search']['mintorrentseeds'] > 0:
            releases = seed_check(releases)
        if core.CONFIG['Search']['freeleechpoints'] > 0 or core.CONFIG['Search']['requirefreeleech']:
            releases = freeleech(releases)
        if core.CONFIG['Search']['seederspoints'] and core.CONFIG['Search']['seedersthreshold']:
            releases = threshold_score(releases, 'seeders', core.CONFIG['Search']['seederspoints'], core.CONFIG['Search']['seedersthreshold'])
        if core.CONFIG['Search']['leecherspoints'] and core.CONFIG['Search']['leechersthreshold']:
            releases = threshold_score(releases, 'leechers', core.CONFIG['Search']['leecherspoints'], core.CONFIG['Search']['leechersthreshold'])

    releases = score_sources(releases, sources, check_size=check_size)
    if year:
        releases = score_year(releases, int(year))

    if quality['scoretitle']:
        titles = [movie_details.get('title')]
        if movie_details.get('alternative_titles'):
            titles += movie_details['alternative_titles'].split(',')
        releases = fuzzy_title(releases, titles, movie_details.get('english_title'), lang_names)

    if preferred_groups and preferred_groups != ['']:
        releases = score_preferred(releases, preferred_groups)

    logging.info('Finished scoring releases.')

    return releases

def words_to_list(words):
    return [i.split('&') for i in words.lower().replace(' ', '').split(',') if i != '']

def reset(releases):
    ''' Sets all result's scores to 0, and clear reject reason
    releases (dict): scene release metadata to score

    returns dict
    '''
    logging.debug('Resetting release scores to 0, and clear reject reasons.')
    for i, d in enumerate(releases):
        releases[i]['score'] = 0
        releases[i]['reject_reason'] = None


def remove_ignored(releases, group_list):
    ''' Set reject_reason for releases with ignored groups of 'words'
    releases (list[dict]): scene release metadata to score and filter
    group_list (list[list[str]]): forbidden groups of words

    group_list must be formatted as a list of lists ie:
        [['word1'], ['word2', 'word3']]

    Iterates through releases and removes every entry that contains any
        group of words in group_list

    Returns list[dict]
    '''

    reject = 0

    logging.info('Filtering Ignored Words.')
    for r in releases:
        if r['reject_reason']:
            reject += 1
            continue
        if r['type'] == 'import':
            continue
        for word_group in group_list:
            if all(word in r['title'].lower() for word in word_group):
                logging.debug('{} found in {}, removing from releases.'.format(word_group, r['title']))
                r['reject_reason'] = 'ignored words found ({})'.format(' '.join(word_group))
                reject += 1
                break

    logging.info('Keeping {} releases.'.format(len(releases) - reject))

    return releases


def keep_required(releases, group_list):
    ''' Set reject_reason for releases without required groups of 'words'
    releases (list[dict]): scene release metadata to score and filter
    group_list (list[list[str]]): required groups of words

    group_list must be formatted as a list of lists ie:
        [['word1'], ['word2', 'word3']]

    Iterates through releases and rejects every entry that does not
        contain any group of words in group_list

    Returns list[dict]
    '''

    reject = 0

    logging.info('Filtering Required Words.')
    logging.debug('Required Words: {}'.format(str(group_list)))
    for r in releases:
        if r['reject_reason']:
            reject += 1
            continue
        if r['type'] == 'import':
            continue
        required_group = False
        for word_group in group_list:
            if all(word in r['title'].lower() for word in word_group):
                logging.debug('{} found in {}, keeping this search result.'.format(word_group, r['title']))
                required_group = True
                break

        if not required_group:
            r['reject_reason'] = 'required words missing'
            reject += 1

    logging.info('Keeping {} releases.'.format(len(releases) - reject))

    return releases


def retention_check(releases):
    ''' Set reject_reason for releases older than 'retention' days
    releases (list[dict]): scene release metadata to score and filter
    retention (int): days of retention limit

    Iterates through releases and removes any nzb entry that was
        published more than 'retention' days ago

    returns list[dict]
    '''

    today = datetime.datetime.today()

    logging.info('Checking retention [threshold = {} days].'.format(core.CONFIG['Search']['retention']))
    reject = 0
    for result in releases:
        if result['reject_reason']:
            reject += 1
            continue
        if result['type'] == 'nzb':
            pubdate = datetime.datetime.strptime(result['pubdate'], '%d %b %Y')
            age = (today - pubdate).days
            if age >= core.CONFIG['Search']['retention']:
                logging.debug('{} published {} days ago, removing search result.'.format(result['title'], age))
                result['reject_reason'] = 'older than retention ({})'.format(core.CONFIG['Search']['retention'])
                reject += 1

    logging.info('Keeping {} releases.'.format(len(releases) - reject))
    return releases


def seed_check(releases):
    ''' Set reject_reason for any torrents with fewer than 'seeds' seeders
    releases (list[dict]): scene release metadata to score and filter

    Gets required seeds from core.CONFIG

    Returns list[dict]
    '''

    logging.info('Checking torrent seeds.')
    reject = 0
    for result in releases:
        if result['reject_reason']:
            reject += 1
            continue
        if result['type'] in ('torrent', 'magnet'):
            if int(result['seeders']) < core.CONFIG['Search']['mintorrentseeds']:
                logging.debug('{} has {} seeds, removing search result.'.format(result['title'], result['seeders']))
                result['reject_reason'] = 'not enough seeds ({})'.format(core.CONFIG['Search']['mintorrentseeds'])
                reject += 1

    logging.info('Keeping {} releases.'.format(len(releases) - reject))
    return releases


def freeleech(releases):
    ''' Adds points to freeleech torrents
    releases (list[dict]): scene release metadata to score and filter

    Returns list[dict]
    '''
    logging.info('Checking torrent Freeleech info.')
    points = core.CONFIG['Search']['freeleechpoints']
    reject = 0
    for release in releases[:]:
        if release['reject_reason']:
            reject += 1
            continue
        if not release['type'] in ('magnet', 'torrent'):
            continue
        if release['freeleech'] == 1:
            if core.CONFIG['Search']['requirefreeleech']:
                continue
            logging.debug('Adding {} Freeleech points to {}.'.format(points, release['title']))
            release['score'] += points
        elif core.CONFIG['Search']['requirefreeleech']:
            logging.debug('{} is not Freeleech, rejecting search result.'.format(release['title']))
            release['reject_reason'] = 'freeleech required'
            reject += 1

    logging.info('Keeping {} releases.'.format(len(releases) - reject))
    return releases


def threshold_score(releases, attr, points, threshold):
    ''' Adds points to releases if attr is greater than threshold
    releases (list[dict]): scene release metadata to score
    attr (str): attr in release to check
    points (int): points to add to score
    threshold (int): value to compare attr against

    Returns list[dict]
    '''
    logging.info('Comparing torrent {} with {}.'.format(attr, threshold))
    for release in releases[:]:
        try:
            if attr in release and release[attr] > threshold:
                release['score'] += points
        except TypeError:
            logging.warn('{} is not int ({})'.format(attr, release))

    return releases


def score_preferred(releases, group_list):
    ''' Increase score for each group of 'words' match
    releases (list[dict]): scene release metadata to score and filter
    group_list (list): preferred groups of words

    group_list must be formatted as a list of lists ie:
        [['word1'], ['word2', 'word3']]

    Iterates through releases and adds 10 points to every
        entry for each word group it contains

    Returns list[dict]
    '''

    logging.info('Scoring Preferred Words.')

    if not group_list or group_list == ['']:
        return

    for r in releases:
        for word_group in group_list:
            if all(word in r['title'].lower() for word in word_group):
                logging.debug('{} found in {}, adding 10 points.'.format(word_group, r['title']))
                r['score'] += 10
            else:
                continue
    return releases

def score_year(releases, year):
    ''' Increase score for each group of 'words' match
    releases (list[dict]): scene release metadata to score and filter
    year (int): expected year

    Iterates through releases and adds 20 points to every
        entry with exact year match
    Keeps releases without year or 1 year higher or lower.

    Returns list[dict]
    '''

    logging.info('Checking year match.')

    reject = 0

    for r in releases:
        if r['reject_reason']:
            reject += 1
            continue
        if 'ptn' not in r:
            r['ptn'] = PTN.parse(r['title'])
        if 'year' in r['ptn']:
            if r['ptn']['year'] == year:
                r['score'] += 20
            if abs(year - r['ptn']['year']) > 1:
                reject += 1
                r['reject_reason'] = 'Year mismatch'
        else:
            logging.debug('No year mismatch found')
            continue

    return releases


def fuzzy_title(releases, titles, english_title, lang_names):
    ''' Score and remove releases based on title match
    releases (list[dict]): scene release metadata to score and filter
    titles (list): titles to match against

    If titles is an empty list every result is treated as a perfect match

    Iterates through releases and removes any entry that does not
        fuzzy match 'title' > 70.
    Adds fuzzy_score / 20 points to ['score']

    Returns list[dict]
    '''

    logging.info('Checking title match.')

    reject = 0
    if titles == [] or titles == [None]:
        logging.debug('No titles available to compare, scoring all as perfect match.')
        for result in releases:
            if result['reject_reason']:
                reject += 1
                continue
            result['score'] += 20
    else:
        titles = [title for title in titles if title != english_title]
        for result in releases:
            if result['reject_reason']:
                reject += 1
                continue
            if result['type'] == 'import':
                logging.debug('{} is an Import, sorting as a perfect match.'.format(result['title']))
                result['score'] += 20
                continue

            rel_title_ss = result.get('ptn', PTN.parse(result['title']))['title']

            if titles:
                logging.debug('Comparing release substring {} with titles {}.'.format(rel_title_ss, titles))
                matches = [_fuzzy_title(rel_title_ss, title) for title in titles]
                if any(match > 70 for match in matches):
                    result['score'] += int(max(matches) / 5)
                    continue
            else:
                matches = [0]

            if english_title and any(re.search(r'\b' + lang + r'\b', result['title'].lower()) for lang in lang_names):
                logging.debug('Comparing release substring {} with english title {}.'.format(rel_title_ss, english_title))
                match = _fuzzy_title(rel_title_ss, english_title)
                if match > 70:
                    result['score'] += int(match / 5)
                    continue
                else:
                    matches.append(match)

            logging.debug('{} best title match was {}%, removing search result.'.format(result['title'], max(matches)))
            result['reject_reason'] = 'mismatch title (best match was {}%)'.format(max(matches))
            reject += 1

    logging.info('Keeping {} releases.'.format(len(releases) - reject))
    return releases

def _fuzzy_title(a, b):
    ''' Determines how much of a is in b
    a (str): String to match against b
    b (str): String to match a against

    Order of a and b matters.

    A is broken down and words are compared against B's words.

    ie:
    _fuzzy_title('This is string a', 'This is string b and has extra words.')
    Returns 75 since 75% of a is in b.

    Returns int
    '''

    a = a.replace('&', 'and')
    b = b.replace('&', 'and')
    a = a.replace('\'', '')
    b = b.replace('\'', '')
    a = a.replace(':', '')
    b = b.replace(':', '')

    a_words = Url.normalize(a).split(' ')
    b_words = Url.normalize(b).split(' ')

    m = 0
    a_len = len(a_words)

    for i in a_words:
        if i in b_words:
            b_words.remove(i)
            m += 1

    return int((m / a_len) * 100)


def score_sources(releases, sources, check_size=True):
    ''' Score releases based on quality/source preferences
    releases (list[dict]): scene release metadata to score and filter
    sources (dict): sources from user config
    check_size (bool): whether or not to set reject reason based on size

    Iterates through releases and removes any entry that does not
        fit into quality criteria (source-resoution, filesize)
    Adds to ['score'] based on priority of match

    Returns list[dict]
    '''

    logging.info('Filtering resolution and size requirements.')
    score_range = len(core.SOURCES) + 1

    sizes = core.CONFIG['Quality']['Sources']

    reject = 0
    for result in releases:
        if result['reject_reason']:
            reject += 1
            continue
        result_res = result['resolution']
        logging.debug('Scoring and filtering {} based on resolution {}.'.format(result['title'], result_res))
        size = result['size'] / 1000000
        if result['type'] == 'import' and result_res not in sources:
            continue

        accepted = False
        for k, v in sources.items():
            if v[0] is False and result['type'] != 'import':
                continue
            priority = v[1]
            if check_size:
                min_size = sizes[k]['min']
                max_size = sizes[k]['max']
            else:
                min_size = 0
                max_size = Ellipsis

            if result_res == k:
                logging.debug('{} matches source {}, checking size.'.format(result['title'], k))

                if result['type'] != 'import' and not (min_size < size < max_size):
                    logging.debug('Removing {}, size {} not in range {}-{}.'.format(result['title'], size, min_size, max_size))
                    result['reject_reason'] = 'size {} not in range {}-{}'.format(size, min_size, max_size)
                    reject += 1
                    break

                result['score'] += abs(priority - score_range) * 40
                accepted = True
                break

        if not accepted and not result['reject_reason']:
            result['reject_reason'] = 'source not accepted ({})'.format(result_res)
            reject += 1

    logging.info('Keeping {} releases.'.format(len(releases) - reject))
    return releases


def import_quality():
    ''' Creates quality profile for imported releases

    Creates import profile that mimics the base profile, but it incapable
        of removing releases.

    Returns dict
    '''
    profile = core.config.base_profile

    profile['ignoredwords'] = ''
    profile['requiredwords'] = ''

    for i in profile['Sources']:
        profile['Sources'][i][0] = True

    return profile


def generate_simulacrum(movie):
    ''' Generates phony search result for imported movies
    movie (dict): movie info

    movie will use 'release_title' key if found, else 'title' to generate fake release

    Resturns dict to match SEARCHRESULTS table
    '''

    logging.info('Creating "fake" search result for imported movie {}'.format(movie['title']))

    result = {'status': 'Finished',
              'info_link': '#',
              'pubdate': None,
              'title': None,
              'imdbid': movie['imdbid'],
              'torrentfile': None,
              'indexer': 'Library Import',
              'date_found': str(datetime.date.today()),
              'score': None,
              'type': 'import',
              'downloadid': None,
              'guid': None,
              'resolution': movie.get('resolution'),
              'size': movie.get('size') or 0,
              'releasegroup': movie.get('releasegroup') or '',
              'freeleech': 0
              }

    title = '{}.{}.{}.{}.{}.{}'.format(movie['title'],
                                       movie['year'],
                                       movie.get('resolution') or '.',  # Kind of a hacky way to make sure it doesn't print None in the title
                                       movie.get('audiocodec') or '.',
                                       movie.get('videocodec') or '.',
                                       movie.get('releasegroup') or '.'
                                       )

    while len(title) > 0 and title[-1] == '.':
        title = title[:-1]

    while '..' in title:
        title = title.replace('..', '.')

    result['title'] = title

    result['guid'] = movie.get('guid') or 'import{}'.format(b16encode(title.encode('ascii', errors='ignore')).decode('utf-8').zfill(16)[:16]).lower()

    return result
