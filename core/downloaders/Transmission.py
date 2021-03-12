import logging

from lib import transmissionrpc

import core
from datetime import datetime

logging = logging.getLogger(__name__)


def test_connection(data):
    ''' Tests connectivity to Transmission
    data: dict of Transmission server information

    Return True on success or str error message on failure
    '''

    logging.info('Testing connection to Transmission.')

    host = data['host']
    port = data['port']
    user = data['user']
    password = data['pass']

    try:
        client = transmissionrpc.Client(host, port, user=user, password=password)
        if type(client.rpc_version) == int:
            return True
        else:
            logging.warning('Unable to connect to TransmissionRPC.')
            return 'Unable to connect.'
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Unable to connect to TransmissionRPC.', exc_info=True)
        return '{}.'.format(e)


def add_torrent(data):
    ''' Adds torrent or magnet to Transmission
    data: dict of torrrent/magnet information

    Adds torrents to /default/path/<category>

    Returns dict {'response': True, 'downloadid': 'id'}
                    {'response': False', 'error': 'exception'}

    '''

    logging.info('Sending torrent {} to Transmission.'.format(data['title']))

    conf = core.CONFIG['Downloader']['Torrent']['Transmission']

    host = conf['host']
    port = conf['port']
    user = conf['user']
    password = conf['pass']

    client = transmissionrpc.Client(host, port, user=user, password=password)

    url = data['torrentfile']
    paused = conf['addpaused']
    category = conf['category']

    priority_keys = {
        'Low': '-1',
        'Normal': '0',
        'High': '1'
    }

    bandwidthPriority = priority_keys[conf['priority']]

    d = client.get_session().__dict__['_fields']['download_dir'][0]
    d_components = d.split('/')

    if category:
        d_components.append(category)

    download_dir = '/'.join(d_components)

    try:
        download = client.add_torrent(url, paused=paused, bandwidthPriority=bandwidthPriority, download_dir=download_dir, timeout=30)
        downloadid = download.hashString
        set_torrent_limits(download.id)
        logging.info('Torrent sent to TransmissionRPC - downloadid {}'.format(downloadid))
        return {'response': True, 'downloadid': downloadid}
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Unable to send torrent {} to TransmissionRPC.'.format(url), exc_info=True)
        return {'response': False, 'error': str(e)}

def set_torrent_limits(downloadid):
    ''' Set seedIdleLimit, seedIdleMode, seedRatioLimit and seedRatioMode
    according to transmission settings

    downloadid: int download id

    Returns bool
    '''
    conf = core.CONFIG['Downloader']['Torrent']['Transmission']
    idle_limit = conf.get('seedidlelimit', '')
    ratio_limit = conf.get('seedratiolimit', '')

    args = {}
    if idle_limit == -1:
        args['seedIdleMode'] = 2
        idle_limit_desc = 'unlimited'
    elif idle_limit == '':
        idle_limit_desc = 'global setting'
    else:
        args['seedIdleMode'] = 1
        args['seedIdleLimit'] = idle_limit_desc = int(idle_limit * 60)

    if ratio_limit == -1:
        args['seedRatioMode'] = 2
        ratio_limit_desc = 'unlimited'
    elif ratio_limit == '':
        ratio_limit_desc = 'global setting'
    else:
        args['seedRatioMode'] = 1
        args['seedRatioLimit'] = ratio_limit_desc = ratio_limit

    logging.info('Setting idle limit to {} and ratio limit to {} for torrent #{}'.format(idle_limit_desc, ratio_limit_desc, downloadid))

    if args:
        host = conf['host']
        port = conf['port']
        user = conf['user']
        password = conf['pass']

        try:
            client = transmissionrpc.Client(host, port, user=user, password=password)
            client.change_torrent(downloadid, **args)
            return True
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            logging.error('Unable to change torrent #{} in TransmissionRPC.'.format(downloadid), exc_info=True)
            return False
    else:
        return True

def get_torrents_status(stalled_for=None, progress={}):
    ''' Get torrents and calculate status

    Returns list
    '''
    conf = core.CONFIG['Downloader']['Torrent']['Transmission']

    logging.info('Get torrents from transmissionrpc')

    host = conf['host']
    port = conf['port']
    user = conf['user']
    password = conf['pass']

    try:
        torrents = []

        client = transmissionrpc.Client(host, port, user=user, password=password)

        now = int(datetime.timestamp(datetime.now()))
        fields = ['id', 'hashString', 'isFinished', 'isStalled', 'status', 'percentDone', 'name', 'downloadedEver']
        for torrent in client.get_torrents(arguments=fields):
            data = {'hash': torrent._fields['hashString'].value, 'status': torrent.status, 'name': torrent._get_name_string(), 'progress': torrent._fields['downloadedEver'].value}
            if torrent._fields['isFinished'].value:
                data['status'] = 'finished'
            elif torrent.status == 'downloading' and stalled_for and data['hash'] in progress:
                torrent_progress = progress[data['hash']]
                if data['progress'] == torrent_progress['progress'] and now > torrent_progress['time'] + stalled_for * 3600:
                    data['status'] = 'stalled'
            torrents.append(data)

        return torrents
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Unable to list torrents from TransmissionRPC.', exc_info=True)
        return []

def cancel_download(downloadid):
    ''' Cancels download in client
    downloadid: int download id

    Returns bool
    '''
    logging.info('Cancelling download # {} in Transmission.'.format(downloadid))

    conf = core.CONFIG['Downloader']['Torrent']['Transmission']

    host = conf['host']
    port = conf['port']
    user = conf['user']
    password = conf['pass']

    client = transmissionrpc.Client(host, port, user=user, password=password)

    try:
        client.remove_torrent([downloadid], delete_data=True)
        return True
    except Exception as e:
        logging.error('Unable to cancel download.', exc_info=True)
        return False
