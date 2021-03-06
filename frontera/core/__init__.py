from __future__ import absolute_import
from six.moves.urllib.parse import urlparse
from socket import getaddrinfo
from collections import defaultdict, deque
import six


def get_slot_key(request, type):  # TODO: Probably use caching here
    """
    Get string representing a downloader slot key, which will be used in downloader as id for domain/ip load
    statistics and in backend for distinguishing free and overloaded resources. This method used in all Frontera
    backends.

    :param object request: is the instance of :class:`Request <frontera.core.models.Request>`.
    :param str type: either 'domain'(default) or 'ip'.
    :return: string
    """
    key = urlparse(request.url).hostname or ''
    if type == 'ip':
        for result in getaddrinfo(key, 80):
            key = result[4][0]
            break
    return key


class OverusedBuffer(object):
    """
    A buffering object for implementing the buffer of Frontera requests for overused domains/ips. It can be used
    when customizing backend to address efficient downloader pool usage.
    """
    def __init__(self, _get_func, log_func=None, max_queue_size=None):
        """
        :param _get_func: reference to get_next_requests() method of binded class
        :param log_func: optional logging function, for logging of internal state
        """
        self._pending = defaultdict(deque)
        self._get = _get_func
        self._log = log_func
        self.max_queue_size = max_queue_size

    def _get_key(self, request, type):
        return get_slot_key(request, type)

    def _get_pending_count(self):
        return sum(six.moves.map(len, six.itervalues(self._pending)))

    def _get_pending(self, max_n_requests, overused_set):
        pending = self._pending
        i, keys = 0, set(pending) - overused_set

        while i < max_n_requests and keys:
            for key in keys.copy():
                try:
                    yield pending[key].popleft()
                    i += 1
                except IndexError:
                    keys.discard(key)
                    del pending[key]

    def get_next_requests(self, max_n_requests, **kwargs):
        if self._log:
            self._log("Overused keys: %s" % str(kwargs['overused_keys']))
            self._log("Pending: %d" % self._get_pending_count())

        overused_set = set(kwargs['overused_keys'])
        requests = list(self._get_pending(max_n_requests, overused_set))

        if len(requests) == max_n_requests:
            return requests

        for request in self._get(max_n_requests-len(requests), **kwargs):
            key = self._get_key(request, kwargs['key_type'])
            if key in overused_set:
                # Drop request if the pending queue is already full.
                if not self.max_queue_size or len(self._pending[key]) < self.max_queue_size:
                    self._pending[key].append(request)
            else:
                requests.append(request)
        return requests
