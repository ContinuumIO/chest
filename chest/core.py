from collections import MutableMapping
import errno
from functools import partial
from threading import Lock
from contextlib import contextmanager
import sys
import tempfile
import shutil
import os
import re
try:
    import cPickle as pickle
except ImportError:  # pragma: no cover
    import pickle  # pragma: no cover
from heapdict import heapdict
import hashlib

from .utils import BytesIO


DEFAULT_AVAILABLE_MEMORY = 1e9
MAX_OPEN_FILES = 512


def key_to_filename(key):
    """ Return a filename from any kind of hashable key

    >>> type(key_to_filename(('foo', 'bar'))).__name__
    'str'
    """
    if isinstance(key, str) and re.match('^[_a-zA-Z]\w*$', key):
        return key
    if isinstance(key, tuple):
        names = (['_' + key_to_filename(k) for k in key[:-1]] +
                 [key_to_filename(key[-1])])
        return os.path.join(*names)
    else:
        return str(hashlib.md5(str(key).encode()).hexdigest())


def _do_nothing(*args, **kwargs):
    pass


class full_policy(object):
    """ Behaviours to use when a a chest is full.
    """
    @staticmethod
    def raise_(chest):
        """A policy that raises an ENOSPC error if the disk is full.
        """
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), chest.path)

    @staticmethod
    def pop_lru(chest):
        """A policy that removes the most recently used element from
        the cache when the chest is full.
        """
        del chest[chest.heap.popitem()[0]]


@contextmanager
def _open_many(fnames, mode='rb'):
    fs = []
    for fn in fnames:
        fs.append(open(fn, mode=mode))
    yield fs
    for f in fs:
        f.close()


class Chest(MutableMapping):
    """ A Dictionary that spills to disk

    Chest acts like a normal Python dictionary except that it writes large
    contents to disk.  It is ideal to store and access collections of large
    variables like arrays.

    Paramters
    ---------

    data : dict (optional)
        An initial dictionary to seed the chest
    path : str (optional)
        A directory path to store contents of the chest.  Defaults to a tmp dir
    available_memory : int (optional)
        Number of bytes that a chest should use for in-memory storage
    available_disk : int (optional)
        Number of bytes that a chest should use for on-disk storage.
        If this is not provided then there will be no cap.
    on_full : function (optional)
        A function to be called if available_disk has been used; however,
        more disk space is requested. This function will be passed the chest
    dump : function (optional)
        A function like pickle.dump or json.dump that dumps contents to file
    load : function(optional)
        A function like pickle.load or json.load that loads contents from file
    key_to_filename : function (optional)
        A function to determine filenames from key values
    lock : Lock (optional)
        The lock object to use to control access to the disk. If no lock is
        given, a new threading lock will be used.
    mode : str (t or b)
        Binary or text mode for file storage

    Examples
    --------

    >>> c = Chest(path='my-chest')
    >>> c['x'] = [1, 2, 3]
    >>> c['x']
    [1, 2, 3]

    >>> c.flush()
    >>> import os
    >>> sorted(os.listdir(c.path))
    ['.keys', 'x']

    >>> c.drop()
    """
    def __init__(self, data=None, path=None,
                 available_memory=None,
                 available_disk=None,
                 dump=partial(pickle.dump, protocol=1),
                 load=pickle.load,
                 key_to_filename=key_to_filename,
                 lock=None,
                 on_full=full_policy.raise_,
                 on_miss=_do_nothing, on_overflow=_do_nothing,
                 open=open,
                 open_many=_open_many,
                 mode='b'):
        # In memory storage
        self.inmem = data or dict()
        # A set of keys held both in memory or on disk
        self._keys = {}
        # Was a path given or no?  If not we'll clean up the directory later
        self._explicitly_given_path = path is not None
        # Diretory where the on-disk data will be held
        self.path = path or tempfile.mkdtemp('.chest')
        # Amount of memory we're allowed to use
        self.available_memory = (available_memory if available_memory
                                 is not None else DEFAULT_AVAILABLE_MEMORY)
        self.memory_usage = sum(map(nbytes, self.inmem.values()))
        self.available_disk = available_disk
        self.on_full = on_full
        # Functions to control disk I/O
        self.load = load
        self._dump = dump
        if available_disk is None:
            self.dump = dump
        self.mode = mode
        self.open = open
        self.open_many = open_many
        self._key_to_filename = key_to_filename

        keyfile = os.path.join(self.path, '.keys')
        try:
            with self.open(keyfile, mode='r'+self.mode) as f:
                self._keys = dict(self.load(f))
        except:
            if not os.path.exists(self.path):
                os.mkdir(self.path)

        self.lock = lock if lock is not None else Lock()

        # LRU state
        self.counter = 0
        self.heap = heapdict()

        # Debug
        self._on_miss = on_miss
        self._on_overflow = on_overflow

    def __repr__(self):
        return '<chest at %s: keys=%s>' % (self.path, list(self._keys))
    __str__ = __repr__

    @property
    def disk_usage(self):
        path = self.path
        return sum(
            os.path.getsize(os.path.join(r, f))
            for r, _, fs in os.walk(path) for f in fs
        )

    def dump(self, data, file_):
        tmp = BytesIO()
        self._dump(data, tmp)
        bs = tmp.getvalue()
        while self.disk_usage + len(bs) > self.available_disk:
            self.on_full(self)
        file_.write(bs)

    def key_to_filename(self, key):
        """ Filename where key will be held """
        if key in self._keys:
            return os.path.join(self.path, self._keys[key])
        else:
            return os.path.join(self.path, self._key_to_filename(key))

    def move_to_disk(self, key):
        """ Move data from memory onto disk """
        self._on_overflow(key)
        fn = self.key_to_filename(key)
        if not os.path.exists(fn):  # Only write if it doesn't exist.
            dir = os.path.dirname(fn)
            if not os.path.exists(dir):
                os.makedirs(dir)
            try:
                with self.open(fn, mode='w'+self.mode) as f:
                    self.dump(self.inmem[key], f)
            except TypeError:
                os.remove(fn)
                raise
        try:
            self.memory_usage -= nbytes(self.inmem[key])
            del self.inmem[key]
        except KeyError:
            pass

    def get_from_disk(self, key):
        """ Pull value from disk into memory """
        if key in self.inmem:
            return

        fn = self.key_to_filename(key)
        with self.open(fn, mode='r'+self.mode) as f:
            value = self.load(f)

        self.inmem[key] = value
        self.memory_usage += nbytes(value)

    def __getitem__(self, key):
        with self.lock:
            if key in self.inmem:
                value = self.inmem[key]
            else:
                if key not in self._keys:
                    raise KeyError("Key not found: %s" % str(key))

                self._on_miss(key)
                self.get_from_disk(key)
                value = self.inmem[key]
                self._update_lru(key)

        with self.lock:
            self.shrink()

        return value

    def _update_lru(self, key):
        self.counter += 1
        self.heap[key] = self.counter

    def __delitem__(self, key):
        if key in self.inmem:
            self.memory_usage -= nbytes(self.inmem[key])
            del self.inmem[key]
        if key in self.heap:
            del self.heap[key]

        fn = self.key_to_filename(key)
        if os.path.exists(fn):
            os.remove(fn)

        del self._keys[key]

    def __setitem__(self, key, value):
        with self.lock:
            if key in self._keys:
                del self[key]

            self.memory_usage += nbytes(value)
            self.inmem[key] = value
            self._keys[key] = self._key_to_filename(key)
            self._update_lru(key)

        with self.lock:
            self.shrink()

    def __del__(self):
        if self._explicitly_given_path:
            if os.path.exists(self.path):
                self.flush()
            else:
                with self.lock:
                    for key in list(self.inmem):
                        del self.inmem[key]
        elif os.path.exists(self.path):
            with self.lock:
                self.drop()  # pragma: no cover

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    def __contains__(self, key):
        return key in self._keys

    def shrink(self):
        """
        Spill in-memory storage to disk until usage is less than available
        """
        if self.memory_usage < self.available_memory:
            return

        while self.memory_usage > self.available_memory:
            key, _ = self.heap.popitem()
            data = self.inmem[key]
            try:
                self.move_to_disk(key)
            except TypeError:
                pass

    def drop(self):
        """ Permanently remove directory from disk """
        shutil.rmtree(self.path)

    def write_keys(self):
        fn = os.path.join(self.path, '.keys')
        with self.open(fn, mode='w'+self.mode) as f:
            self.dump(list(self._keys.items()), f)

    def flush(self):
        """ Flush all in-memory storage to disk """
        with self.lock:
            for key in list(self.inmem):
                self.move_to_disk(key)
            self.write_keys()

    def __enter__(self):
        return self

    def __exit__(self, eType, eValue, eTrace):
        with self.lock:
            L = os.listdir(self.path)
            if not self._explicitly_given_path and os.path.exists(self.path):
                self.drop()  # pragma: no cover

        if eValue is not None:
            if not isinstance(eValue, Exception):  # Py26 behavior
                eValue = eType(eValue)  # pragma: no cover
            raise eValue

    def update(self, other, overwrite=True):
        """ Copy (hard-link) the contents of chest other to this chest """
        #  if already flushed, then this does nothing
        self.flush()
        other.flush()
        for key in other._keys:
            if key in self._keys and overwrite:
                del self[key]
            elif key in self._keys and not overwrite:
                continue
            old_fn = other.key_to_filename(key)
            self._keys[key] = self._key_to_filename(key)
            new_fn = self.key_to_filename(key)
            dir = os.path.dirname(new_fn)
            if not os.path.exists(dir):
                os.makedirs(dir)
            os.link(old_fn, new_fn)

    def prefetch(self, keys):
        """ Fetch a list of pairs into memory """
        if not isinstance(keys, list):
            keys = [keys, ]
        keys = [k for k in keys if k not in self.inmem]
        fns = [self.key_to_filename(k) for k in keys]
        for i in range(0, len(fns), MAX_OPEN_FILES):
            top = min(len(fns), i + MAX_OPEN_FILES)
            with self.open_many(fns[i:top], mode='r'+self.mode) as fs:
                for f, k in zip(fs, keys[i:top]):
                    value = self.load(f)
                    self.inmem[k] = value
                    self.memory_usage += nbytes(value)
                    self._update_lru(k)
                    with self.lock:
                        self.shrink()


def nbytes(o):
    """ Number of bytes of an object

    >>> nbytes(123)  # doctest: +SKIP
    24

    >>> nbytes('Hello, world!')  # doctest: +SKIP
    50

    >>> import numpy as np
    >>> nbytes(np.ones(1000, dtype='i4'))
    4000
    """
    if hasattr(o, 'nbytes'):
        return o.nbytes
    n = str(type(o))
    if 'pandas' in n and ('DataFrame' in n or 'Series' in n):
        return sum(b.values.nbytes * (10 if b.values.dtype == 'O' else 1)
                   for b in o._data.blocks)  # pragma: no cover
    else:
        return sys.getsizeof(o)
