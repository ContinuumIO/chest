Chest
=====

|Build Status| |Coverage Status| |Version Status| |Downloads|

A dictionary that spills to disk.

Chest acts likes a dictionary but it can write its contents to disk.  This is
useful in the following two occasions:

1.  Chest can hold datasets that are larger than memory
2.  Chest persists and so can be saved and loaded for later use

Related Projects
----------------

The standard library ``shelve`` is an alternative out-of-core dictionary.
``Chest`` offers the following benefits over shelve_:

1.  Chest supports any hashable key (not just strings)
2.  Chest supports pluggable serialization and file saving schemes

Alternatively one might consider a traditional key-value store database like
Redis_.

Shove_ is another excellent alternative with support for a variety of stores.


How it works
------------

Chest stores data in two locations

1.  An in-memory dictionary
2.  On the filesystem in a directory owned by the chest

As a user adds contents to the chest the in-memory dictionary fills up.  When
a chest stores more data in memory than desired (see ``available_memory=``
keyword argument) it writes the larger contents of the chest to disk as pickle
files (the choice of ``pickle`` is configurable).  When a user asks for a value
chest checks the in-memory store, then checks on-disk and loads the value into
memory if necessary, pushing other values to disk.

Chest is a simple project.  It was intended to provide a simple interface to
assist in the storage and retrieval of numpy arrays.  However it's design and
implementation are agnostic to this case and so could be used in a variety of
other situations.

With minimal work chest could be extended to serve as a communication point
between multiple processes.


Known Failings
--------------

Chest was designed to hold a moderate amount of largish numpy arrays.  It
doesn't handle the very many small key-value pairs usecase (though could with
small effort).  In particular chest has the following deficiencies

1.  Chest is not multi-process safe.  We should institute a file lock at least
    around the ``.keys`` file.
2.  Chest does not support mutation of variables on disk.


LICENSE
-------

New BSD. See License_


Install
-------

``chest`` is available through ``conda``::

    conda install chest

``chest`` is on the Python Package Index (PyPI)::

    pip install chest


Example
-------

.. code:: python

    >>> from chest import Chest
    >>> c = Chest()

    >>> # Acts like a normal dictionary
    >>> c['x'] = [1, 2, 3]
    >>> c['x']
    [1, 2, 3]

    >>> # Data persists to local files
    >>> c.flush()
    >>> import os
    >>> os.listdir(c.path)
    ['.keys', 'x']

    >>> # These files hold pickled results
    >>> import pickle
    >>> pickle.load(open(c.key_to_filename('x')))
    [1, 2, 3]

    >>> # Though one normally accesses these files with chest itself
    >>> c2 = Chest(path=c.path)
    >>> c2.keys()
    ['x']
    >>> c2['x']
    [1, 2, 3]

    >>> # Chest is configurable, so one can use json, etc. instead of pickle
    >>> import json
    >>> c = Chest(path='my-chest', dump=json.dump, load=json.load)
    >>> c['x'] = [1, 2, 3]
    >>> c.flush()

    >>> json.load(open(c.key_to_filename('x')))
    [1, 2, 3]


Dependencies
------------

``Chest`` supports Python 2.6+ and Python 3.2+ with a common codebase.

It currently depends on the ``heapdict`` library.

It is a light weight dependency.


.. _shelve: https://docs.python.org/3/library/shelve.html
.. _Shove: https://pypi.python.org/pypi/shove/0.5.6
.. _License: https://github.com/ContinuumIO/chest/blob/master/LICENSE.txt
.. _Redis: http://redis.io/
.. |Build Status| image:: https://travis-ci.org/ContinuumIO/chest.png
   :target: https://travis-ci.org/ContinuumIO/chest
.. |Coverage Status| image:: https://coveralls.io/repos/mrocklin/chest/badge.png
   :target: https://coveralls.io/r/mrocklin/chest
.. |Version Status| image:: https://img.shields.io/pypi/v/chest.svg
   :target: https://pypi.python.org/pypi/chest/
.. |Downloads| image:: https://img.shields.io/pypi/dm/chest.svg
   :target: https://pypi.python.org/pypi/chest/
