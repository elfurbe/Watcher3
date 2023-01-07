import logging
import re

from lib.deluge_client import DelugeRPCClient
from datetime import datetime

import core

logging.getLogger('lib.deluge_client').setLevel(logging.CRITICAL)
logging = logging.getLogger(__name__)

label_fix = re.compile(r'[^a-z0-9_ -]')


def test_connection(config):
    ''' Tests connectivity to deluge daemon rpc
    config: dict of deluge server information

    Tests if we can open a socket to the rpc and creates DelugeRPC.client if successful

    Returns Bool True on success or str error message on failure
    '''

    logging.info('Testing connection to DelugeRPC')

    host = config['host']
    port = config['port']
    user = config['user']
    password = config['pass']

    client = DelugeRPCClient(host, port, user, password)
    try:
        error = client.connect()
        if error:
            return f'{error}.'
    except Exception as e:
        logging.error('Unable to connect to Deluge RPC.', exc_info=True)
        return str(e)
    else:
        return True


def add_torrent(torrent):
    ''' Adds torrent or magnet to Deluge
    torrent: dict of torrrent/magnet information

    Returns dict {'response': True, 'downloadid': 'id'}
                    {'response': False, 'error': 'exception'}

    '''

    logging.info('Sending torrent {} to DelugeRPC.'.format(torrent['title']))

    conf = core.CONFIG['Downloader']['Torrent']['DelugeRPC']

    host = conf['host']
    port = conf['port']
    user = conf['user']
    password = conf['pass']

    client = DelugeRPCClient(host, port, user, password)

    try:
        error = client.connect()
        if error:
            return {'response': False, 'error': error}
    except Exception as e:
        logging.error('Deluge Add Torrent.', exc_info=True)
        return {'response': False, 'error': str(e)}

    try:
        def_download_path = client.call('core.get_config')[b'download_location'].decode('utf-8')
    except Exception as e:
        logging.error('Unable to get download path.', exc_info=True)
        return {'response': False, 'error': 'Unable to get download path.'}

    download_path = '{}/{}'.format(def_download_path, conf['category'])

    priority_keys = {
        'Low': 64,
        'Normal': 128,
        'High': 255,
    }

    options = {}
    options['add_paused'] = conf['addpaused']
    options['download_location'] = download_path
    options['priority'] = priority_keys[conf['priority']]
    ratio_limit = conf.get('seedratiolimit', '')
    if ratio_limit != '':
        options['stop_at_ratio'] = True
        options['stop_ratio'] = ratio_limit
    elif ratio_limit == -1:
        torrent['options']['stop_at_ratio'] = False
    if conf.get('removetorrents'):
        options['remove_at_ratio'] = True

    if torrent['type'] == 'magnet':
        try:
            downloadid = client.call('core.add_torrent_magnet', torrent['torrentfile'], options).decode('utf-8')
        except Exception as e:
            logging.error('Unable to send magnet.', exc_info=True)
            return {'response': False, 'error': str(e)}
    elif torrent['type'] == 'torrent':
        try:
            downloadid = (client.call('core.add_torrent_url', torrent['torrentfile'], options) or b'').decode('utf-8')
        except Exception as e:
            logging.error('Unable to send torrent.', exc_info=True)
            return {'response': False, 'error': str(e)}
    else:
        return {'response': False, 'error': 'Invalid torrent type {}'.format(torrent['type'])}

    _set_label(downloadid, conf['category'], client)

    return {'response': True, 'downloadid': downloadid}


def cancel_download(downloadid):
    ''' Cancels download in client
    downloadid: int download id
    Returns bool
    '''
    logging.info(f'Cancelling DelugeRPC download # {downloadid}')

    conf = core.CONFIG['Downloader']['Torrent']['DelugeRPC']

    host = conf['host']
    port = conf['port']
    user = conf['user']
    password = conf['pass']

    client = DelugeRPCClient(host, port, user, password)

    try:
        client.connect()
        return client.call('core.remove_torrent', downloadid, True)
    except Exception as e:
        logging.error('Unable to cancel download.', exc_info=True)
        return False


def _set_label(torrent, label, client):
    ''' Sets label for download
    torrent: str hash of torrent to apply label
    label: str name of label to apply
    client: object DelugeRPCClient instance

    Returns Bool
    '''

    label = label_fix.sub('', label.lower())

    logging.info(f'Applying label {label} to torrent {torrent} in DelugeRPC.')

    try:
        deluge_labels = client.call('label.get_labels')
    except Exception as e:
        logging.error('Unable to get labels from DelugeRPC.', exc_info=True)
        deluge_labels = []

    if label not in deluge_labels:
        logging.info(f'Adding label {label} to Deluge')
        try:
            client.call('label.add', label)
        except Exception as e:
            logging.error('Unable to add Deluge label.', exc_info=True)
            return False

    try:
        l = client.call('label.set_torrent', torrent, label)
        if l == b'Unknown Label':
            logging.error(f'Unknown label {label}')
            return False
    except Exception as e:
        logging.error('Unable to set Deluge label.', exc_info=True)
        return False

    return True

def get_torrents_status(stalled_for=None, progress={}):
    ''' Get torrents and calculate status

    Returns list
    '''
    conf = core.CONFIG['Downloader']['Torrent']['DelugeRPC']

    logging.info('Get torrents from DelugeRPC')

    host = conf['host']
    port = conf['port']
    user = conf['user']
    password = conf['pass']

    client = DelugeRPCClient(host, port, user, password)

    try:
        client.connect()

        torrents = []
        now = int(datetime.timestamp(datetime.now()))
        fields = ['hash', 'state', 'name', 'last_seen_complete', 'time_since_download', 'total_payload_download', 'active_time']
        for id, torrent in client.call('core.get_torrents_status', {'id': list(progress.keys())}, fields).items():
            # deluge return empty hash for every requested hash, even when it's missing
            if not torrent:
                continue
            logging.debug(torrent)
            data = {'hash': torrent[b'hash'].decode(), 'status': torrent[b'state'].lower().decode(), 'name': torrent[b'name'].decode()}
            if data['status'] == 'downloading' and stalled_for:
                if b'last_seen_complete' in torrent and b'time_since_download' in torrent: # deluge 2.x
                    if torrent[b'last_seen_complete'] == 0 or now > torrent[b'last_seen_complete'] + stalled_for * 3600:
                        if torrent[b'time_since_download'] != -1 and torrent[b'time_since_download'] > stalled_for * 3600 or \
                                torrent[b'time_since_download'] == -1 and torrent[b'active_time'] > stalled_for * 3600:
                            data['status'] = 'stalled'
                elif data['hash'] in progress: # deluge 1.x
                    data['progress'] = torrent[b'total_payload_download']
                    torrent_progress = progress[data['hash']]
                    if data['progress'] == torrent_progress['progress'] and \
                            now > torrent_progress['time'] + stalled_for * 3600:
                        data['status'] = 'stalled'

            torrents.append(data)

        return torrents
    except Exception as e:
        logging.error('Unable to list torrents from DelugeRPC.', exc_info=True)
        return []