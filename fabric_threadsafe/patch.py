import gevent.monkey
gevent.monkey.patch_all()
import threading
from functools import wraps
from UserDict import UserDict

state = threading.local()


class DictProxy(UserDict, object):
    def __init__(self, getter, dict=None, **kwargs):
        object.__setattr__(self, 'getter', getter)

        if dict is not None:
            self.update(dict)
        if len(kwargs):
            self.update(kwargs)

    @property
    def data(self):
        return self.getter()


class _AttributeDictProxy(DictProxy):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value

    def first(self, *names):
        for name in names:
            value = self.get(name)
            if value:
                return value


class _AliasDictProxy(_AttributeDictProxy):
    def __init__(self, getter, alias_getter, dict=None, **kwargs):
        DictProxy.__init__(self, getter, dict=dict, **kwargs)
        object.__setattr__(self, 'alias_getter', alias_getter)

    def __setitem__(self, key, value):
        if hasattr(self, 'aliases') and key in self.aliases:
            for aliased in self.aliases[key]:
                self[aliased] = value
        else:
            return _AttributeDictProxy.__setitem__(self, key, value)

    def expand_aliases(self, keys):
        ret = []
        for key in keys:
            if key in self.aliases:
                ret.extend(self.expand_aliases(self.aliases[key]))
            else:
                ret.append(key)
        return ret

    @property
    def aliases(self):
        return self.alias_getter()


# monkeypatch
def patch_fabric():
    import sys
    from fabric import state as fstate
    from fabric.thread_handling import ThreadHandler

    default_env = fstate.env
    default_output = fstate.output

    def get_state_output(state=state, default_output=default_output):
        if not hasattr(state, 'output'):
            state.output = default_output.copy()
        return state.output

    def get_state_output_aliases(state=state, default_output=default_output):
        if not hasattr(state, 'aliases'):
            state.aliases = default_output.__dict__.get('aliases')
        return state.aliases

    def get_state_env(state=state, default_env=default_env):
        if not hasattr(state, 'env'):
            state.env = default_env.copy()
        return state.env

    fstate.env = _AttributeDictProxy(get_state_env)
    fstate.output = _AliasDictProxy(get_state_output, get_state_output_aliases)

    def transfer_state(func):
        def inner(old_state):
            @wraps(func)
            def decorated(*args, **kwargs):
                state.__dict__.update(old_state)
                return func(*args, **kwargs)
            return decorated
        return inner(state.__dict__)

    def th_init_patcher(func):
        @wraps(func)
        def decorated(self, name, callable, *args, **kwargs):
            callable = transfer_state(callable)
            return func(self, name, callable, *args, **kwargs)
        return decorated

    ThreadHandler.__init__ = th_init_patcher(ThreadHandler.__init__)

    for m, v in sys.modules.items():
        if (v and (m.startswith('fabric.') or m == 'fabric')
                and m != 'fabric.state'):
            reload(v)

patch_fabric()


# /monkeypatch
def test_patch():
    from fabric.thread_handling import ThreadHandler
    from fabric.api import env, output

    env.host_string = 'myhost'
    output['test'] = 'ok'

    # test dict proxy
    assert env['host_string'] == 'myhost'
    assert output['test'] == 'ok'

    assert len(output.expand_aliases(['everything'])) > 0

    # test attribute dict proxy
    assert env.host_string == 'myhost'

    # test state transfer
    def test_state_transfer(x, y):
        assert x == 1
        assert y == 2
        assert env.host_string == 'myhost'

    # test fresh state
    def test_default(x, y):
        assert x == 1
        assert y == 2
        assert env.host_string == None

    th = ThreadHandler('footest', test_state_transfer, [1], {'y': 2})
    th.thread.join()

    t = threading.Thread(None, test_default, args=[1], kwargs={'y': 2})
    t.start()
    t.join()

    print 'OK'

if __name__ == '__main__':
    test_patch()
