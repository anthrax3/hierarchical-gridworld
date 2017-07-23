import pyparsing as pp
from utils import unweave
from messages import Message, Pointer, Channel
import messages
import main
from math import log

class BadCommand(Exception):
    def __init__(self, explanation):
        self.explanation = explanation
    def __str__(self):
        return self.explanation

class Command(object):

    def execute(self, env, budget, register_adder):
        raise NotImplemented()

class Ask(Command):

    def __init__(self, question, budget=None):
        self.question = question
        self.budget = budget

    def execute(self, env, budget, register_adder):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        if self.budget is None: self.budget = round_budget(budget)
        try:
            question = self.question.instantiate(env.args)
            answerer = main.Answerer(context=env.context).set_head(Message('Q: ') + question)
            answer, answerer, budget_consumed = answerer.run(self.budget, budget)
            answer, env = env.contextualize(answer)
            addressed_question = Message('Q[{}]: '.format(self.budget)) + self.question
            addressed_answer = Message('A: ') + answer
            env = register_adder(env,
                    (addressed_question, addressed_answer),
                    answerer=answerer, contextualize=False)
            return None, env, budget_consumed
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

def round_budget(x):
    if x == float('inf'):
        return float('inf')
    if x <= 10:
        return 10
    return 10**int(log(x) / log(10))

class View(Command):

    def __init__(self, n):
        self.n = n 

    def execute(self, env, budget, register_adder):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand("invalid index")
        new_m, env = env.contextualize(env.args[n])
        env = env.delete_arg(n, new_m)
        return None, env, 0

class Say(Command):

    def __init__(self, message):
        self.message = message

    def execute(self, env, budget, register_adder):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        try:
            return None, register_adder(env, (message,)), 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Clear(Command):

    def __init__(self, n):
        self.n = n

    def __str__(self):
        return "clear {}".format(self.n)

    def execute(self, env, budget, register_adder):
        return None, env.delete_register(self.n), 0

class Replace(Command):

    def __init__(self, ns, message):
        self.ns = ns
        self.message = message

    def execute(self, env, budget, register_adder):
        try:
            env = register_adder(env, (message,))
            removed = []
            for n in self.ns:
                removed.append(n)
                n -= len([m for m in removed if m < n])
                if n < 0 or n >= len(env.args):
                    raise BadCommand("invalid index")
                env = env.delete(n)
            return None, env, 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

#class Replay(Command):
#
#    def __str__(self):
#        return "replay"
#
#    def execute(self, env, budget):
#        last_action = env.actions[-1]
#        if not isinstance(last_action, Ask):
#            raise BadCommand("replay can only follow an action")
#        t = env.context.terminal
#        t.clear()
#        for line in env.get_lines():
#            t.print_line(line)
#        t.print_line("replay the last line? [type 'y' or 'n']")
#        t.set_cursor(t.x, t.y)
#        t.refresh()
#        while True:
#            ch, key = t.poll()
#            if ch == "y":
#                return None, env.history[-1], 0
#            if ch == "n":
#                raise BadCommand("cancelled")
#
class Reply(Command):

    def __init__(self, message):
        self.message = message

    def execute(self, env, budget, register_adder):
        try:
            answer = self.message.instantiate(env.args)
            given_answer = Message("A: ") + self.message
            return answer, register_adder(env, (given_answer,), contextualize=False), 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Fix(Command):

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

def parse_reply(s):
    return parse(reply_command, s)

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
w = pp.Empty() # optional whitespace

number = pp.Word("0123456789").setParseAction(lambda t : int(t[0]))
power_of_ten = (pp.Literal("1") + pp.Word("0")).setParseAction(lambda t : int(t[0] + t[1]))
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

budget_modifier = power_of_ten + w
budget_modifier.setParseAction(lambda xs : ("budget", xs[0]))

ask_modifiers = pp.Optional(budget_modifier)
ask_modifiers.setParseAction(lambda xs : dict(list(xs)))

ask_command = (raw("Q")) + ask_modifiers + w + message
ask_command.setParseAction(lambda xs : Ask(xs[1], **xs[0]))

fix_command = (raw('fix'))
fix_command.setParseAction(lambda xs : Fix())

reply_command = (raw("A")) + w + message
reply_command.setParseAction(lambda xs : Reply(xs[0]))

clear_command = (raw("clear")) + w + number
clear_command.setParseAction(lambda xs : Clear(xs[0]))

replace_command = (raw("replace")) + w + number + pp.ZeroOrMore(w + raw("and") + w + number) + w + raw("with") + w + message
replace_command.setParseAction(lambda xs : Replace(xs[0], xs[1:-1], xs[-1]))

say_command = (raw("say")) + w + message
say_command.setParseAction(lambda xs : Say(xs[0]))

view_command = raw("view") + w + number
view_command.setParseAction(lambda xs : View(xs[0]))

#replay_command = raw("replay")
#replay_command.setParseAction(lambda xs : Replay())
#
command = ask_command | reply_command | say_command | view_command | fix_command | clear_command | replace_command
