""" This collector retrieves inode data from netapp filers

    !Thread-safe!

    The following metrics are measured in this diamond collector:
        * number of inodes per volume ()
        * current inode max (One inode per block; 4kB blocks)

        Config File:
            [devices]
            [[filer-corp-201]] <--- You can have as many filers as you want!
            ip = 192.168.1.45
            user = netapp_monitor
            password = b0bl0rd!

"""

import diamond.collector
from diamond.metric import Metric

try:
    import xml.etree.ElementTree as ET
    ET  # workaround for pyflakes issue #13
except ImportError:
    import cElementTree as ET

try:
    from netappsdk.NaServer import *
    from netappsdk.NaElement import *
except ImportError:
    netappsdk = None


__author__ = 'peter@phyn3t.com'


class netapp_inodeCol(object):
    """ Our netapp_inode Collector
    """

    def __init__(self, device, ip, user, password, prefix, pm):
        """Instantiate _our_ stuff
        """

        self.device = device
        self.ip = ip
        self.netapp_user = user
        self.netapp_password = password
        self.path_prefix = prefix
        self.publish_metric = pm
        self._netapp_login()

        filers_xml = self.get_netapp_data()

        for volume in filers_xml:
            max_inodes = volume.find('files-total').text
            used_inodes = volume.find('files-used').text
            volume = volume.find('name').text
            self.push('max_inodes', max_inodes, volume)
            self.push('used_inodes', used_inodes, volume)

    def push(self, metric_name=None, metric_value=None, volume=None):
        """ Ship that shit off to graphite broski
        """

        graphite_path = self.path_prefix
        graphite_path += '.' + self.device + '.' + 'volume'
        graphite_path += '.' + volume + '.' + metric_name

        metric = Metric(graphite_path, metric_value, precision=4,
                        host=self.device)

        self.publish_metric(metric)

    def get_netapp_data(self):
        """ Retrieve netapp volume information

            returns ElementTree of netapp volume information

        """

        netapp_data = self.server.invoke('volume-list-info')

        if netapp_data.results_status() == 'failed':
            self.log.error(
                'While using netapp API failed to retrieve '
                'volume-list-info for netapp filer %s' % self.device)
            return

        netapp_xml = ET.fromstring(netapp_data.sprintf()).find('volumes')

        return netapp_xml

    def _netapp_login(self):
        """ Login to our netapp filer
        """

        self.server = NaServer(self.ip, 1, 3)
        self.server.set_transport_type('HTTPS')
        self.server.set_style('LOGIN')
        self.server.set_admin_user(self.netapp_user, self.netapp_password)


class netapp_inode(diamond.collector.Collector):
    """ Netapp inode diamond collector
    """

    running = set()

    def collect(self, device, ip, user, password):
        """ Collects metrics for our netapp filer --START HERE--

        """

        if netappsdk is None:
            self.log.error(
                'Failed to import netappsdk.NaServer or netappsdk.NaElement')
            return

        if device in self.running:
            return

        self.running.add(device)
        prefix = self.config['path_prefix']
        pm = self.publish_metric

        netapp_inodeCol(device, ip, user, password, prefix, pm)
        self.running.remove(device)

    def get_schedule(self):
        """ Override Collector.get_schedule

           We override collector.get_schedule so we can increase speed
           by having a task per netapp filer

            return schedule - dictionary with key being className_device
              value is tuple containing:
                0(tuple) - object collector method
                1(tuple) - device, ip, user, password
                2(int)   - splay, set in diamond.conf
                3(int)   - interval, set in diamond.conf

        """

        schedule = {}

        if 'devices' in self.config:

            for device in self.config['devices']:
                filer_config = self.config['devices'][device]
                task_name = '_'.join([self.__class__.__name__, device])

                if task_name in schedule:
                    raise KeyError('Duplicate netapp filer scheduled')

                schedule[task_name] = (
                    self.collect,
                    (device,
                     filer_config['ip'],
                     filer_config['user'],
                     filer_config['password']),
                    int(self.config['splay']),
                    int(self.config['interval']))

                self.log.info("Set up scheduler for %s" % device)

        return schedule
