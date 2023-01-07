import logging
import json
import re
import core
from core.helpers import Torrent, Url
from datetime import datetime

cookie = None
command_id = 0

label_fix = re.compile('[^a-z0-9_-]')

headers = {'Content-Type': 'application/json', 'User-Agent': 'Watcher'}

logging = logging.getLogger(__name__)


def test_connection(data):
    ''' Tests connectivity to deluge web client
    data: dict of deluge server information


    Return True on success or str error message on failure
    '''

    logging.info('Testing connection to Deluge Web UI.')

    host = data['host']
    port = data['port']
    password = data['pass']

    url = f'{host}:{port}/json'

    return _login(url, password)


def add_torrent(data):
    ''' Adds torrent or magnet to deluge web api
    data (dict): torrrent/magnet information

    Adds torrents to default/path/<category>

    Returns dict ajax-style response
    '''
    global command_id

    logging.info('Sending torrent {} to Deluge Web UI.'.format(data['title']))

    conf = core.CONFIG['Downloader']['Torrent']['DelugeWeb']

    host = conf['host']
    port = conf['port']
    url = f'{host}:{port}/json'

    priority_keys = {
        'Low': 64,
        'Normal': 128,
        'High': 255,
    }

    if cookie is None:
        if _login(url, conf['pass']) is not True:
            return {'response': False, 'error': 'Incorrect usename or password.'}

    download_dir = _get_download_dir(url)

    if not download_dir:
        return {'response': False, 'error': 'Unable to get path information.'}
    # if we got download_dir we can connect.

    download_dir = '{}/{}'.format(download_dir, conf['category'])

    # if file is a torrent, have deluge download it to a tmp dir
    if data['type'] == 'torrent':
        tmp_torrent_file = _get_torrent_file(data['torrentfile'], url)
        if tmp_torrent_file['response'] is True:
            torrent = {'path': tmp_torrent_file['torrentfile'], 'options': {}}
        else:
            return {'response': False, 'error': tmp_torrent_file['error']}
    else:
        torrent = {'path': data['torrentfile'], 'options': {}}

    torrent['options']['add_paused'] = conf['addpaused']
    torrent['options']['download_location'] = download_dir
    torrent['options']['priority'] = priority_keys[conf['priority']]
    ratio_limit = conf.get('seedratiolimit', '')
    if ratio_limit != '':
        torrent['options']['stop_at_ratio'] = True
        torrent['options']['stop_ratio'] = ratio_limit
    elif ratio_limit == -1:
        torrent['options']['stop_at_ratio'] = False
    if conf.get('removetorrents'):
        torrent['options']['remove_at_ratio'] = True

    command = {'method': 'web.add_torrents',
               'params': [[torrent]],
               'id': command_id
               }
    command_id += 1

    post_data = json.dumps(command)
    headers['cookie'] = cookie

    try:
        response = Url.open(url, post_data=post_data, headers=headers)
        response = json.loads(response.text)
        if response['result'] is True: # maybe Deluge Web 1.x returned true, 2.x returns array of array
            downloadid = Torrent.get_hash(data['torrentfile'])
        elif isinstance(response['result'], list) and isinstance(response['result'][0], list) and\
                len(response['result'][0]) == 2 and response['result'][0][0] is True:
            downloadid = response['result'][0][1]
        else:
            return {'response': False, 'error': response['error']}
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Delugeweb add_torrent', exc_info=True)
        return {'response': False, 'error': str(e)}

    _set_label(downloadid, conf['category'], url)

    return {'response': True, 'downloadid': downloadid}


def _set_label(torrent, label, url):
    ''' Sets label for download
    torrent: str hash of torrent to apply label
    label: str name of label to apply
    url: str url of deluge web interface

    Returns bool
    '''
    global command_id

    label = label_fix.sub('', label.lower()).replace(' ', '')

    logging.info(f'Applying label {label} to torrent {torrent} in Deluge Web UI.')

    command = {'method': 'label.get_labels',
               'params': [],
               'id': command_id
               }
    command_id += 1

    try:
        response = Url.open(url, post_data=json.dumps(command), headers=headers).text
        deluge_labels = json.loads(response).get('result') or []
    except Exception as e:
        logging.error('Unable to get labels from Deluge Web UI.', exc_info=True)
        return False

    if label not in deluge_labels:
        logging.info(f'Adding label {label} to Deluge.')
        command = {'method': 'label.add',
                   'params': [label],
                   'id': command_id
                   }
        command_id += 1
        try:
            sc = Url.open(url, post_data=json.dumps(command), headers=headers).status_code
            if sc != 200:
                logging.error(f'Deluge Web UI response {sc}.')
                return False
        except Exception as e:
            logging.error('Delugeweb get_labels.', exc_info=True)
            return False
    try:
        command = {'method': 'label.set_torrent',
                   'params': [torrent.lower(), label],
                   'id': command_id
                   }
        command_id += 1
        sc = Url.open(url, post_data=json.dumps(command), headers=headers).status_code
        if sc != 200:
            logging.error(f'Deluge Web UI response {sc}.')
            return False
    except Exception as e:
        logging.error('Delugeweb set_torrent.', exc_info=True)
        return False

    return True


def _get_torrent_file(torrent_url, deluge_url):
    global command_id

    command = {'method': 'web.download_torrent_from_url',
               'params': [torrent_url],
               'id': command_id
               }
    command_id += 1
    post_data = json.dumps(command)
    headers['cookie'] = cookie
    try:
        response = Url.open(deluge_url, post_data=post_data, headers=headers)
        response = json.loads(response.text)
        if response['error'] is None:
            return {'response': True, 'torrentfile': response['result']}
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Delugeweb download_torrent_from_url', exc_info=True)
        return {'response': False, 'error': str(e)}


def _get_download_dir(url):
    global command_id

    logging.debug('Getting default download dir from Deluge Web UI.')

    command = {'method': 'core.get_config_value',
               'params': ['download_location'],
               'id': command_id
               }
    command_id += 1

    post_data = json.dumps(command)

    headers['cookie'] = cookie

    try:
        response = Url.open(url, post_data=post_data, headers=headers)
        response = json.loads(response.text)
        return response['result']
    except Exception as e:
        logging.error('delugeweb get_download_dir', exc_info=True)
        return {'response': False, 'error': str(e)}


def _login(url, password):
    global command_id
    global cookie

    logging.info('Logging in to Deluge Web UI.')

    command = {'method': 'auth.login',
               'params': [password],
               'id': command_id
               }
    command_id += 1

    post_data = json.dumps(command)

    try:
        response = Url.open(url, post_data=post_data, headers=headers)
        cookie = response.headers.get('Set-Cookie')

        if cookie is None:
            return 'Incorrect password.'

        body = json.loads(response.text)
        if body['error'] is None:
            return True
        else:
            return response.msg

    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('DelugeWeb test_connection', exc_info=True)
        return f'{e}.'


def cancel_download(downloadid):
    global command_id

    logging.info(f'Cancelling download {downloadid} in Deluge Web UI')

    conf = core.CONFIG['Downloader']['Torrent']['DelugeWeb']

    host = conf['host']
    port = conf['port']
    url = f'{host}:{port}/json'

    if cookie is None:
        _login(url, conf['pass'])

    command = {'method': 'core.remove_torrent',
               'params': [downloadid.lower(), True],
               'id': command_id
               }
    command_id += 1

    post_data = json.dumps(command)

    headers['cookie'] = cookie

    try:
        response = Url.open(url, post_data=post_data, headers=headers)
        response = json.loads(response.text)
        return response['result']
    except Exception as e:
        logging.error('delugeweb get_download_dir', exc_info=True)
        return {'response': False, 'error': str(e)}

def get_torrents_status(stalled_for=None, progress={}):
    ''' Get torrents and calculate status

    Returns list
    '''
    global command_id
    conf = core.CONFIG['Downloader']['Torrent']['DelugeWeb']

    logging.info(f'Get torrents from DelugeWeb: {list(progress.keys())}')

    host = conf['host']
    port = conf['port']
    url = f'{host}:{port}/json'

    if cookie is None:
        _login(url, conf['pass'])

    fields = ['hash', 'state', 'last_seen_complete', 'name', 'time_since_download', 'total_payload_download', 'active_time']
    command = {'method': 'core.get_torrents_status',
               'params': [{'id': list(progress.keys())}, fields],
               'id': command_id
               }
    command_id += 1

    post_data = json.dumps(command)

    headers['cookie'] = cookie

    try:
        torrents = []
        now = int(datetime.timestamp(datetime.now()))
        response = Url.open(url, post_data=post_data, headers=headers)
        response = json.loads(response.text)
        logging.debug(f'Response keys: {list(response.keys())}')
        logging.debug(response)
        for id, torrent in response.get('result', {}).items():
            # deluge return empty hash for every requested hash, even when it's missing
            if not torrent:
                continue
            logging.debug(torrent)
            data = {'hash': torrent['hash'], 'status': torrent['state'].lower(), 'name': torrent['name']}
            if data['status'] == 'downloading' and stalled_for:
                if 'last_seen_complete' in torrent and 'time_since_download' in torrent: # deluge 2.x
                    if torrent['last_seen_complete'] == 0 or now > torrent['last_seen_complete'] + stalled_for * 3600:
                        if torrent['time_since_download'] != -1 and torrent['time_since_download'] > stalled_for * 3600 or \
                                torrent['time_since_download'] == -1 and torrent['active_time'] > stalled_for * 3600:
                            data['status'] = 'stalled'
                elif data['hash'] in progress: # deluge 1.x
                    data['progress'] = torrent['total_payload_download']
                    torrent_progress = progress[data['hash']]
                    if data['progress'] == torrent_progress['progress'] and \
                            now > torrent_progress['time'] + stalled_for * 3600:
                        data['status'] = 'stalled'

            torrents.append(data)

        return torrents
    except Exception as e:
        logging.error('Unable to list torrents from DelugeWeb', exc_info=True)
        return []
