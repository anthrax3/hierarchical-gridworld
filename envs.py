import pyparsing as pp
from utils import unweave, areinstances, interleave
import utils
from messages import Message, Pointer, Channel, Referent, addressed_message, BadInstantiation
import messages
import worlds
import elicit
import debug
import term

class Env(object):
    def __init__(self, context=None, messages=(), actions=(), args=()):
        self.messages = messages
        self.actions = actions
        self.context = context
        self.args = args
        assert self.well_formed()

    def well_formed(self):
        return (
            areinstances(self.args, Referent),
            areinstances(self.messages, Message),
            areinstances(self.actions, Command),
        )

    def copy(self, messages=None, actions=None, context=None, args=None, **kwargs):
        if messages is None: messages = self.messages
        if actions is None: actions = self.actions
        if context is None: context = self.context
        if args is None: args = self.args
        return self.__class__(messages=messages, actions=actions, context=context, args=args, **kwargs)

    def instantiate_message(self, m):
        new_env_args = self.args
        def sub(arg):
            nonlocal new_env_args
            if isinstance(arg, Pointer):
                return arg
            else:
                new_env_args = new_env_args + (arg,)
                return Pointer(len(new_env_args) - 1, type=type(arg))
        return m.transform_args(sub), self.copy(args=new_env_args)

    def add_message(self, m):
        new_m, new_env = self.instantiate_message(m)
        return new_env.copy(messages = self.messages + (new_m,))

    def add_action(self, a):
        return self.copy(actions=self.actions + (a,))

    def get_lines(self, debug=False):
        message_lines = [self.display_message(i, m) for i, m in enumerate(self.messages)]
        action_lines = [self.display_action(i, a, debug) for i, a in enumerate(self.actions)]
        return interleave(message_lines, action_lines)

    def fix(self):
        t = self.context.terminal
        t.clear()
        lines = self.get_lines(debug=True)
        for line in lines:
            t.print_line(line)
        done = False
        while not done:
            n = term.get_input(t, prompt="which of these choices do you want to change? ")
            if n == "none":
                return None
            else:
                try:
                    n = int(n)
                    if n >= 0 and n < len(self.actions):
                        old = "{}".format(self.actions[n])
                        message = "previously responded '{}'".format(old)
                        self.copy(messages=self.messages[:n+1], actions=self.actions[:n]).get_response(error_message=message, default=old)
                        return n
                    else:
                        t.print_line("please enter an integer between 0 and {}".format(len(self.actions) - 1))
                except ValueError:
                    t.print_line("please type 'none' or an integer")

class Implementer(Env):
    @staticmethod
    def display_message(i, m):
        return ">>> {}\n".format(m)

    @staticmethod
    def display_action(i, a, debug=False):
        prefix = "<<< "
        if debug: prefix = utils.pad_to("{}.".format(i), len(prefix))
        return "{}{}".format(prefix, a)

    def get_response(self, **kwargs):
        return elicit.get_response(self, kind="implement", prompt="<<< ", **kwargs)

    def run(self, m, use_cache=True):
        implementer = self.add_message(m)
        message = None
        while True:
            s = implementer.get_response(error_message=message, use_cache=use_cache)
            command = parse_command(s)
            if command is None:
                message = "syntax error: {}".format(s)
            else:
                message = None
                try:
                    retval, implementer = command.execute(implementer)
                    if retval is not None:
                        return retval, implementer
                except BadCommand:
                    message = "syntax error: {}".format(s)
                except RecursionError:
                    implementer = self.add_action(command).add_message(Message("stack overflow"))

class Translator(Env):
    @staticmethod
    def display_message(i, m):
        sender = "A" if i % 2 == 0 else "B"
        return "{} >>> {}".format(sender, m)

    @staticmethod
    def display_action(i, a, debug=False):
        receiver = "B" if i % 2 == 0 else "A"
        prefix = "{} <<< ".format(receiver)
        if debug: prefix = utils.pad_to("{}.".format(i), len(prefix))
        return "{}{}\n".format(prefix, a)

    def get_response(self, **kwargs):
        prompt = "{} <<< ".format("B" if len(self.actions) % 2 == 0 else "A")
        return elicit.get_response(self, prompt=prompt, kind="translate", **kwargs)

    def run(self, m, use_cache=True):
        translator = self.add_message(m)
        message = None
        while True:
            s = translator.get_response(error_message=message, use_cache=use_cache)
            viewer = parse_view(s)
            translation = parse_message(s)
            fixer = parse_fix(s)
            if fixer is not None:
                message = fixer.fix(translator)
            elif viewer is not None:
                try:
                    translator = viewer.view(translator)
                    message = None
                except BadCommand:
                    message = "syntax error: {}".format(s)
            elif translation is not None:
                try:
                    def sub(arg):
                        if isinstance(arg, Message):
                            return Translator(context=self.context).run(arg.instantiate(translator.args))[0]
                        else:
                            return arg
                    recursive_translation = translation.transform_args(sub)
                    result = recursive_translation.instantiate(translator.args)
                    return result, translator.add_action(translation)
                except BadInstantiation:
                    message = "syntax error: {}".format(s)
            else:
                message = "syntax error: {}".format(s)

def ask_Q(Q, context, sender, receiver=None, translator=None):
    translator = Translator(context=context) if translator is None else translator
    receiver = Implementer(context=context) if receiver is None else receiver
    builtin_result = builtin_handler(Q)
    if builtin_result is not None:
        translator = translator.add_message(Q).add_action(Q)
        translator = translator.add_message(builtin_result).add_action(builtin_result)
        return builtin_result, Channel(translator=translator, implementer=receiver.add_message(Q).add_action(Automatic()))
    translated_Q, translator = translator.run(Q)
    if sender is not None:
        addressed_Q = messages.addressed_message(translated_Q, implementer=sender, translator=translator, question=True)
    A, receiver = receiver.run(addressed_Q)
    translated_A, translator = translator.run(A)
    addressed_A = messages.addressed_message(translated_A, implementer=receiver, translator=translator)
    return addressed_A

def builtin_handler(Q):
    if (Q.matches("what cell contains the agent in world []?")
            and isinstance(Q.args[0], messages.WorldMessage)):
        grid, agent, history = Q.args[0].world
        return Message("the agent is in cell []", messages.CellMessage(agent))
    if (Q.matches("what is in cell [] in world []?")
            and isinstance(Q.args[0], messages.CellMessage)
            and isinstance(Q.args[1], messages.WorldMessage)):
        cell = Q.args[0].cell
        world = Q.args[1].world
        return Message("it contains []", Message(worlds.look(world, cell)))
    for direction in worlds.directions:
        if (Q.matches("is cell [] {} of cell []?".format(direction))
                and isinstance(Q.args[0], messages.CellMessage)
                and isinstance(Q.args[1], messages.CellMessage)):
            a = Q.args[0].cell
            b = Q.args[1].cell
            if (a - b).in_direction(direction):
                return Message("yes")
            else:
                return Message("no")
        if (Q.matches("move the agent {} in world []".format(direction))
                and isinstance(Q.args[0], messages.WorldMessage)):
            world = Q.args[0].world
            new_world, moved = worlds.move_person(world, direction)
            if moved:
                return Message("the resulting world is []", messages.WorldMessage(new_world))
            else:
                return Message("it can't move that direction")
        if (Q.matches("what cell is directly {} of cell []?".format(direction))
                and isinstance(Q.args[0], messages.CellMessage)):
            cell = Q.args[0].cell
            new_cell, moved = cell.move(direction)
            if moved:
                return Message("the cell []", messages.CellMessage(new_cell))
            else:
                return Message("there is no cell there")
    return None

#----commands

class BadCommand(Exception):
    pass

class Command(object):

    def execute(self, env):
        raise NotImplemented()

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

    def execute(self, env):
        try:
            if self.recipient is not None:
                channel = self.recipient.instantiate(env.args)
                translator = channel.translator
                receiver = channel.implementer
            else:
                translator = receiver = None
            message = self.message.instantiate(env.args)
            response = ask_Q(message, sender=env, context=env.context, receiver=receiver, translator=translator)
            return None, env.add_action(self).add_message(response)
        except BadInstantiation:
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
                return Message(m.text, *[sub(arg) for arg in m.args])
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

    def execute(self, env):
        try:
            return self.message.instantiate(env.args), env.add_action(self)
        except BadInstantiation:
            raise BadCommand()

class Fix(Command):

    def __str__(self):
        return "fix"

    def execute(self, env):
        return None, env.add_action(self).add_message(Message(self.fix(env)))
    
    def fix(self, env):
        change = env.fix()
        return "response {} changed".format(change) if change is not None else "nothing was changed"


def get_messages_in(c):
    if isinstance(c, Reply) or isinstance(c, Ask):
        return [c.message]
    else:
        return []


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
