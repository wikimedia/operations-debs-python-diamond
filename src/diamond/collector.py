# coding=utf-8

"""
The Collector class is a base class for all metric collectors.
"""

import os
import socket
import platform
import logging
import configobj
import traceback
import time

from diamond.metric import Metric

# Detect the architecture of the system and set the counters for MAX_VALUES
# appropriately. Otherwise, rolling over counters will cause incorrect or
# negative values.

if platform.architecture()[0] == '64bit':
    MAX_COUNTER = (2 ** 64) - 1
else:
    MAX_COUNTER = (2 ** 32) - 1


def get_hostname(config, method=None):
    """
    Returns a hostname as configured by the user
    """
    if 'hostname' in config:
        return config['hostname']

    if method is None:
        if 'hostname_method' in config:
            method = config['hostname_method']
        else:
            method = 'smart'

    # case insensitive method
    method = method.lower()

    if method in get_hostname.cached_results:
        return get_hostname.cached_results[method]

    if method == 'smart':
        hostname = get_hostname(config, 'fqdn_short')
        if hostname != 'localhost':
            get_hostname.cached_results[method] = hostname
            return hostname
        hostname = get_hostname(config, 'hostname_short')
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'fqdn_short':
        hostname = socket.getfqdn().split('.')[0]
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'fqdn':
        hostname = socket.getfqdn().replace('.', '_')
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'fqdn_rev':
        hostname = socket.getfqdn().split('.')
        hostname.reverse()
        hostname = '.'.join(hostname)
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'uname_short':
        hostname = os.uname()[1].split('.')[0]
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'uname_rev':
        hostname = os.uname()[1].split('.')
        hostname.reverse()
        hostname = '.'.join(hostname)
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'hostname':
        hostname = socket.gethostname()
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'hostname_short':
        hostname = socket.gethostname().split('.')[0]
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'hostname_rev':
        hostname = socket.gethostname().split('.')
        hostname.reverse()
        hostname = '.'.join(hostname)
        get_hostname.cached_results[method] = hostname
        return hostname

    if method == 'none':
        get_hostname.cached_results[method] = None
        return None

    raise NotImplementedError(config['hostname_method'])

get_hostname.cached_results = {}


def str_to_bool(value):
    """
    Converts string truthy/falsey strings to a bool
    Empty strings are false
    """
    if isinstance(value, basestring):
        value = value.strip().lower()
        if value in ['true', 't', 'yes', 'y']:
            return True
        elif value in ['false', 'f', 'no', 'n', '']:
            return False
        else:
            raise NotImplementedError("Unknown bool %s" % value)

    return value


class Collector(object):
    """
    The Collector class is a base class for all metric collectors.
    """

    def __init__(self, config, handlers):
        """
        Create a new instance of the Collector class
        """
        # Initialize Logger
        self.log = logging.getLogger('diamond')
        # Initialize Members
        self.name = self.__class__.__name__
        self.handlers = handlers
        self.last_values = {}

        # Get Collector class
        cls = self.__class__

        # Initialize config
        self.config = configobj.ConfigObj()

        # Check if default config is defined
        if self.get_default_config() is not None:
            # Merge default config
            self.config.merge(self.get_default_config())

        # Merge default Collector config
        self.config.merge(config['collectors']['default'])

        # Check if Collector config section exists
        if cls.__name__ in config['collectors']:
            # Merge Collector config section
            self.config.merge(config['collectors'][cls.__name__])

        # Check for config file in config directory
        configfile = os.path.join(config['server']['collectors_config_path'],
                                  cls.__name__) + '.conf'
        if os.path.exists(configfile):
            # Merge Collector config file
            self.config.merge(configobj.ConfigObj(configfile))

        # Handle some config file changes transparently
        if isinstance(self.config['byte_unit'], basestring):
            self.config['byte_unit'] = self.config['byte_unit'].split()

        self.config['enabled'] = str_to_bool(self.config['enabled'])

        self.config['measure_collector_time'] = str_to_bool(
            self.config['measure_collector_time'])

        self.collect_running = False

    def get_default_config_help(self):
        """
        Returns the help text for the configuration options for this collector
        """
        return {
            'enabled': 'Enable collecting these metrics',
            'byte_unit': 'Default numeric output(s)',
            'measure_collector_time': 'Collect the collector run time in ms',
        }

    def get_default_config(self):
        """
        Return the default config for the collector
        """
        return {
            ### Defaults options for all Collectors

            # Uncomment and set to hardcode a hostname for the collector path
            # Keep in mind, periods are seperators in graphite
            # 'hostname': 'my_custom_hostname',

            # If you perfer to just use a different way of calculating the
            # hostname
            # Uncomment and set this to one of these values:
            # fqdn_short  = Default. Similar to hostname -s
            # fqdn        = hostname output
            # fqdn_rev    = hostname in reverse (com.example.www)
            # uname_short = Similar to uname -n, but only the first part
            # uname_rev   = uname -r in reverse (com.example.www)
            # 'hostname_method': 'fqdn_short',

            # All collectors are disabled by default
            'enabled': False,

            # Path Prefix
            'path_prefix': 'servers',

            # Path Prefix for Virtual Machine metrics
            'instance_prefix': 'instances',

            # Path Suffix
            'path_suffix': '',

            # Default splay time (seconds)
            'splay': 1,

            # Default Poll Interval (seconds)
            'interval': 300,

            # Default Event TTL (interval multiplier)
            'ttl_multiplier': 2,

            # Default collector threading model
            'method': 'Sequential',

            # Default numeric output
            'byte_unit': 'byte',

            # Collect the collector run time in ms
            'measure_collector_time': False,
        }

    def get_stats_for_upload(self, config=None):
        if config is None:
            config = self.config

        stats = {}

        if 'enabled' in config:
            stats['enabled'] = config['enabled']
        else:
            stats['enabled'] = False

        if 'interval' in config:
            stats['interval'] = config['interval']

        return stats

    def get_schedule(self):
        """
        Return schedule for the collector
        """
        # Return a dict of tuples containing (collector function,
        # collector function args, splay, interval)
        return {self.__class__.__name__: (self._run,
                                          None,
                                          int(self.config['splay']),
                                          int(self.config['interval']))}

    def get_metric_path(self, name, instance=None):
        """
        Get metric path.
        Instance indicates that this is a metric for a
            virtual machine and should have a different
            root prefix.
        """
        if 'path' in self.config:
            path = self.config['path']
        else:
            path = self.__class__.__name__

        if instance is not None:
            if 'instance_prefix' in self.config:
                prefix = self.config['instance_prefix']
            else:
                prefix = 'instances'
            if path == '.':
                return '.'.join([prefix, instance, name])
            else:
                return '.'.join([prefix, instance, path, name])

        if 'path_prefix' in self.config:
            prefix = self.config['path_prefix']
        else:
            prefix = 'systems'

        if 'path_suffix' in self.config:
            suffix = self.config['path_suffix']
        else:
            suffix = None

        hostname = get_hostname(self.config)
        if hostname is not None:
            if prefix:
                prefix = ".".join((prefix, hostname))
            else:
                prefix = hostname

        # if there is a suffix, add after the hostname
        if suffix:
            prefix = '.'.join((prefix, suffix))

        if path == '.':
            return '.'.join([prefix, name])
        else:
            return '.'.join([prefix, path, name])

    def get_hostname(self):
        return get_hostname(self.config)

    def collect(self):
        """
        Default collector method
        """
        raise NotImplementedError()

    def publish(self, name, value, raw_value=None, precision=0,
                metric_type='GAUGE', instance=None):
        """
        Publish a metric with the given name
        """
        # Get metric Path
        path = self.get_metric_path(name, instance=instance)

        # Get metric TTL
        ttl = float(self.config['interval']) * float(
            self.config['ttl_multiplier'])


        # Create Metric
        metric = Metric(path, value, raw_value=raw_value, timestamp=None,
                        precision=precision, host=self.get_hostname(),
                        metric_type=metric_type, ttl=ttl, source=self.name)

        # Publish Metric
        self.publish_metric(metric)

    def publish_metric(self, metric):
        """
        Publish a Metric object
        """
        # Process Metric
        for handler in self.handlers:
            handler._process(metric)

    def publish_gauge(self, name, value, precision=0, instance=None):
        return self.publish(name, value, precision=precision,
                            metric_type='GAUGE', instance=instance)

    def publish_counter(self, name, value, precision=0, max_value=0,
                        time_delta=True, interval=None, allow_negative=False,
                        instance=None):
        raw_value = value
        value = self.derivative(name, value, max_value=max_value,
                                time_delta=time_delta, interval=interval,
                                allow_negative=allow_negative,
                                instance=instance)
        return self.publish(name, value, raw_value=raw_value,
                            precision=precision, metric_type='COUNTER',
                            instance=instance)

    def derivative(self, name, new, max_value=0,
                   time_delta=True, interval=None,
                   allow_negative=False, instance=None):
        """
        Calculate the derivative of the metric.
        """
        # Format Metric Path
        path = self.get_metric_path(name, instance=instance)

        if path in self.last_values:
            old = self.last_values[path]
            # Check for rollover
            if new < old:
                old = old - max_value
            # Get Change in X (value)
            derivative_x = new - old

            # If we pass in a interval, use it rather then the configured one
            if interval is None:
                interval = int(self.config['interval'])

            # Get Change in Y (time)
            if time_delta:
                derivative_y = interval
            else:
                derivative_y = 1

            result = float(derivative_x) / float(derivative_y)
            if result < 0 and not allow_negative:
                result = 0
        else:
            result = 0

        # Store Old Value
        self.last_values[path] = new

        # Return result
        return result

    def _run(self):
        """
        Run the collector unless it's already running
        """
        if self.collect_running:
            return
        # Log
        self.log.debug("Collecting data from: %s" % self.__class__.__name__)
        try:
            try:
                start_time = time.time()
                self.collect_running = True

                # Collect Data
                self.collect()

                end_time = time.time()

                if 'measure_collector_time' in self.config:
                    if self.config['measure_collector_time']:
                        metric_name = 'collector_time_ms'
                        metric_value = int((end_time - start_time) * 1000)
                        self.publish(metric_name, metric_value)

            except Exception:
                # Log Error
                self.log.error(traceback.format_exc())
        finally:
            self.collect_running = False
            # After collector run, invoke a flush
            # method on each handler.
            for handler in self.handlers:
                handler.flush(self.name)

    def find_binary(self, binary):
        """
        Scan and return the first path to a binary that we can find
        """
        if os.path.exists(binary):
            return binary

        # Extract out the filename if we were given a full path
        binary_name = os.path.basename(binary)

        # Gather $PATH
        search_paths = os.environ['PATH'].split(':')

        # Extra paths to scan...
        default_paths = [
            '/usr/bin',
            '/bin'
            '/usr/local/bin',
            '/usr/sbin',
            '/sbin'
            '/usr/local/sbin',
        ]

        for path in default_paths:
            if path not in search_paths:
                search_paths.append(path)

        for path in search_paths:
            if os.path.isdir(path):
                filename = os.path.join(path, binary_name)
                if os.path.exists(filename):
                    return filename

        return binary
