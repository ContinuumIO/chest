import os
import re
import json
import shutil
import pickle
from contextlib import contextmanager
import numpy as np
from chest.utils import raises, raise_KeyError
import hashlib

from chest.core import Chest, nbytes, key_to_filename, full_policy
from chest.utils import PY3


@contextmanager
def tmp_chest(*args, **kwargs):
    c = Chest(*args, **kwargs)
    fn = c.path

    try:
        yield c
    finally:
        if os.path.exists(fn):
            with c.lock:
                c.drop()
        try:
            del c
        except:
            pass


def my_key_to_fname(key):
    fname = str(hashlib.md5(str(key).encode()).hexdigest())
    return fname


def test_basic():
    with tmp_chest() as c:
        c[1] = 'one'
        c['two'] = 2

        assert c[1] == 'one'
        assert c['two'] == 2
        assert c.path

        assert len(c) == 2
        assert set(c) == set([1, 'two'])


def test_paths():
    with tmp_chest() as c:
        assert os.path.exists(c.path)

        c[1] = 'one'

        c.move_to_disk(1)

        assert os.path.exists(c.key_to_filename(1))

        with open(c.key_to_filename(1), mode='rb') as f:
            assert pickle.load(f) == 'one'


def eq(a, b):
    c = a == b
    if isinstance(c, np.ndarray):
        return c.all()
    return c


def test_limited_storage():
    x = np.ones(1000, dtype='i4')
    y = np.ones(1000, dtype='i4')
    with tmp_chest(available_memory=5000) as c:
        c['x'] = x
        c['y'] = y
        assert c.memory_usage < c.available_memory
        assert 'x' in c
        assert 'y' in c

        assert len(c.inmem) == 1

        assert 'x' not in c.inmem
        assert 'y' in c.inmem

        assert eq(c['x'], x)
        assert eq(c['y'], y)


def test_limited_shrink_called_normally():
    x = np.ones(1000, dtype='i4')
    y = 2 * np.ones(1000, dtype='i4')
    with tmp_chest(available_memory=0) as c:
        c['x'] = x
        c['y'] = y

        assert not c.inmem

        assert eq(c['x'], x)

        assert not c.inmem


def test_shrink():
    with tmp_chest(available_memory=100) as c:
        c['one'] = np.ones(10, dtype='i8')  # 80 bytes
        assert 'one' in c.inmem
        c['two'] = 2 * np.ones(5, dtype='i8')  # 40 bytes
        assert 'two' in c.inmem
        assert 'one' not in c.inmem


def test_drop():
    with tmp_chest() as c:
        c.drop()
        assert not os.path.exists(c.path)


def test_flush():
    with tmp_chest() as c:
        c[1] = 'one'
        c[2] = 'two'
        c.flush()
        assert os.path.exists(c.key_to_filename(1))
        assert os.path.exists(c.key_to_filename(2))
        c[1] = 'two'
        c[2] = 'one'
        c.flush()
        assert c[1] == 'two'
        assert c[2] == 'one'


def test_keys_values_items():
    with tmp_chest() as c:
        c[1] = 'one'
        c[2] = 'two'

        assert set(c.keys()) == set([1, 2])
        assert set(c.values()) == set(['one', 'two'])
        assert set(c.items()) == set([(1, 'one'), (2, 'two')])


def test_recreate_chest():
    with tmp_chest() as c:
        c[1] = 'one'
        c[2] = 'two'

        c.flush()

        c2 = Chest(path=c.path)

        assert c.items() == c2.items()


def test_delitem():
    with tmp_chest() as c:
        c[1] = 'one'
        c[2] = 'two'

        del c[1]

        assert 1 not in c

        c.flush()
        assert 2 in c

        assert os.path.exists(c.key_to_filename(2))
        del c[2]
        assert not os.path.exists(c.key_to_filename(2))


def test_str():
    with tmp_chest() as c:
        assert c.path in str(c)


def test_get_from_disk():
    with tmp_chest() as c:
        c[1] = 'one'  # 1 is in memory
        c.get_from_disk(1)  # shouldn't have an effect
        assert 1 in c.inmem


def test_errors():
    with tmp_chest() as c:
        assert raises(KeyError, lambda: c[1])
        assert raises(KeyError, lambda: c[(1, 2)])


def test_reset_item_is_consistent():
    with tmp_chest() as c:
        c[1] = 'one'
        c.flush()

        c[1] = 'uno'
        assert c[1] == 'uno'

        fn = c.key_to_filename(1)

        assert not os.path.exists(fn) or c.load(open(fn)) == 'uno'


def test_nbytes():
    assert isinstance(nbytes('x'), int)
    assert nbytes('x') < 100
    assert nbytes(np.ones(1000, dtype='i4')) >= 4000


def test_dataframe_nbytes():
    try:
        import pandas as pd
        df = pd.DataFrame({'a': [1]*10000})
        assert nbytes(df) > 10000
    except ImportError:
        pass


def test_del_on_temp_path():
    c = Chest()
    c[1] = 'one'
    c.flush()

    fn = c.path
    del c

    import gc
    gc.collect()

    assert not os.path.exists(fn)


def test_del_on_normal_path():
    path = '_chest_test_path'
    if os.path.exists(path):
        shutil.rmtree(path)

    c = Chest(path=path)
    c[1] = 'one'
    c.flush()

    del c
    import gc
    gc.collect()

    assert os.path.exists(path)

    c = Chest(path=path)
    c.drop()


def test_basic_json():
    with tmp_chest(load=json.load, dump=json.dump, mode='t') as c:
        c[1] = [1, 2, 3]
        c[2] = 'two'

        c.flush()

        c2 = Chest(path=c.path, load=json.load, dump=json.dump, mode='t')

        assert c2[1] == c[1]
        assert c2[2] == c[2]


def test_key_to_filename():
    assert key_to_filename('x') == 'x'
    assert isinstance(key_to_filename((1, (3, 4))), str)

    assert re.match('^\w+$', key_to_filename('1/2'))


def test_key_to_filename_with_tuples():
    a, two = os.path.split(key_to_filename(('one', 'two')))
    b, three = os.path.split(key_to_filename(('one', 'three')))
    assert a == b


def test_context_manager():
    with Chest() as c:
        c[1] = 1
        c.flush()

    assert not os.path.exists(c.path)

    try:
        with Chest() as c:
            1 / 0
    except Exception as e:
        assert isinstance(e, ZeroDivisionError)


def test_threadsafe():
    from multiprocessing.pool import ThreadPool
    from random import randint

    pool = ThreadPool(8)
    n = 100
    with tmp_chest(available_memory=48) as c:
        for i in range(10):
            c[i] = i

        def getset(_):
            c[randint(0, 9)] = c[randint(0, 9)]

        pool.map(getset, range(n))

        pool.close()
        pool.join()

        assert set(c.keys()).issubset(range(10))
        assert set(c.values()).issubset(range(10))


def test_undumpable_values_stay_in_memory():
    class A(object):
        def __getstate__(self):
            raise TypeError()

    with tmp_chest(available_memory=100) as c:
        a = A()
        fn = 'tmp'
        with open(fn, 'w') as f:
            assert raises(TypeError, lambda: c.dump(a, f))
        os.remove(fn)

        c['a'] = a

        # Add enough data to try to flush out a
        for i in range(20):
            c[i] = i

        assert 'a' in c.inmem
        assert not os.path.exists(c.key_to_filename('a'))


def test_eat():
    with tmp_chest() as c1:
        with tmp_chest() as c2:
            c1['foo'] = 'bar'
            c1['bar'] = 'bbq'
            c2['bar'] = 'foo'
            c2['spam'] = 'eggs'
            c1.update(c2)
            assert c1['foo'] == 'bar'
            assert c1['bar'] == 'foo'
            assert c1['spam'] == 'eggs'


def test_update_no_overwrite():
    with tmp_chest() as c1:
        with tmp_chest() as c2:
            c1['foo'] = 'bar'
            c1['bar'] = 'bbq'
            c2['bar'] = 'foo'
            c2['spam', 'spam'] = 'eggs'
            c1.update(c2, overwrite=False)
            assert c1['foo'] == 'bar'
            assert c1['bar'] == 'bbq'
            assert c1['spam', 'spam'] == 'eggs'


def test_update():
    with tmp_chest() as c1:
        with tmp_chest() as c2:
            c1['foo'] = 'bar'
            c1['bar'] = 'bbq'
            c2['bar'] = 'foo'
            c2['spam', 'spam'] = 'eggs'
            c1.update(c2)
            assert c1['foo'] == 'bar'
            assert c1['bar'] == 'foo'
            assert c1['spam', 'spam'] == 'eggs'
            assert c2['bar'] == 'foo'
            assert c2['spam', 'spam'] == 'eggs'


def test_del_flushes():
    with tmp_chest(path='foo') as c:
        assert c._explicitly_given_path
        c[1] = 1
        fn = c.key_to_filename(1)
        c.__del__()
        assert os.path.exists(fn)


def test_del_drops():
    with tmp_chest() as c:
        c[1] = 1
        fn = c.key_to_filename(1)
        c.flush()
        c.__del__()
        assert not os.path.exists(fn)


def test_nested_files_with_tuples():
    with tmp_chest(path='foo') as c:
        c['one'] = 1
        c['one', 'two'] = 12
        c['one', 'three'] = 13

        assert c['one'] == 1
        assert c['one', 'two'] == 12
        assert c['one', 'three'] == 13

        c.flush()
        paths = [fn for fn in os.listdir(c.path) if fn != '.keys']
        assert len(paths) == 2
        assert any(os.path.isdir(os.path.join(c.path, p)) for p in paths)
        assert any(not os.path.isdir(os.path.join(c.path, p)) for p in paths)

        c['a', 'b', 'c', 'd', 'e'] = 5
        c.flush()
        assert c['a', 'b', 'c', 'd', 'e'] == 5


def test_store_fnames():
    with tmp_chest(key_to_filename=my_key_to_fname) as c1:
        c1[('spam', 'eggs')] = 'spam and eggs'
        c1.flush()
        with tmp_chest() as c2:
            c2.update(c1)
            c2.flush()
            assert c2[('spam', 'eggs')] == 'spam and eggs'


def test_store_fnames_relocatable():
    with tmp_chest(path="somewhere", key_to_filename=my_key_to_fname) as c1:
        c1[('spam', 'eggs')] = 'spam and eggs'
        c1.flush()
        os.rename("somewhere", "else")
        with tmp_chest(path="else") as c1:
            with tmp_chest(path="somewhereelse") as c2:
                c2.update(c1)
                c2.flush()
                assert c2[('spam', 'eggs')] == 'spam and eggs'


def test_memory_usage():
    with tmp_chest() as c:
        assert c.memory_usage == 0
        c[1] = 1
        mem1 = c.memory_usage
        assert mem1 > 0
        c[2] = 2
        assert c.memory_usage > mem1

        c.flush()
        assert c.memory_usage == 0


def test_prefetch():
    with tmp_chest(on_miss=raise_KeyError) as c:
        c[1] = 1
        c[2] = 2
        c[3] = 3
        assert not raises(KeyError, lambda: c[1])
        c.flush()
        assert raises(KeyError, lambda: c[1])
        c.prefetch(1)
        assert not raises(KeyError, lambda: c[1])
        c.prefetch([1, 2])
        assert not raises(KeyError, lambda: c[2])


def test_available_disk_raise():
    with tmp_chest(available_disk=0) as c:
        c[1] = 1
        assert not raises(KeyError, lambda: c[1])
        assert raises(OSError, lambda: c.flush())


def test_available_disk_pop_lru():
    with tmp_chest(available_disk=100 if PY3 else 94,
                   on_full=full_policy.pop_lru) as c:
        c[1] = 1
        assert not raises(KeyError, lambda: c[1])
        c[2] = 2
        assert not raises(KeyError, lambda: c[2])
        c.flush()
        assert raises(KeyError, lambda: c[1])
        assert not raises(KeyError, lambda: c[2])
