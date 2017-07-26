from utils import areinstances, interleave, unweave
import six

class Referent(object):

    def instantiate(self, xs):
        raise NotImplemented()

class BadInstantiation(Exception):
    pass

class Message(Referent):
    """
    A Message consists of text interspersed with Referents
    """

    def __init__(self, text, args=(), pending=False):
        if isinstance(text, six.string_types):
            text = tuple(text.split("[]"))
        if isinstance(args, Referent):
            args = (args,)
        self.text = text
        self.args = args 
        self.pending = pending
        if not pending:
            assert self.well_formed()

    def copy(self, **kwargs):
        for k in ["text", 'args', "pending"]:
            if k not in kwargs: kwargs[k] = self.__dict__[k]
        return Message(**kwargs)

    def finalize_args(self, args):
        assert self.pending
        self.args = args
        self.pending = False
        assert self.well_formed()

    def matches(self, text):
        target = tuple(text.split("[]"))
        return target == self.text

    def well_formed(self):
        return (
            areinstances(self.text, six.string_types) and
            areinstances(self.args, Referent) and
            len(self.text) == len(self.args) + 1
        )

    @property
    def size(self):
        return len(self.args)

    def __add__(self, other):
        joined = self.text[-1] + other.text[0]
        return Message(self.text[:-1] + (joined,) + other.text[1:], self.args + other.args)

    def format(self, names):
        return "".join(interleave(self.text, names))

    def format_with_indices(self, indices):
        return self.format(["#{}".format(index) for index in indices])

    def __str__(self):
        def f(arg):
            return "({})".format(arg) if isinstance(arg, Message) else str(arg)
        return self.format([f(arg) for arg in self.args])

    def instantiate(self, xs):
        return self.transform_args_recursive(lambda arg : arg.instantiate(xs))

    def transform_args_recursive(self, f, cache=None):
        if cache is None: cache = {}
        if self in cache: return cache[self]
        result = Message(self.text, pending=True)
        cache[self] = result
        def sub(a):
            if isinstance(a, Message):
                return a.transform_args_recursive(f, cache=cache)
            else:
                return f(a)
        result.finalize_args(tuple(sub(a) for a in self.args))
        return result

    def transform_args(self, f):
        return Message(self.text, tuple(f(a) for a in self.args))

    def get_leaf_arguments(m, seen=None):
        if seen is None: seen = set()
        seen.add(m)
        for arg in m.args:
            if isinstance(arg, Message):
                yield from arg.get_leaf_arguments(seen)
            else:
                yield arg

class WorldMessage(Message):

    def __init__(self, world):
        self.world = world
        self.args = (self,)
        self.text = ("the gridworld grid ", "")

    def __str__(self):
        return "<<gridworld grid>>"

def get_world(m):
    if isinstance(m, WorldMessage):
        return m.world
    if m.matches("the gridworld grid []"):
        return get_world(m.args[0])
    return None

class CellMessage(Message):

    def __init__(self, cell):
        self.cell = cell
        self.args = (self,)
        self.text = ("the gridworld cell ", "")

    def __str__(self):
        return "<<gridworld cell>>"

def get_cell(m):
    if isinstance(m, CellMessage):
        return m.cell
    if m.matches("the gridworld cell []"):
        return get_cell(m.args[0])
    return None

def addressed_message(message, implementer, translator, question=False, budget=float('inf')):
    budget_str = "" if budget == float('inf') else ", budget {}".format(budget)
    channel = Channel(implementer=implementer, translator=translator)
    return Message("{} from []{}: ".format("Q" if question else "A", budget_str), channel) + message

def address_answer(A, sender):
    return Message("[]: ", sender) + A

def address_question(Q):
    return Message("Q: ") + Q

def strip_prefix(message, sep=": "):
    for i, t in enumerate(message.text):
        if sep in t:
            new_args = message.args[i:]
            new_t = sep.join(t.split(sep)[1:])
            new_text = (new_t,) + message.text[i+1:]
            return Message(new_text, new_args)
    return message

def submessages(ref, include_root=True, seen=None):
    if seen is None: seen = set()
    if isinstance(ref, Message) and ref not in seen:
        if include_root:
            seen.add(ref)
            yield ref
        for arg in ref.args:
            yield from submessages(arg, seen=seen)

class Pointer(Referent):
    """
    A Pointer is an integer, that indexes into a list of arguments
    """

    def __init__(self, n):
        self.n = n
        assert self.well_formed()

    def well_formed(self):
        return (
            isinstance(self.n, int)
        )

    def instantiate(self, xs):
        if self.n >= len(xs) or self.n < 0:
            raise BadInstantiation()
        x = xs[self.n]
        if not isinstance(x, self.type): raise BadInstantiation()
        return x

    def __str__(self):
        return "#{}".format(self.n)
