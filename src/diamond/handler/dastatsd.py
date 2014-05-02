# coding=utf-8

"""
This is a simple statsd handler for dA. Instead of managing merge conflicts
we just make our own.

Things we do different:

* flushing only at collector end, instead of adhoc batching
  this exposes long running collectors and saves us from
  incomplete data sets from a collector.
* flushing stats from a collector in groups of 10
* no py-statsd lib requirement
* can accept custom 'metric.metric_type' that is translated
  to statsd metric type 

    ('T' = timer, 'C' = counter, 'S' = set, gauge is default)

 * handers = diamond.handler.dastatsd.StatsHandler
"""

from Handler import Handler
import logging

import socket
import time
import json
import sys

class StatsHandler(Handler):

    def __init__(self, config=None):
        """
        Create a new instance of the StatsdHandler class
        """
        # Initialize Handler
        Handler.__init__(self, config)
        logging.debug("Initialized statsd handler.")
        # Initialize Options
        self.host = self.config['host']
        self.port = int(self.config['port'])
        self.batch_size = int(self.config.get('batch', 1))
        self.old_values = {}
        self.queues = {}

    def process(self, metric):
        """add metric to source queue"""
        if metric.source not in self.queues:
            self.queues[metric.source] = []
        self.queues[metric.source].append(metric)

    def render_metric(self, metric):
        fqmn = metric.path +  ':' + str(metric.value) + '|'
        if metric.metric_type == 'T':
            return fqmn + 't'
        elif metric.metric_type == 'S':
            return fqmn + 's'
        elif metric.metric_type == 'C':
            return fqmn + 'c'
        else:
            return fqmn + 'g'

    def _send(self, metrics):
        """
        Send data to statsd
        Render metric into statsd format
        """
        rendered = map(self.render_metric, filter(None, metrics))
        stat_string = '\n'.join(rendered)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        try:
            sent = s.sendto(stat_string, (self.host, self.port))
            if sent != len(stat_string):
                raise socket.error('%s: sent count does not match' % (self.__class__.__name__))
        finally:
            s.close()

    def flush(self, caller):
        """Flush metrics in caller queue"""

        def chunks(l, n):
            """yield n sized chunks of a list"""
            for i in xrange(0, len(l), n):
                yield l[i:i+n]

        if caller in self.queues:
            try:
                for batch in chunks(self.queues[caller], 10):
                    self._send(batch)
            finally:
                self.queues[caller] = []
