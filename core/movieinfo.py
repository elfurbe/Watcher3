import json
import logging
from time import time, sleep
import core
import os
import re
from core.helpers import Comparisons, Url
_k = Comparisons._k

logging = logging.getLogger(__name__)


class TheMovieDatabase:
    tokens = 30             # int initial amount of tokens for TMDB rate limiting
    last_token_fill = time()      # float epoch time of last token fill
    token_capacity = 30     # int max number of tokens. TMDB allows more, but artificially restricting the hit rate doesn't hurt

    @staticmethod
    def _get_tokens():
        ''' Refills TMDB tokens if possible

        If tokens are needed, checks if they've been refilled in the
            last 10 seconds and tops off the capacity.

        Returns int # of tmdb tokens available
        '''
        if TheMovieDatabase.tokens < TheMovieDatabase.token_capacity:
            now = time()
            if (now - TheMovieDatabase.last_token_fill) > 10:
                TheMovieDatabase.tokens = TheMovieDatabase.token_capacity
                TheMovieDatabase.last_token_fill = time()
        return TheMovieDatabase.tokens

    @staticmethod
    def _use_token():
        ''' Uses tmdb api token

        Used as a blocking method before url requests.
        If remaining tokens are fewer than 3 waits for refill.

        Does not return
        '''
        while TheMovieDatabase._get_tokens() < 3:
            sleep(0.3)
        TheMovieDatabase.tokens -= 1

    @staticmethod
    def search(search_term, single=False):
        ''' Search TMDB for all matches
        search_term (str): title of movie to search for
        single (bool): return only first result         <optional - default False>

        Can accept imdbid, title, or title+year and dispatches accordingly.

        Passes term to find_imdbid or find_title depending on the data recieved.

        Returns list of dicts of individual movies from the find_x function.
        '''

        logging.info(f'Searching TheMovieDB for {search_term}')

        if re.match('^tt[0-9]{7,9}$', search_term):
            movies = TheMovieDatabase._search_imdbid(search_term)
        elif re.match(r'^imdb:\s*tt[0-9]{7,8}\s*$', search_term):
            movies = TheMovieDatabase._search_imdbid(search_term[5:].strip())
        elif re.match(r'^tmdb:\s*[0-9]+\s*$', search_term):
            movies = TheMovieDatabase._search_tmdbid(search_term[5:].strip())
            if movies and 'status' in movies[0]:
                # watcher thinks movie is already added when it has status, so we don't want status in search result
                movies[0].pop('status')
        else:
            movies = TheMovieDatabase._search_title(search_term)

        if not movies:
            logging.info(f'Nothing found on TheMovieDatabase for {search_term}')
            return []
        if single:
            return movies[0:1]
        else:
            return movies

    @staticmethod
    def _search_title(title):
        ''' Search TMDB for title
        title (str): movie title

        Title can include year ie Move Title 2017

        Returns list of results
        '''

        logging.info(f'Searching TheMovieDB for title: {title}.')

        title = Url.normalize(title)

        url = 'https://api.themoviedb.org/3/search/movie?page=1&include_adult={}&'.format('true' if core.CONFIG['Search']['allowadult'] else 'false')
        if len(title) > 4 and title[-4:].isdigit():
            query = f'query={title[:-5]}&year={title[-4:]}'
        else:
            query = f'query={title}'

        url = url + query
        logging.info(f'Searching TMDB {url}')
        url = url + '&api_key={}'.format(_k(b'tmdb'))

        TheMovieDatabase._use_token()

        try:
            results = json.loads(Url.open(url).text)
            if results.get('success') == 'false':
                return []
            else:
                return results['results'][:6]
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            logging.error('Error searching for title on TMDB.', exc_info=True)
            return []

    @staticmethod
    def _search_imdbid(imdbid):
        ''' Search TMDB for imdb id #
        imdbid (str): imdb id #

        Returns list of results
        '''

        logging.info(f'Searching TheMovieDB for IMDB ID: {imdbid}.')

        url = f'https://api.themoviedb.org/3/find/{imdbid}?language=en-US&external_source=imdb_id&append_to_response=alternative_titles,external_ids,release_dates'

        logging.info(f'Searching TMDB {url}')
        url = url + '&api_key={}'.format(_k(b'tmdb'))

        TheMovieDatabase._use_token()

        try:
            results = json.loads(Url.open(url).text)
            if results['movie_results'] == []:
                return []
            else:
                response = results['movie_results'][0]
                response['imdbid'] = imdbid
                return [response]
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            logging.error('Error searching for IMDBID on TMDB.', exc_info=True)
            return []

    @staticmethod
    def _search_tmdbid(tmdbid, language=None):
        ''' Search TMDB for tmdbid
        tmdbid (str): themoviedatabase id #

        Returns list of results
        '''

        logging.info(f'Searching TheMovieDB for TMDB ID: {tmdbid}.')

        url = f'https://api.themoviedb.org/3/movie/{tmdbid}?language=en-US&append_to_response=alternative_titles,external_ids,release_dates'

        if (language):
            url += ',translations'
        logging.info(f'Searching TMDB {url}')
        url += '&api_key={}'.format(_k(b'tmdb'))

        TheMovieDatabase._use_token()

        try:
            response = Url.open(url)
            if response.status_code != 200:
                logging.warning(f'Unable to reach TMDB, error {response.status_code}')
                return []
            else:
                results = json.loads(response.text)
                results['imdbid'] = results.pop('imdb_id')
                if language:
                    results = TheMovieDatabase.process_language_info(results, language)
                logging.warning('TMDB returned imdbid as {}'.format(results['imdbid']))
                if results['imdbid'] == 'N/A' or results['imdbid'] == '':
                    logging.warning('TMDB did not have an IMDBid for this movie')
                    return []
                else:
                    return [results]
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            logging.error('Error searching for TMDBID on TMDB.', exc_info=True)
            return []

    @staticmethod
    def process_language_info(result, language):
        ''' Search alternative title for country in language, or translation for language
         sets lang_titles and change overview with translated overview if translation is found
        result (dict): data for movie
        language (str): language in format lang_code-country_code (iso 639-1 and iso 3166-1)

        Returns list of results
        '''

        lang, country = language.split('-')
        if result['original_language'] == lang:
            result['title'] = result['original_title']
            logging.debug(f'Requested lang {lang} is original language')
        else:
            result['lang_titles'] = set()
            for title in result.get('alternative_titles', {}).get('titles', []):
                if title['iso_3166_1'] == country:
                    result['lang_titles'].add(title['title'])
            logging.debug('Found {} titles in language {}'.format(len(result['lang_titles']), lang))

        for translation in result.get('translations', {}).get('translations', []):
            if translation['iso_3166_1'] == country and translation['iso_639_1'] == lang:
                logging.debug(f'Found translation for lang {lang}-{country}')
                if 'lang_titles' in result and translation['data'].get('title'):
                    result['lang_titles'].add(translation['data']['title'])
                if translation['data'].get('overview'):
                    result['overview'] = translation['data']['overview']
                break

        result.pop('translations')
        if 'lang_titles' in result:
            result['english_title'] = result['title'] # set english title, if no lang titles they are equal
            result['lang_titles'] = list(result['lang_titles']) # set can't be returned in ajax request
            if result['lang_titles']:
                result['title'] = result['lang_titles'][0]
            else:
                # no translation was found, so setting lang_titles to default title only
                # lang_titles will be used for alternative_titles, and they are supposed to be in requested language
                result['lang_titles'].append(result['title'])
        return result

    @staticmethod
    def get_imdbid(tmdbid=None, title=None, year=''):
        ''' Gets imdbid from tmdbid or title and year
        tmdbid (str): themoviedatabase id #
        title (str): movie title
        year (str/int): year of movie release

        MUST supply either tmdbid or title. Year is optional with title, but results
            are more reliable with it.

        Returns str imdbid
        '''

        if not tmdbid and not title:
            logging.warning('Neither tmdbid or title supplied. Unable to find imdbid.')
            return ''

        if not tmdbid:
            title = Url.normalize(title)
            year = Url.normalize(year)

            url = 'https://api.themoviedb.org/3/search/movie?api_key={}&language=en-US&query={}&year={}&page=1&include_adult={}'.format(_k(b'tmdb'), title, year, 'true' if core.CONFIG['Search']['allowadult'] else 'false')

            TheMovieDatabase._use_token()

            try:
                results = json.loads(Url.open(url).text)
                results = results['results']
                if results:
                    tmdbid = results[0]['id']
                else:
                    return ''
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as e:
                logging.error('Error attempting to get TMDBID from TMDB.', exc_info=True)
                return ''

        url = 'https://api.themoviedb.org/3/movie/{}?api_key={}'.format(tmdbid, _k(b'tmdb'))

        TheMovieDatabase._use_token()

        try:
            results = json.loads(Url.open(url).text)
            return results.get('imdb_id')
        except Exception as e:
            logging.error('Error attempting to get IMDBID from TMDB.', exc_info=True)
            return ''

    @staticmethod
    def get_category(cat, tmdbid=None):
        ''' get popular movies from TMDB
        cat (str): category of movies to retrieve
        tmdbid (str): tmdb id# to use for suggestions or similar

        tmdbid required for section=similar, otherwise can be ignored.

        Gets list of movies in cat from tmdbid (ie popular, now playing, coming soon, etc)

        Returns list[dict]
        '''

        if cat == 'similar':
            if tmdbid is None:
                return []
            url = f'https://api.themoviedb.org/3/movie/{tmdbid}/similar?&language=en-US&page=1'
        else:
            url = f'https://api.themoviedb.org/3/movie/{cat}?language=en-US&page=1'

        url += '&api_key={}'.format(_k(b'tmdb'))

        TheMovieDatabase._use_token()

        try:
            results = json.loads(Url.open(url).text)
            if results.get('success') == 'false':
                logging.warning('Bad request to TheMovieDatabase.')
                return []
            else:
                return results['results']
        except Exception as e:
            logging.error(f'Unable to read {cat} movies from TheMovieDB.', exc_info=True)
            return []


class YouTube:

    @staticmethod
    def trailer(title_date):
        ''' Gets trailer embed ID from Youtube.
        title_date (str): movie title and date ('Movie Title 2016')

        Attempts to connect 3 times in case Youtube is down or not responding
        Can fail if no response is received.

        Returns str
        '''

        logging.info(f'Getting trailer url from YouTube for {title_date}')

        search_term = Url.normalize(title_date + '+trailer')

        url = 'https://www.googleapis.com/youtube/v3/search?part=snippet&q={}&maxResults=1&key={}'.format(search_term, _k(b'youtube'))

        tries = 0
        while tries < 3:
            try:
                results = json.loads(Url.open(url).text)
                return results['items'][0]['id']['videoId']
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as e:
                if tries == 2:
                    logging.error('Unable to get trailer from Youtube.', exc_info=True)
                tries += 1
        return ''


class Poster:

    folder = os.path.join(core.POSTER_DIR)

    if not os.path.exists(folder):
        os.makedirs(folder)

    @staticmethod
    def save(imdbid, poster):
        ''' Saves poster locally
        imdbid (str): imdb id #
        poster (str): url of poster image.jpg

        Saves poster as watcher/userdata/posters/[imdbid].jpg

        Does not return
        '''

        logging.info(f'Downloading poster for {imdbid}.')

        new_poster_path = os.path.join(Poster.folder, f'{imdbid}.jpg')

        if os.path.exists(new_poster_path):
            logging.warning(f'{new_poster_path} already exists.')
            return
        else:
            logging.info(f'Saving poster to {new_poster_path}')

            try:
                poster_bytes = Url.open(poster, stream=True).content
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as e:
                logging.error('Poster save_poster get', exc_info=True)
                return

            try:
                with open(new_poster_path, 'wb') as output:
                    output.write(poster_bytes)
                del poster_bytes
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as e:
                logging.error('Unable to save poster to disk.', exc_info=True)
                return

            logging.info(f'Poster saved to {new_poster_path}')

    @staticmethod
    def remove(imdbid):
        ''' Deletes poster from disk.
        imdbid (str): imdb id #

        Does not return
        '''

        logging.info(f'Removing poster for {imdbid}')
        path = os.path.join(Poster.folder, f'{imdbid}.jpg')
        if os.path.exists(path):
            os.remove(path)
        else:
            logging.warning(f'{path} doesn\'t exist, cannot remove.')
