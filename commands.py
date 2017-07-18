import pyparsing as pp
from utils import unweave
from messages import Message, Pointer, Channel
import messages
import main

class BadCommand(Exception):
    pass

class Command(object):

    def execute(self, env):
        raise NotImplemented()

    def messages(self):
        return []

class Automatic(Command):

    def __init__(self):
        pass

    def execute(self, env):
        raise Exception("Can't implement automatic command")

    def __str__(self):
        return "<<produced by built-in function>>"

class Ask(Command):

    def __init__(self, message, recipient=None):
        self.message = message
        self.recipient = recipient

    def __str__(self):
        return "ask{} {}".format("" if self.recipient is None else self.recipient, self.message)

    def messages(self):
        return [self.message]

    def execute(self, env):
        try:
            if self.recipient is not None:
                channel = self.recipient.instantiate(env.args)
                translator = channel.translator
                receiver = channel.implementer
            else:
                translator = receiver = None
            message = self.message.instantiate(env.args)
            env = env.add_action(self)
            response = main.ask_Q(message, sender=env, context=env.context, receiver=receiver, translator=translator)
            return None, env.add_message(response)
        except messages.BadInstantiation:
            raise BadCommand()

class View(Command):

    def __init__(self, n):
        self.n = n 

    def execute(self, env):
        return None, self.view(env)

    def view(self, env):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand()
        new_m, env = env.instantiate_message(env.args[n])
        def sub(m):
            if isinstance(m, Pointer):
                if m.n < n:
                    return m
                elif m.n == n:
                    return sub(new_m)
                elif m.n > n:
                    return Pointer(m.n - 1, m.type)
                return new_m if pointer.n == n else m
            elif isinstance(m, Message):
                return m.transform_args_recursive(sub)
            elif isinstance(m, Ask):
                return Ask(message=sub(m.message), recipient=m.recipient)
            elif isinstance(m, Reply):
                return Reply(message=sub(m.message))
            else:
                return m
        return env.copy(
            messages=tuple(sub(m) for m in env.messages),
            actions=tuple(sub(a) for a in env.actions),
            args=env.args[:n] + env.args[n+1:]
        )


    def __str__(self):
        return "view {}".format(self.n)

class Reply(Command):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return "reply {}".format(self.message)

    def messages(self):
        return [self.message]

    def execute(self, env):
        try:
            return self.message.instantiate(env.args), env.add_action(self)
        except messages.BadInstantiation:
            raise BadCommand()

class Fix(Command):

    def __str__(self):
        return "fix"

    def execute(self, env):
        return None, env.add_action(self).add_message(Message(self.fix(env)))
    
    def fix(self, env):
        change = env.fix()
        return "response {} changed".format(change) if change is not None else "nothing was changed"

#----parsing

def parse(t, string):
    try:
        return t.parseString(string, parseAll=True)[0]
    except pp.ParseException:
        return None


def parse_command(s):
    return parse(command, s)

def parse_message(s):
    return parse(message, s)

def parse_view(s):
    return parse(view_command, s)

def parse_fix(s):
    return parse(fix_command, s)

def raw(s):
    return pp.Literal(s).suppress()
def options(*xs):
    result = pp.Literal(xs[0])
    for x in xs[1:]:
        result = result ^ pp.Literal(x)
    return result

number = pp.Word("0123456789").setParseAction(lambda t : int(t[0]))
prose = pp.Word(" ,!?+-/*.;:_<>=&%{}[]\'\"" + pp.alphas).leaveWhitespace()

agent_pointer = (raw("@")+ number).leaveWhitespace()
agent_pointer.setParseAction(lambda x : Pointer(x[0], Channel))

message_pointer = (raw("#") + number).leaveWhitespace()
message_pointer.setParseAction(lambda x : Pointer(x[0], Message))

message = pp.Forward()
submessage = raw("(") + message + raw(")")
argument = submessage | agent_pointer | message_pointer #| world_pointer
literal_message = (
        pp.Optional(prose, default="") +
        pp.ZeroOrMore(argument + pp.Optional(prose, default=""))
    ).setParseAction(lambda xs : Message(tuple(unweave(xs)[0]), *unweave(xs)[1]))
message << literal_message

target_modifier = raw("@")+number
target_modifier.setParseAction(lambda xs : ("recipient", Pointer(xs[0], type=Channel)))

ask_modifiers = pp.ZeroOrMore(target_modifier)
ask_modifiers.setParseAction(lambda xs : dict(list(xs)))

ask_command = (raw("ask")) + ask_modifiers + pp.Empty() + message
ask_command.setParseAction(lambda xs : Ask(xs[1], **xs[0]))

fix_command = (raw('fix'))
fix_command.setParseAction(lambda xs : Fix())

reply_command = (raw("reply")) + pp.Empty() + message
reply_command.setParseAction(lambda xs : Reply(xs[0]))

view_command = raw("view") + pp.Empty() + number
view_command.setParseAction(lambda xs : View(xs[0]))

command = ask_command | reply_command | view_command | fix_command
