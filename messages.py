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

    def __init__(self, text, *args):
        if isinstance(text, six.string_types):
            text = tuple(text.split("[]"))
        args = tuple(args)
        self.text = text
        self.args = args 
        assert self.well_formed()

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

    def __eq__(self, other):
        return self.text == other.text and self.args == other.args

    def __ne__(self, other):
        return self.text != other.text or self.args != other.args

    def instantiate(self, xs):
        return Message(self.text, *[arg.instantiate(xs) for arg in self.args])

class Channel(Referent):
    """
    A Channel is a wrapper around an Env, that lets it be pointed to in messages
    """

    symbol = "@"

    def __init__(self, env):
        self.env = env

    def well_formed(self):
        return True

    def instantiate(self, xs):
        raise Exception("should not try to instantiate a channel")

def addressed_message(message, env, question=False):
    return Message("{} from []: ".format("Q" if question else "A"), Channel(env)) + message

def is_addressed(message, req=["Q", "A"]):
    if isinstance(req, str): req = [req]
    temp = "{} from "
    def check(t):
        return t in [temp.format(r) for r in req]
    return check(message.text[0])  and isinstance(message.args[0], Channel)

def unaddressed_message(message):
    new_text = (message.text[1][2:],) + message.text[2:]
    return Message(new_text, *message.args[1:])

def submessages(ref, include_root=True):
    if isinstance(ref, Message):
        if include_root:
            yield ref
        for arg in ref.args:
            yield from submessages(arg)

class Pointer(Referent):
    """
    A Pointer is an abstract variable,
    which can be instantiated given a list of arguments
    """


    def __init__(self, n, type=Referent):
        self.n = n
        self.type = type

    def well_formed(self):
        return (
            issubclass(self.type, Referent) and
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

class World(Referent):
    """
    A World refers to a state of gridworld
    """

    symbol = "$"

    def __init__(self, world):
        self.world = world

    def instantiate(self, xs):
        raise Exception("should not instantiate a World")

    def well_formed(self):
        return True
