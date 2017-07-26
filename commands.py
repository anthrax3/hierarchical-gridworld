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

    def set_context(self, string, state):
        self.string = string
        self.state = state

    def execute(self, env, budget, cmd):
        raise NotImplemented()

    def command_for_raise(self):
        return self

    def command_for_fix(self):
        return self

    def messages(self):
        return []

class Malformed(Command):
    pass

def requires_register(f):
    def decorated(command, env, buget):
        if env.registers >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        return f(command, env, budget)
    return decorated

class Interrupted(Command):
    def __init__(self, exhausted=True, previous=None):
        self.exhausted = exhausted
        self.previous = previous

    def make_message(self):
        s = "<<budget exhuasted>>" if exhausted else "<<interrupted>>"
        return Message(s)

class Ask(Command):

    def __init__(self, question, budget=None, **kwargs):
        self.question = question
        self.budget = budget

    def messages(self):
        return [self.question]

    @requires_register
    def execute(self, env, budget):
        if self.budget is None:
            self.budget = env.default_child_budget()
        try:
            question = self.question.instantiate(env.args)
            builtin_response = builtin_handler(question)
            if builtin_response is not None:
                result_cmd = None
                budget_consumed = 1
                answer = builtin_response
            else:
                answerer = env.make_child(question, cmd=self, budget=self.budget)
                answer, result_cmd, answerer, budget_consumed = answerer.run(self.budget, budget)
            answer, env = env.contextualize(answer)
            addressed_question = env.render_question(self.question, budget=self.budget)
            addressed_answer = Message('A: ') + answer
            self.result_cmd = result_cmd
            env = env.add_register(addressed_question, addressed_answer, cmd=self, contextualize=False)
            return None, env, budget_consumed
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

    def command_for_raise(self):
        if hasattr(self, "result_cmd") and self.result_cmd is not None:
            return self.result_cmd
        else:
            return self

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

    def __init__(self, n, **kwargs):
        self.n = n 

    def execute(self, env, budget):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand("invalid index")
        new_m, env = env.contextualize(env.args[n])
        env = env.delete_arg(n, new_m, cmd=self)
        return None, env, 0

class Say(Command):

    def __init__(self, message):
        self.message = message

    def messages(self):
        return [self.message]

    @requires_register
    def execute(self, env, budget):
        try:
            return None, env.add_register(self.message, cmd=self), 1
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Clear(Command):

    def __init__(self, n):
        self.n = n

    def __str__(self):
        return "clear {}".format(self.n)

    def execute(self, env, budget):
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

    def execute(self, env, budget):
        try:
            env = env.add_register(self.message, cmd=self)
            removed = []
            for n in self.ns:
                removed.append(n)
                n -= len([m for m in removed if m < n])
                env = clear(n, env)
            return None, env, 1
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Reply(Command):

    def __init__(self, message):
        self.message = message

    @requires_register
    def execute(self, env, budget):
        try:
            answer = self.message.instantiate(env.args)
            return self.answer, None, 0
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

    def followup(self, env, followup, cmd):
        self.result_cmd = cmd
        followup, env = env.contextualize(followup)
        env = env.copy(parent_cmd=cmd)
        addressed_followup = Message("Reply: ") + followup
        addressed_answer = Message("A: ") + self.message
        env = env.add_register(addressed_answer, addressed_followup,
                contextualize=False, cmd=self)
        return env

    def command_for_raise(self):
        if hasattr(self, "result_cmd"):
            return self.result_cmd
        else:
            return self

class Raise(Command):

    def __init__(self, n, message):
        self.n = n
        self.message = message

    def messages(self):
        return [self.message]

    def execute(self, env, budget):
        register = env.registers[self.n]
        try:
            message = Message("Error: ") + self.message.instantiate(env.args)
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")
        self.old_cmd = register.cmd.command_for_raise()
        error = Message(self.old_cmd.string)
        state = self.old_cmd.state.add_register(error, message, cmd=self)
        return None, state, 0

    def command_for_fix(self):
        if hasattr(self, "old_cmd"):
            return self.old_cmd
        else:
            return self

class Fix(Command):

    def __init__(self, n):
        self.n = n

class Resume(Command):

    def __init__(self, n, message):
        self.n = n
        self.message = message

    def execute(self, env, budget)
        try:
            register = env.registers[self.n]
        except IndexError:
            assert False
            raise BadCommand("invalid index")
        try:
            self.budget = register.cmd.budget
            self.question = register.cmd.question
            result_cmd = register.cmd.result_cmd
        except AttributeError:
            raise BadCommand("can only resume a question register")
        if not hasattr(result_cmd, "followup"):
            raise BadCommand("cannot follow up that command")
        try:
            followup = self.message.instantiate(env.args)
        except messages.BadInstantation:
            raise BadCommand("invalid reference")
        new_env = result_cmd.followup(env, followup, self)
        result, self.result_cmd, budget_command = new_env.run(self.budget, budget)
        result, env = env.contextualize(result)
        answer = Message("A: ") + result
        env = env.add_register(self.question, answer, cmd=self,
                n=self.n, replace=True, contextualize=False)
        return None, env, budget_consumed

    def command_for_raise(self):
        if hasattr(self, "result_cmd"):
            return self.result_cmd
        else:
            return self

class More(Command):

    def __init__(self, n):
        self.n = n

    def execute(self, env, budget):
        try:
            register = env.registers[self.n]
        except IndexError:
            assert False
            raise BadCommand("invalid index")
        try:
            self.budget = register.cmd.budget
            self.question = register.cmd.question
            result_cmd = register.cmd.result_cmd
        except AttributeError:
            raise BadCommand("can only get more from a question register")
        if not isinstance(result_cmd, Interrupted):
            raise BadCommand("can only get more from interrupted questions")
        if result_cmd.exhausted:
            self.budget *= 10
        new_env = result_cmd.state
        new_head = new_env.make_head(self.question, self.budget).copy(args=new_env.registers[0].contents[0].args)
        new_env = new_env.add_register(new_head, cmd=self, replace=True, n=0, contextualize=False).copy(parent_cmd=self)
        budget = min(budget, self.budget)
        if (hasattr(result_cmd.previous, "result_cmd") and 
                isinstance(reuslt_cmd.previous.result_cmd, Interrupted) and
                result_cmd.previous.result_cmd.exhausted == result_cmd.exhausted):
            if isinstance(result_cmd.previous, Ask):
                new_n = len(new_env.registers) - 1
            elif isinstance(result_cmd.previous, More) or isinstance(result_cmd.previous, Resume):
                new_n = result_cmd.previous.n
            else:
                raise ValueError("didn't know that this could be interrupted")
            _, new_env, budget_consumed = Resume(new_n).execute(new_env, budget, src)
        else:
            budget_consumed = 0
        result, self.result_cmd, step_budget_consumed = new_env.run(self.budget, budget - budget_consumed)
        budget_consumed += step_budget_consumed
        result, env = env.contextualize(result)
        addressed_answer = Message('A: ') + result
        env = env.add_register(env.render_question(self.question, self.budget), addressed_answer,
            cmd = self, replace=True, n = self.n, contextualize=False)
        return None, env, budget_consumed
    
#----parsing

parse_cache = {}

def parse(t, string):
    if (t, string) not in parse_cache:
        try:
            parse_cache[(t, string)] = t.parseString(string, parseAll=True)[0]
        except pp.ParseException:
            parse_cache[(t, string)] = Malformed()
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

message_pointer = (raw("#") + number).leaveWhitespace()
message_pointer.setParseAction(lambda x : Pointer(x[0], Message))

def message_action(xs):
    text, args = unweave(xs)
    if text == ("",):
        raise pp.ParseException("can't parse empty message")

message = pp.Forward()
submessage = raw("(") + message + raw(")")
argument = submessage | message_pointer
literal_message = (
        pp.Optional(prose, default="") +
        pp.ZeroOrMore(argument + pp.Optional(prose, default=""))
    ).setParseAction(message_action)
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

resume_command = raw("resume") + w + number + w + message
resume_command.setParseAction(lambda xs : Resume(xs[0], xs[1]))

more_command = raw("more") + w + number
more_command.setParseAction(lambda xs : Resume(xs[0]))

command = ask_command | reply_command | say_command | view_command | clear_command | replace_command | raise_command | fix_command | more_command | resume_command
