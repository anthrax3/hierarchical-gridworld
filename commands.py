import pyparsing as pp
from utils import unweave
from messages import Message, Pointer, Channel
import messages
import main

class BadCommand(Exception):
    def __init__(self, explanation):
        self.explanation = explanation
    def __str__(self):
        return self.explanation

class Command(object):

    def execute(self, env, budget):
        raise NotImplemented()

    def messages(self):
        return []

class Placeholder(Command):

    def __init__(self, s):
        self.s = s
        pass

    def execute(self, env, budget):
        raise Exception("Can't implement placeholder command")

    def __str__(self):
        return self.s

class BudgetExhausted(Command):

    def __init__(self):
        pass

    def execute(self, env, budget):
        raise Exception("Can't implement automatic command")

    def __str__(self):
        return "<<produced by built-in function>>"

class Ask(Command):

    def __init__(self, message, recipient=None, budget=4):
        self.message = message
        self.recipient = recipient
        self.budget = budget

    def __str__(self):
        return "ask{} {}".format("" if self.recipient is None else self.recipient, self.message)

    def messages(self):
        return [self.message]

    def more(self):
        return Ask(message=self.message, recipient=self.recipient, budget =4*self.budget)

    def execute(self, env, budget):
        try:
            if self.recipient is not None:
                channel = self.recipient.instantiate(env.args)
                translator = channel.translator
                receiver = channel.implementer
            else:
                translator = receiver = None
            message = self.message.instantiate(env.args)
            env = env.add_action(self)
            response, budget_consumed = main.ask_Q(message,
                    sender=env, context=env.context, receiver=receiver, translator=translator,
                    nominal_budget=self.budget, invisible_budget=budget)
            return None, env.add_message(response), budget_consumed
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")


class View(Command):

    def __init__(self, n):
        self.n = n 

    def execute(self, env, budget):
        return None, self.view(env), 0

    def view(self, env):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand("invalid index")
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

class More(Command):

    def __str__(self):
        return "more"

    def execute(self, env, budget):
        last_action = env.actions[-1]
        if not isinstance(last_action, Ask):
            raise BadCommand("more can only follow an action")
        new_action = last_action.more()
        return new_action.execute(env.history[-1], budget)

class Reply(Command):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return "reply {}".format(self.message)

    def messages(self):
        return [self.message]

    def execute(self, env, budget):
        try:
            return self.message.instantiate(env.args), env.add_action(self), 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Fix(Command):

    def __str__(self):
        return "fix"

    def execute(self, env, budget):
        return None, env.add_action(self).add_message(Message(self.fix(env))), 0
    
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

more_command = raw("more")
more_command.setParseAction(lambda xs : More())

command = ask_command | reply_command | view_command | fix_command | more_command

#-----help message

help_message = """Valid commands:

"ask Q", e.g. "ask what is one plus one?"
"reply A", e.g. "reply it is two"
"view n", e.g. "view 0", expand the pointer #n
"more", rerun the previous query with a larger budget
"fix", change one of the previous actios in this context

Valid messages: text interspersed with pointers such as "#1",
sub-messages enclosed in parentheses such as "(one more than #2)",
or channels such as "@0"

Built in commands:

ask what cell contains the agent in world #n?
ask what is in cell #n in world #m?
ask move the agent n/e/s/w in world #n?
ask what cell is directly n/e/s/w of cell #m?
ask is cell #n n/e/s/w of cell #m?"""
