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

    def execute(self, env, budget, src):
        raise NotImplemented()

class Ask(Command):

    def __init__(self, question, budget=None):
        self.question = question
        self.budget = budget

    def execute(self, env, budget, src):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        if self.budget is None:
            self.budget = env.default_budget(budget)
        try:
            question = self.question.instantiate(env.args)
            answerer = env.make_child(question, src=src, budget=self.budget)
            answer, result_src, answerer, budget_consumed = answerer.run(min(self.budget, budget))
            answer, env = env.contextualize(answer)
            addressed_question = env.render_question(self.question, budget=self.budget)
            addressed_answer = Message('A: ') + answer
            env = env.add_register(addressed_question, addressed_answer, src=src,
                    result_src=result_src, cmd=self, contextualize=False)
            return None, env, budget_consumed
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class View(Command):

    def __init__(self, n):
        self.n = n 

    def execute(self, env, budget, src):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand("invalid index")
        new_m, env = env.contextualize(env.args[n])
        env = env.delete_arg(n, new_m)
        return None, env, 0

class Say(Command):

    def __init__(self, message):
        self.message = message

    def execute(self, env, budget, src):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        try:
            return None, env.add_register(message, cmd=self, src=src), 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Clear(Command):

    def __init__(self, n):
        self.n = n

    def __str__(self):
        return "clear {}".format(self.n)

    def execute(self, env, budget, src):
        return None, clear(self.n, env), 0

def clear(n, env):
    if n == 0:
        raise BadCommand("can't remove register 0")
    if n < 0 or n >= len(env.registers):
        raise BadCommand("invalid index")
    return env.delete_register(n)

class Replace(Command):

    def __init__(self, ns, message):
        self.ns = ns
        self.message = message

    def execute(self, env, budget, src):
        try:
            env = env.add_register(self.message, cmd=Say(self.message), src=src)
            removed = []
            for n in self.ns:
                removed.append(n)
                n -= len([m for m in removed if m < n])
                env = clear(n, env)
            return None, env, 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Reply(Command):

    def __init__(self, message):
        self.message = message

    def execute(self, env, budget, src):
        try:
            answer = self.message.instantiate(env.args)
            given_answer = Message("A: ") + self.message
            return answer, env.add_register(given_answer, src=src, cmd=self, contextualize=False), 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Raise(Command):

    def __init__(self, n, message):
        self.n = n
        self.message = message

    def execute(self, env, budget, src):
        register = env.registers[self.n]
        try:
            message = self.message.instantiate(env.args)
        except BadInstantiation:
            raise BadCommand("invalid reference")
        if register.result_src is not None:
            old_src = register.result_src
        else:
            old_src = register.src
        error = Message("Error: {}".format(old_src.command_str))
        state = old_src.context.add_register(error, message, src=old_src, result_src=src, cmd=self)
        return None, state, 0

class Fix(Command):

    def __init__(self, n):
        self.n = n

class More(Command):

    def __init__(self, n):
        self.n = n

    def execute(self, env, budget, src):
        register = env.registers[self.n]
        if not isinstance(register.cmd, Ask) or register.cmd.budget == float("inf"):
            raise BadCommand("can only give more time to questions with finite budget")
        new_budget = register.cmd.budget
        question = register.cmd.question.instantiate(env.args)
        new_budget *= 10
        new_env = register.result_src.context
        new_env = new_env.add_register(new_env.make_head(question, new_budget), src=src, replace=True, n=0)
        if isinstance(new_env, main.Translator):
            _, new_env, budget_consumed = More(1).execute(new_env, budget, src) #XXX hacky
            result, result_src, new_env, step_budget_consumed = new_env.run(budget - budget_consumed)
            budget_consumed += step_budget_consumed
        else:
            result, result_src, new_env, budget_consumed = new_env.run(min(budget, new_budget))
        result, env = env.contextualize(result)
        env = env.add_register(env.render_question(register.cmd.question, new_budget), result,
                src=src, result_src=result_src, contextualize=False, replace=True, n=self.n)
        assert False
        return None, env, budget_consumed
    
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

ask_command = (raw("ask") | raw("Q")) + ask_modifiers + w + message
ask_command.setParseAction(lambda xs : Ask(xs[1], **xs[0]))

reply_command = (raw("reply") | raw("A")) + w + message
reply_command.setParseAction(lambda xs : Reply(xs[0]))

clear_command = (raw("clear")) + w + number
clear_command.setParseAction(lambda xs : Clear(xs[0]))

replace_command = (raw("replace")) + w + number + pp.ZeroOrMore(w + raw("and") + w + number) + w + raw("with") + w + message
replace_command.setParseAction(lambda xs : Replace(xs[:-1], xs[-1]))

say_command = (raw("say")) + w + message
say_command.setParseAction(lambda xs : Say(xs[0]))

view_command = raw("view") + w + number
view_command.setParseAction(lambda xs : View(xs[0]))

raise_command = raw("raise") + w + number + w + message
raise_command.setParseAction(lambda xs : Raise(xs[0], xs[1]))

fix_command = raw("fix") + w + number
fix_command.setParseAction(lambda xs : Fix(xs[0]))

more_command = raw("more") + w + number
more_command.setParseAction(lambda xs : More(xs[0]))

command = ask_command | reply_command | say_command | view_command | clear_command | replace_command | raise_command | fix_command | more_command
