import logging
import os
import core
from core.helpers import Url
from core.helpers import Torrent as th

logging = logging.getLogger(__name__)

bt_cache = ('https://itorrents.org/torrent/{}.torrent',
            'http://thetorrent.org/torrent/{}.torrent',
            'http://btdig.com/torrent/{}.torrent'
            )


def test_connection(data):
    ''' Tests ability to write to directory
    data (dict): blackhole settings

    Returns True on success or str error message on failure
    '''

    logging.info('Testing ability to write to blackhole directory {}'.format(data['directory']))

    directory = data['directory']

    if core.PLATFORM == '*nix':
        if os.access(directory, os.W_OK):
            return True
        else:
            logging.error(f'Unable to write to directory {directory}.')
            return f'Write access denied for {directory}.'
    else:
        try:
            tmp_file = os.path.join(directory, 'watcher.write')
            with open(tmp_file, 'w') as f:
                f.write('Watcher')
            os.remove(tmp_file)
        except Exception as e:
            logging.error(f'Unable to write to directory {directory}.', exc_info=True)
            return str(e)
        return True


def _download_link(url, file):
    ''' Downloads url to file
    url (str): url to downloadable file (nzb, torrent)
    file (str): absolute path to FILE in which to save url

    Returns bool
    '''

    try:
        dl_bytes = Url.open(url, stream=True).content
        with open(file, 'wb') as f:
            f.write(dl_bytes)
        del dl_bytes
    except Exception as e:
        logging.error(f'Could not download {url}.', exc_info=True)
        return False

    return True


def cancel_download(downloadid):
    ''' Placeholder method
    downloadid (int): download id

    This method does nothing. It simply exists so we don't throw an exception
        if it is called automatically.

    Returns True
    '''
    return True


def add_nzb(data):
    ''' Downloads NZB to blackhole directory
    data (dict): release information

    Returns dict ajax-style response
    '''

    conf = core.CONFIG['Downloader']['Usenet']['BlackHole']

    directory = conf['directory']
    fp = os.path.join(directory, '{}.nzb'.format(data['title']))

    if _download_link(data['guid'], fp):
        logging.info(f'NZB saved as {fp}.')
        return {'response': True, 'downloadid': None}
    else:
        logging.error('Could not download NZB.', exc_info=True)
        return {'response': False, 'error': 'Unable to download NZB.'}


def add_torrent(data):
    ''' Downloads Torrent/magnet to blackhole directory
    data (dict): release information

    Returns dict ajax-style response
    '''

    conf = core.CONFIG['Downloader']['Torrent']['BlackHole']

    directory = conf['directory']
    fp = os.path.join(directory, '{}.torrent'.format(data['title']))

    dl = False
    if data['type'] == 'magnet':
        dl = _download_magnet(data, fp)
    else:
        dl = _download_link(data['torrentfile'], fp)

    if dl:
        logging.info(f'Torrent saved as {fp}.')
        return {'response': True, 'downloadid': None}
    else:
        logging.error('Could not download Torrent.', exc_info=True)
        return {'response': False, 'error': 'Unable to download Torrent.'}


def _download_magnet(data, path):
    ''' Resolves magnet link to torrent file
    data (dict): release information
    file (str): absolute path to FILE in which to save file

    Attempts to use magnet2torrent.com to resolve to torrent file. If that fails,
        iterates through bt_cache sites and attempts to get download.

    The downloaded content is ran through bencode (via core.helpers.Torrent) to
        make sure the hash from the torrent file (or whatever content was download)
        matches the hash submitted.

    Returns bool
    '''
    magnet_hash = data['guid'].upper()

    try:
        logging.info('Attempting to resolve torrent hash through magnet2torrent.com')
        dl_bytes = Url.open('http://magnet2torrent.com/upload/', post_data={'magnet': f'magnet:?xt=urn:btih:{magnet_hash}'}, stream=True).content
        if _verify_torrent(dl_bytes, magnet_hash):
            logging.info('Torrent found on magnet2torrent.com')
            with open(path, 'wb') as f:
                f.write(dl_bytes)
            del dl_bytes
            return True
    except Exception as e:
        logging.warning('Unable to reach magnet2torrent.com', exc_info=True)

    for i in bt_cache:
        try:
            url = i.format(magnet_hash)
            logging.info(f'Attempting to resolve torrent hash through {url}')
            dl_bytes = Url.open(url, stream=True).content
            if _verify_torrent(dl_bytes, magnet_hash):
                logging.info(f'Torrent found at {url}')
                with open(path, 'wb') as f:
                    f.write(dl_bytes)
                del dl_bytes
                return True
            else:
                continue
        except Exception as e:
            logging.warning(f'Unable to resolve magnet hash through {i}.', exc_info=True)
            continue

    logging.warning(f'Torrent hash {magnet_hash} not found on any torrent cache.')

    logging.warning(f'Creating a torrent file from hash {magnet_hash}.')

    tf_elements = ['d10:magnet-uri',
                   'LENGTH',
                   'magnet:?xt=urn:btih:',
                   magnet_hash,
                   '&dn=',
                   magnet_hash,
                   '&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969%2Fannounce',
                   '&tr=udp%3A%2F%2F9.rarbg.com%3A2710%2Fannounce',
                   '&tr=udp%3A%2F%2Fp4p.arenabg.com%3A1337',
                   '&tr=udp%3A%2F%2Ftracker.leechers-paradise.org%3A6969',
                   '&tr=udp%3A%2F%2Ftracker.internetwarriors.net%3A1337',
                   '&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce',
                   '&tr=udp%3A%2F%2Ftracker.zer0day.to%3A1337%2Fannounce',
                   '&tr=udp%3A%2F%2Ftracker.leechers-paradise.org%3A6969%2Fannounce',
                   'e']

    # calculate and update the lenght of magnet file
    mlenght = 0

    for a in tf_elements[2:-1]:
        mlenght += len(a)

    tf_elements[1] = str(mlenght) + ":"

    torrent_file = "".join(tf_elements)

    with open(path, 'w') as f:
        f.write(torrent_file)
    return True


def _verify_torrent(stream, magnet):
    ''' Verifies torrent against magnet hash to make sure download is correct
    stream (str): bitstream of torrent file
    magnet (str): magnet hash to check against

    Returns Bool
    '''
    return magnet == th.get_hash(stream, file_bytes=True)
