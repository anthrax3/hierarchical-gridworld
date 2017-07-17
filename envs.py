import pyparsing as pp
from utils import unweave, areinstances, interleave
from messages import Message, Pointer, Channel, Referent, addressed_message, BadInstantiation
import messages
import worlds
import elicit
import debug

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
        new_args = ()
        for arg in m.args:
            if isinstance(arg, Pointer):
                new_arg = arg
            else:
                new_arg = Pointer(len(new_env_args), type=type(arg))
                new_env_args = new_env_args + (arg,)
            new_args = new_args + (new_arg,)
        return Message(m.text, *new_args), self.copy(args=new_env_args)

    def add_message(self, m):
        new_m, new_env = self.instantiate_message(m)
        return new_env.copy(messages = self.messages + (new_m,))

    def add_action(self, a):
        return self.copy(actions=self.actions + (a,))

class Translator(Env):
    def __init__(self, source="A", target="B", **kwargs):
        self.source = source
        self.target = target
        super().__init__(**kwargs)

    def copy(self, source=None, target=None, **kwargs):
        if source is None: source = self.source
        if target is None: target = self.target
        return super().copy(source=source, target=target, **kwargs)

    def get_lines(self):
        message_lines = [str(m) for m in self.messages]
        result = []
        for i, line in enumerate(message_lines):
            result.append(line)
            if i % 2 == 1:
                result.append("")
        return result

    def add_says(self, m):
        return self.add_message(Message("{} says: ".format(self.source)) + m)

    def add_gets(self, m):
        return self.copy(messages = self.messages + (Message(self.get_prompt()) + m,))

    def get_prompt(self):
        return "{} gets: ".format(self.target)

    def add_translation(self, original, translated):
        translator = self.add_says(original)
        translator = translator.add_gets(translation)
        return translator.swap()

    def swap(self):
        return self.copy(source=self.target, target=self.source)

    def query(self, m):
        translator = self.add_says(m)
        message = None
        while True:
            s = elicit.get_response(translator, error_message=message, prompt=self.get_prompt(), kind="translate")
            viewer = parse_view(s)
            translation = parse_message(s)
            if viewer is not None:
                try:
                    translator = viewer.view(translator)
                    message = None
                except BadCommand:
                    message = "syntax error: {}".format(s)
            elif translation is not None:
                try:
                    result = translation.instantiate(translator.args)
                    return result, translator.add_gets(translation).swap()
                except BadInstantiation:
                    message = "syntax error: {}".format(s)
            else:
                message = "syntax error: {}".format(s)

class Implementer(Env):
    def get_lines(self, message_callback=None, action_callback=None):
        if message_callback is None:
            def message_callback(m, env):
                return ">>> {}".format(m)
        if action_callback is None:
            def action_callback(a, env):
                return "<<< {}".format(a)
        message_lines = [message_callback(m, self) for m in self.messages]
        action_lines = [action_callback(a, self) for a in self.actions]
        return interleave(message_lines, ["" for _ in message_lines], action_lines)

    def step(self, act):
        command = parse_command(act)
        if command is None:
            raise BadCommand()
        try:
            retval, new_env = command.execute(self)
        except RecursionError:
            retval, new_env = None, 
            message, retval = None, Message("stack overflow")
        return retval, new_env


def run(env, use_cache=True):
    message = None
    while True:
        act = elicit.get_response(env, use_cache=use_cache, error_message=message, kind="implement")
        try:
            retval, env = env.step(act)
            message = None
            if retval is not None:
                return retval, env
        except BadCommand:
            message = "syntax error: {}".format(act)

def ask_Q(Q, context, sender, receiver=None, translator=None):
    translator = Translator(context=context) if translator is None else translator
    receiver = Implementer(context=context) if receiver is None else receiver
    builtin_result = builtin_handler(Q)
    if builtin_result is not None:
        translator = translator.add_translation(Q, Q)
        translator = translator.add_translation(builtin_result, builtin_result)
        return builtin_result, Channel(translator=translator, implementer=receiver.add_message(Q).add_action(Automatic()))
    translated_Q, translator = translator.query(Q)
    if sender is not None:
        addressed_Q = messages.addressed_message(translated_Q, implementer=sender, translator=translator, question=True)
    receiver = receiver.add_message(addressed_Q)
    A, receiver = run(receiver)
    translated_A, translator = translator.query(A)
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

#class MalformedCommand(Command):
#
#    def __init__(self, text):
#        self.text = text
#
#    def __str__(self):
#        return self.text
#
#    def execute(self, env):
#        return Message("that is not a valid command"), None
#
#class Move(Command):
#
#    def __init__(self, direction, world):
#        self.world_pointer = world
#        self.direction = direction
#
#    def __str__(self):
#        return "move {} in {}".format(self.direction, self.world_pointer)
#
#    def execute(self, env):
#        world = self.world_pointer.instantiate(env.args).world
#        new_world, moved = move_person(world, self.direction)
#        result = Message("the result is []", World(new_world)) if moved else Message("you can't move")
#        return result, None
#
#class Gaze(Command):
#
#    def __init__(self, direction, world):
#        self.world_pointer = world
#        self.direction = direction
#
#    def __str__(self):
#        return "gaze {} in {}".format(self.direction, self.world_pointer)
#
#    def execute(self, env):
#        world = self.world_pointer.instantiate(env.args).world
#        new_world, moved = move_gaze(world, self.direction)
#        result = Message("the result is []", World(new_world)) if moved else Message("you can't move")
#        return result, None
#
#class Look(Command):
#
#    def __init__(self, world):
#        self.world_pointer = world
#
#    def __str__(self):
#        return "look in {}".format(self.world_pointer)
#
#    def execute(self, env):
#        world = self.world_pointer.instantiate(env.args).world
#        result = look(world)
#        return Message("you see {}".format(result)), None

class Fix(Command):

    def __str__(self):
        return "fix"

    def execute(self, env):
        change = debug.fix_env(env)
        m = Message("behavior was changed" if change else "nothing was changed")
        return None, env.add_action(self).add_message(m)

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

#world_pointer = (raw("$") + number).leaveWhitespace()
#world_pointer.setParseAction(lambda xs : Pointer(xs[0], World))
#
message = pp.Forward()
submessage = raw("(") + message + raw(")")
argument = submessage | agent_pointer | message_pointer #| world_pointer
literal_message = (
        pp.Optional(prose, default="") +
        pp.ZeroOrMore(argument + pp.Optional(prose, default=""))
    ).setParseAction(lambda xs : Message(tuple(unweave(xs)[0]), *unweave(xs)[1]))
#message << (message_pointer ^ literal_message)
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

#move_command = raw("move") + options("left", "up", "right", "down") + raw("in") + pp.Empty() + world_pointer
#move_command.setParseAction(lambda xs : Move(xs[0], xs[1]))
#gaze_command = raw("gaze") + options("left", "up", "right", "down") + raw("in") + pp.Empty() + world_pointer
#gaze_command.setParseAction(lambda xs : Gaze(xs[0], xs[1]))
#look_command = raw("look in") + pp.Empty() + world_pointer
#look_command.setParseAction(lambda xs : Look(xs[0]))

command = ask_command | reply_command | view_command | fix_command # | gaze_command | move_command | look_command
