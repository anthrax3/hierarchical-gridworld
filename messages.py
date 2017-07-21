from utils import areinstances, interleave, unweave
import six

class Referent(object):
    """
    A Referent is anything that can be referred to in a message,
    including Messages, Pointers, and Channels
    """

    symbol = "?"

    def instantiate(self, xs):
        raise NotImplemented()

class BadInstantiation(Exception):
    pass

class Message(Referent):
    """
    A Message consists of text interspersed with Referents
    """

    symbol = "#"

    def __init__(self, text, *args, pending=False):
        if isinstance(text, six.string_types):
            text = tuple(text.split("[]"))
        args = tuple(args)
        self.text = text
        self.args = args 
        self.pending = pending
        if not pending:
            assert self.well_formed()

    def finalize_args(self, args):
        assert self.pending
        self.args = args
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
        return Message(self.text[:-1] + (joined,) + other.text[1:], *(self.args + other.args))

    def format(self, names):
        return "".join(interleave(self.text, names))

    def format_with_indices(self, indices):
        return self.format(["{}{}".format(arg.symbol, index) for arg, index in zip(self.args, indices)])

    def __str__(self):
        def f(arg):
            s = "({})" if arg.symbol == "#" else "{}"
            return s.format(arg)
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
        return Message(self.text, *[f(a) for a in self.args])

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

class Channel(Referent):
    """
    A Channel is a wrapper around an Env, that lets it be pointed to in messages
    """

    symbol = "@"

    def __init__(self, implementer, translator):
        self.implementer = implementer
        self.translator = translator

    def well_formed(self):
        return True

    def instantiate(self, xs):
        raise Exception("should not try to instantiate a channel")

def addressed_message(message, implementer, translator, question=False, budget=float('inf')):
    budget_str = "" if budget == float('inf') else ", budget {}".format(budget)
    channel = Channel(implementer=implementer, translator=translator)
    return Message("{} from []{}: ".format("Q" if question else "A", budget_str), channel) + message

def strip_prefix(message, sep=": "):
    for i, t in enumerate(message.text):
        if sep in t:
            new_args = message.args[i:]
            new_t = sep.join(t.split(sep)[1:])
            new_text = (new_t,) + message.text[i+1:]
            return Message(new_text, *new_args)
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
    A Pointer is an abstract variable,
    which can be instantiated given a list of arguments
    """

    def __init__(self, n, type=Referent):
        self.n = n
        self.type = type
        assert self.well_formed()

    def well_formed(self):
        return (
            issubclass(self.type, Referent) and
            self.type != self.__class__ and
            isinstance(self.n, int)
        )

    def instantiate(self, xs):
        if self.n >= len(xs) or self.n < 0:
            raise BadInstantiation()
        x = xs[self.n]
        if not isinstance(x, self.type): raise BadInstantiation()
        return x

    @property
    def symbol(self):
        return "{}->".format(self.type.symbol)

    def __str__(self):
        return "{}{}".format(self.type.symbol, self.n)
