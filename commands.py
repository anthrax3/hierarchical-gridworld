import pyparsing as pp
from utils import unweave
from messages import Message, Pointer, Channel
import messages
import worlds
import main

class BadCommand(Exception):
    def __init__(self, explanation):
        self.explanation = explanation
    def __str__(self):
        return self.explanation

class Command(object):

    def execute(self, env, budget, src):
        raise NotImplemented()

    def messages(self):
        return []

class Ask(Command):

    def __init__(self, question, budget=None):
        self.question = question
        self.budget = budget

    def messages(self):
        return [self.question]

    def execute(self, env, budget, src):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        if self.budget is None:
            self.budget = env.default_child_budget()
        try:
            question = self.question.instantiate(env.args)
            builtin_response = builtin_handler(question)
            if builtin_response is not None:
                result_src = None
                budget_consumed = 1
                answer = builtin_response
            else:
                answerer = env.make_child(question, src=src, budget=self.budget)
                answer, result_src, answerer, budget_consumed = answerer.run(self.budget, budget)
            answer, env = env.contextualize(answer)
            addressed_question = env.render_question(self.question, budget=self.budget)
            addressed_answer = Message('A: ') + answer
            env = env.add_register(addressed_question, addressed_answer, src=src,
                    result_src=result_src, cmd=self, contextualize=False)
            return None, env, budget_consumed
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

def builtin_handler(Q):
    if Q.matches("what cell contains the agent in grid []?"):
        world = messages.get_world(Q.args[0])
        if world is not None:
            grid, agent, history = world
            return Message("the agent is in cell []", messages.CellMessage(agent))
    if Q.matches("what is in cell [] in grid []?"):
        cell = messages.get_cell(Q.args[0])
        world = messages.get_world(Q.args[1])
        if cell is not None and world is not None:
            return Message("it contains []", Message(worlds.look(world, cell)))
    for direction in worlds.directions:
        if Q.matches("is cell [] {} of cell []?".format(direction)):
            a = messages.get_cell(Q.args[0])
            b = messages.get_cell(Q.args[1])
            if a is not None and b is not None:
                if (a - b).in_direction(direction):
                    return Message("yes")
                else:
                    return Message("no")
        if Q.matches("move the agent {} in grid []".format(direction)):
            world = messages.get_world(Q.args[0])
            if world is not None:
                new_world, moved = worlds.move_person(world, direction)
                if moved:
                    return Message("the resulting grid is []", messages.WorldMessage(new_world))
                else:
                    return Message("it can't move that direction")
        if Q.matches("what cell is directly {} of cell []?".format(direction)):
            cell = messages.get_cell(Q.args[0])
            if cell is not None:
                new_cell, moved = cell.move(direction)
                if moved:
                    return Message("the cell []", messages.CellMessage(new_cell))
                else:
                    return Message("there is no cell there")
    return None

class View(Command):

    def __init__(self, n):
        self.n = n 

    def execute(self, env, budget, src):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand("invalid index")
        new_m, env = env.contextualize(env.args[n])
        env = env.delete_arg(n, new_m, src=src)
        return None, env, 0

class Say(Command):

    def __init__(self, message):
        self.message = message

    def messages(self):
        return [self.message]

    def execute(self, env, budget, src):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        try:
            return None, env.add_register(self.message, cmd=self, src=src), 1
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

    def messages(self):
        return [self.message]

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
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
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

    def messages(self):
        return [self.message]

    def execute(self, env, budget, src):
        register = env.registers[self.n]
        try:
            message = Message("Error: ") + self.message.instantiate(env.args)
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")
        if register.result_src is not None:
            old_src = register.result_src
        else:
            old_src = register.src
        error = Message(old_src.command_str)
        state = old_src.context.add_register(error, message, src=old_src, result_src=src, cmd=self)
        return None, state, 0

class Fix(Command):

    def __init__(self, n):
        self.n = n

class Resume(Command):

    def __init__(self, n, message=None, multiplier=1):
        self.n = n
        self.multiplier = multiplier
        self.message = message

    def execute(self, env, budget, src):
        try:
            register = env.registers[self.n]
        except IndexError:
            assert False
            raise BadCommand("invalid index")
        if register.result_src is None: #builtin or not a question
            raise BadCommand("can only give more time to not builtin questions")
        new_budget = register.cmd.budget
        question = register.cmd.question.instantiate(env.args)
        new_cmd = Ask(register.cmd.question, new_budget)
        new_env = register.result_src.context
        if (self.message is None) != (register.result_src.interrupted):
            raise BadCommand("must include follow-up iff question completed successfully")
        if (self.multiplier != 1) != (register.result_src.exhausted):
            raise BadCommand("must provide more time iff budget exhausted")
        if self.multiplier != 1:
            new_budget *= self.multiplier
            new_head = new_env.make_head(question, new_budget).copy(args=new_env.registers[0].contents[0].args)
            new_env = new_env.add_register(new_head, src=src, parent_src=src, replace=True, n=0, contextualize=False)
        if self.message is not None:
            reply_cmd = register.result_src.command
            followup, new_env = new_env.contextualize(self.message)
            followup = Message("Reply: ") + followup
            answer = Message("A: ") + reply_cmd.message.instantiate(new_env.args)
            new_env = new_env.add_register(answer, followup, src=register.result_src, parent_src=src, contextualize=False)
        budget = min(budget, new_budget)
        new_n = len(new_env.registers) - 1
        new_register = new_env.registers[new_n]
        if (register.result_src.interrupted
                and new_register.result_src is not None
                and new_register.result_src.exhausted == register.result_src.exhausted):
            _, new_env, budget_consumed = Resume(new_n, multiplier=self.multiplier).execute(new_env, budget, src)
            result, result_src, new_env, step_budget_consumed = new_env.run(new_budget - budget_consumed, budget - budget_consumed)
            budget_consumed += step_budget_consumed
        #if isinstance(new_env, main.Translator):
        #    if len(new_env.registers) == 1:
        #        new_env = new_env
        #        budget_consumed = 0
        #    else:
        #        _, new_env, budget_consumed = Resume(1, multiplier=self.multiplier).execute(new_env, budget, src) #XXX hacky
        #    result, result_src, new_env, step_budget_consumed = new_env.run(new_budget - budget_consumed, budget - budget_consumed)
        #    budget_consumed += step_budget_consumed
        else:
            result, result_src, new_env, budget_consumed = new_env.run(new_budget, budget)
        result, env = env.contextualize(result)
        addressed_answer = Message('A: ') + result
        env = env.add_register(env.render_question(register.cmd.question, new_budget), addressed_answer,
                src=src, result_src=result_src, contextualize=False, replace=True, n=self.n, cmd=new_cmd)
        return None, env, budget_consumed
    
#----parsing

parse_cache = {}

def parse(t, string):
    if (t, string) not in parse_cache:
        try:
            parse_cache[(t, string)] = t.parseString(string, parseAll=True)[0]
        except pp.ParseException:
            parse_cache[(t, string)] = None
    return parse_cache[(t, string)]

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
    ).setParseAction(lambda xs : Message(tuple(unweave(xs)[0]), unweave(xs)[1]))
message << literal_message

target_modifier = raw("@")+number
target_modifier.setParseAction(lambda xs : ("recipient", Pointer(xs[0], type=Channel)))

budget_modifier = power_of_ten + w
budget_modifier.setParseAction(lambda xs : ("budget", xs[0]))

ask_modifiers = pp.Optional(budget_modifier)
ask_modifiers.setParseAction(lambda xs : dict(list(xs)))

ask_command = (raw("ask") | raw("Q:") | raw("Q")) + ask_modifiers + w + message
ask_command.setParseAction(lambda xs : Ask(xs[1], **xs[0]))

reply_command = (raw("reply") | raw("A:") | raw("A")) + w + message
reply_command.setParseAction(lambda xs : Reply(xs[0]))

clear_command = (raw("clear")) + w + number
clear_command.setParseAction(lambda xs : Clear(xs[0]))

replace_command = (raw("replace")) + w + number + pp.ZeroOrMore(pp.Optional(w + raw("and")) + w + number) + pp.Optional(w + raw("with")) + w + message
replace_command.setParseAction(lambda xs : Replace(xs[:-1], xs[-1]))

say_command = (raw("say") | raw("state")) + w + message
say_command.setParseAction(lambda xs : Say(xs[0]))

view_command = raw("view") + w + number
view_command.setParseAction(lambda xs : View(xs[0]))

raise_command = raw("raise") + w + number + w + message
raise_command.setParseAction(lambda xs : Raise(xs[0], xs[1]))

fix_command = raw("fix") + w + number
fix_command.setParseAction(lambda xs : Fix(xs[0]))

resume_command = raw("resume") + w + number + (w ^ w + message)
resume_command.setParseAction(lambda xs : Resume(*xs))

more_command = raw("more") + w + number
more_command.setParseAction(lambda xs : Resume(xs[0], multiplier=10))

command = ask_command | reply_command | say_command | view_command | clear_command | replace_command | raise_command | fix_command | more_command | resume_command
