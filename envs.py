import pyparsing as pp
from utils import unweave, areinstances, interleave
from messages import Message, Pointer, Channel, Referent, addressed_message, World, BadInstantiation
from world import move_person, move_gaze, look, empty_world
import elicit
import debug

class Env(object):
    def __init__(self, messages=(), actions=(), context=None):
        self.messages = messages
        self.actions = actions
        self.context = context
        all_args = []
        for m in messages:
            all_args.extend(m.args)
        self.args = tuple(all_args)
        assert self.well_formed()

    def well_formed(self):
        return (
            areinstances(self.args, Referent),
            areinstances(self.messages, Message),
        )

    def get_lines(self, message_callback=None, action_callback=None):
        if message_callback is None:
            def message_callback(m, args):
                return ">>> {}".format(m.format_with_indices(args))
        if action_callback is None:
            def action_callback(a):
                return "<<< {}".format(a)
        last_arg = 0
        message_lines = []
        action_lines = []
        for m in self.messages:
            new_last_arg = last_arg + m.size
            message_lines.append(message_callback(m, range(last_arg, new_last_arg)))
            last_arg = new_last_arg
        for a in self.actions:
            action_lines.append(action_callback(a))
        return interleave(message_lines, ["" for _ in message_lines], action_lines)

    def step(self, act):
        command = parse_command(act)
        new_env = self.add_action(command)
        try:
            message, retval = command.execute(new_env)
        except BadInstantiation:
            message, retval = MalformedCommand(str(command)).execute(new_env)
        except RecursionError:
            message, retval = None, Message("stack overflow")
        if message is not None:
            new_env = new_env.add_message(message)
        return retval, new_env

    def add_message(self, m):
        return Env(messages=self.messages + (m,), actions=self.actions, context=self.context)

    def add_action(self, a):
        return Env(messages=self.messages, actions=self.actions + (a,), context=self.context)


def run(env, use_cache=True):
    while True:
        act = elicit.get_action(env, use_cache=use_cache)
        retval, env = env.step(act)
        if retval is not None:
            return retval, env

def ask_Q(Q, context):
    return run(Env(messages=(Q,), context=context))

#----commands

class Command(object):

    def execute(self, env):
        raise NotImplemented()

class Ask(Command):

    def __init__(self, message, recipient=None):
        self.message = message
        self.recipient_pointer = recipient

    def __str__(self):
        return "ask{} {}".format("" if self.recipient_pointer is None else self.recipient_pointer, self.message)

    def execute(self, env):
        message = addressed_message(self.message.instantiate(env.args), env, question=True)
        if self.recipient_pointer is None:
            new_env = Env(context=env.context)
        else:
            new_env = self.recipient_pointer.instantiate(env.args).env
        new_env = new_env.add_message(message)
        response, new_env = run(new_env)
        return addressed_message(response, new_env, question=False), None

def starts_with(p, s):
    return len(s) >= len(p) and s[:len(p)] == p

class View(Command):

    def __init__(self, message):
        self.message = message

    def execute(self, env):
        return self.message.instantiate(env.args), None

    def __str__(self):
        return "view {}".format(self.message)


class Reply(Command):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return "reply {}".format(self.message)

    def execute(self, env):
        return None, self.message.instantiate(env.args)

class MalformedCommand(Command):

    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text

    def execute(self, env):
        return Message("that is not a valid command"), None

class Move(Command):

    def __init__(self, direction, world):
        self.world_pointer = world
        self.direction = direction

    def __str__(self):
        return "move {} in {}".format(self.direction, self.world_pointer)

    def execute(self, env):
        world = self.world_pointer.instantiate(env.args).world
        new_world, moved = move_person(world, self.direction)
        result = Message("the result is []", World(new_world)) if moved else Message("you can't move")
        return result, None

class Gaze(Command):

    def __init__(self, direction, world):
        self.world_pointer = world
        self.direction = direction

    def __str__(self):
        return "gaze {} in {}".format(self.direction, self.world_pointer)

    def execute(self, env):
        world = self.world_pointer.instantiate(env.args).world
        new_world, moved = move_gaze(world, self.direction)
        result = Message("the result is []", World(new_world)) if moved else Message("you can't move")
        return result, None

class Look(Command):

    def __init__(self, world):
        self.world_pointer = world

    def __str__(self):
        return "look in {}".format(self.world_pointer)

    def execute(self, env):
        world = self.world_pointer.instantiate(env.args).world
        result = look(world)
        return Message("you see {}".format(result)), None

class Fix(Command):

    def __str__(self):
        return "fix"

    def execute(self, env):
        change = debug.fix_env(env)
        return Message("behavior was changed" if change else "nothing was changed"), None

def get_messages_in(c):
    if isinstance(c, Reply) or isinstance(c, Ask):
        return [c.message]
    else:
        return []


#----parsing

def parse_command(s):
    try:
        return command.parseString(s, parseAll=True)[0]
    except (pp.ParseException, BadInstantiation):
        return MalformedCommand(s)

def parse_message(s):
    try:
        return message.parseString(s, parseAll=True)[0]
    except (pp.ParseException, BadInstantiation):
        return Message("<<malformed message>>")

def raw(s):
    return pp.Literal(s).suppress()
def options(*xs):
    result = pp.Literal(xs[0])
    for x in xs[1:]:
        result = result ^ pp.Literal(x)
    return result

number = pp.Word("0123456789").setParseAction(lambda t : int(t[0]))
prose = pp.Word(" ,!?+-/*.;:_<>=&%{}[]\'\"" + pp.alphas).leaveWhitespace()

agent_referent = (raw("@")+ number).leaveWhitespace()
agent_referent.setParseAction(lambda x : Pointer(x[0], Channel))

message_referent = (raw("#") + number).leaveWhitespace()
message_referent.setParseAction(lambda x : Pointer(x[0], Message))

world_referent = (raw("$") + number).leaveWhitespace()
world_referent.setParseAction(lambda xs : Pointer(xs[0], World))

message = pp.Forward()
submessage = raw("(") + message + raw(")")
argument = submessage | agent_referent | message_referent | world_referent
literal_message = (
        pp.Optional(prose, default="") +
        pp.ZeroOrMore(argument + pp.Optional(prose, default=""))
    ).setParseAction(lambda xs : Message(tuple(unweave(xs)[0]), *unweave(xs)[1]))
#message << (message_referent ^ literal_message)
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

view_command = raw("view") + pp.Empty() + message_referent
view_command.setParseAction(lambda xs : View(xs[0]))

move_command = raw("move") + options("left", "up", "right", "down") + raw("in") + pp.Empty() + world_referent
move_command.setParseAction(lambda xs : Move(xs[0], xs[1]))
gaze_command = raw("gaze") + options("left", "up", "right", "down") + raw("in") + pp.Empty() + world_referent
gaze_command.setParseAction(lambda xs : Gaze(xs[0], xs[1]))
look_command = raw("look in") + pp.Empty() + world_referent
look_command.setParseAction(lambda xs : Look(xs[0]))

command = ask_command | reply_command | view_command | gaze_command | move_command | look_command | fix_command
