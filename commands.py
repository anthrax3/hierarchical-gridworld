import pyparsing as pp
from utils import unweave
from messages import Message, Pointer, RegisterReference
import messages
import worlds
import main

class BadCommand(Exception):
    def __init__(self, explanation, **kwargs):
        super().__init__(**kwargs)
        self.explanation = explanation
    def __str__(self):
        return self.explanation

class Command(object):

    arg_names = []

    def __init__(self, string=None, state=None, budget_consumed=0, **kwargs):
        self.string = string
        self.state = state
        self.budget_consumed = budget_consumed

    def execute(self, env, budget, cmd):
        raise NotImplemented()

    def copy(self, **kwargs):
        for k in ["string", "state", "budget_consumed"] + self.arg_names:
            if k not in kwargs: kwargs[k] = self.__dict__[k]
        return self.__class__(**kwargs)

    def command_for_raise(self):
        return self

    def command_for_fix(self):
        return self

    def messages(self):
        return []

    def budget_consumed_for_more(self):
        return self.budget_consumed

class Malformed(Command):
    pass

def requires_register(f):
    def decorated(command, env, budget):
        if len(env.registers) >= env.max_registers:
            raise BadCommand("no free registers (use clear or replace instead)")
        return f(command, env, budget)
    return decorated

class Interrupted(Command):
    arg_names = ["exhausted", "previous"]
    def __init__(self, exhausted=True, previous=None, **kwargs):
        self.exhausted = exhausted
        self.previous = previous
        super().__init__(**kwargs)

    def make_message(self):
        s = "<<budget exhuasted>>" if self.exhausted else "<<interrupted>>"
        return Message(s)

class Ask(Command):

    arg_names=["question", "nominal_budget", "result_cmd"]
    def __init__(self, question, nominal_budget=None, result_cmd=None, **kwargs):
        super().__init__(**kwargs)
        self.question = question
        self.nominal_budget = nominal_budget
        self.result_cmd = result_cmd

    def messages(self):
        return [self.question]

    @requires_register
    def execute(self, env, budget):
        nominal_budget = env.default_child_budget() if self.nominal_budget is None else self.nominal_budget
        try:
            question = self.question.instantiate(env.args)
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")
        builtin_response = builtin_handler(question)
        if builtin_response is not None:
            result_cmd = None
            budget_consumed = 1
            answer = builtin_response
        else:
            answerer = env.make_child(question, cmd=self, nominal_budget=nominal_budget)
            answer, result_cmd, budget_consumed = answerer.run(nominal_budget, budget)
        answer, env = env.contextualize(answer)
        addressed_question = env.render_question(self.question, nominal_budget=nominal_budget)
        addressed_answer = Message('A: ') + answer
        cmd = self.copy(result_cmd=result_cmd,
                nominal_budget=nominal_budget,
                budget_consumed=budget_consumed)
        env = env.add_register(addressed_question, addressed_answer, cmd=cmd, contextualize=False)
        return None, env, cmd

    def command_for_raise(self):
        return self if self.result_cmd is None else self.result_cmd

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

    arg_names = ["n"]
    def __init__(self, n, **kwargs):
        super().__init__(**kwargs)
        self.n = n 

    def execute(self, env, budget):
        n = self.n
        if n < 0 or n >= len(env.args):
            raise BadCommand("invalid index")
        new_m, env = env.contextualize(env.args[n])
        env = env.delete_arg(n, new_m, cmd=self)
        return None, env, self

class Say(Command):

    arg_names = ["message"]
    def __init__(self, message, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def messages(self):
        return [self.message]

    @requires_register
    def execute(self, env, budget):
        cmd = self.copy(budget_consumed=1)
        try:
            return None, env.add_register(self.message, cmd=cmd), cmd
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Clear(Command):

    arg_names = ["n"]
    def __init__(self, n, **kwargs):
        super().__init__(**kwargs)
        self.n = n

    def __str__(self):
        return "clear {}".format(self.n)

    def execute(self, env, budget):
        return None, clear(self.n, env), self

def clear(n, env):
    if n == 0:
        raise BadCommand("can't remove register 0")
    if n < 0 or n >= len(env.registers):
        raise BadCommand("invalid index")
    return env.delete_register(n)

class Replace(Command):

    arg_names = ["ns", "message"]
    def __init__(self, ns, message, **kwargs):
        super().__init__(**kwargs)
        self.ns = ns
        self.message = message

    def messages(self):
        return [self.message]

    def execute(self, env, budget):
        cmd = self.copy(budget_consumed=1)
        try:
            env = env.add_register(self.message, cmd=cmd)
            removed = []
            for n in self.ns:
                removed.append(n)
                n -= len([m for m in removed if m < n])
                env = clear(n, env)
            return None, env, cmd
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

class Assert(Command):

    arg_names = ["assertion", "error_cmd", "result_cmd", "failed"]
    def __init__(self, assertion, error_cmd=None, result_cmd=None, failed=False, **kwargs):
        super().__init__(**kwargs)
        self.assertion = assertion
        self.error_cmd = error_cmd
        self.result_cmd = result_cmd
        self.failed = failed

    def execute(self, env, budget):
        register = env.registers[-1]
        if not isinstance(register.cmd, Raise):
            if not isinstance(register.cmd, Assert) or register.cmd.failed:
                raise BadCommand("can only assert after a raise")
        assertion = Message("T[rue] or F[alse] (can give explanation for F) -- ") + self.assertion.instantiate(env.args)
        state = env.delete_register(len(env.registers)-1)
        answerer = state.make_child(assertion, cmd=self, nominal_budget=state.nominal_budget)
        answer, result_cmd, budget_consumed = answerer.run(state.nominal_budget, budget)
        cmd = self.copy(error_cmd=register.cmd, budget_consumed=budget_consumed, result_cmd=result_cmd)
        if answer.matches("T") or answer.matches("t"):
            new_contents = register.contents + (Message("Checked: ") + self.assertion,)
            state = state.add_register(*new_contents, contextualize=False, cmd=cmd)
        else:
            cmd = cmd.copy(failed=True)
            answer, state = state.contextualize(answer)
            state = state.add_register(
                    Message("Assert: ") + self.assertion,
                    Message("A: ") + answer, cmd=cmd, contextualize=False)
        return None, state, cmd

    def command_for_raise(self):
        if self.failed:
            return self.result_cmd
        else:
            return self.error_cmd.command_for_raise()

    def command_for_fix(self):
        if self.failed:
            return self.result_cmd
        else:
            return self

class Reply(Command):

    arg_names = ["message", "result_cmd"]
    def __init__(self, message, result_cmd=None, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.result_cmd = result_cmd

    @requires_register
    def execute(self, env, budget):
        try:
            answer = self.message.instantiate(env.args)
            return answer, env, self
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")

    def followup(self, env, followup, cmd):
        followup, env = env.contextualize(followup)
        env = env.copy(parent_cmd=cmd)
        addressed_answer = Message("A: ") + self.message
        addressed_followup = Message("Q: ") + followup
        new_contents = env.registers[0].contents + (addressed_answer, addressed_followup)
        env = env.add_register(*new_contents,
                contextualize=False, cmd=self.copy(result_cmd=cmd), replace=True, n=0)
        return env

    def command_for_raise(self):
        return self if self.result_cmd is None else self.result_cmd

class Raise(Command):

    arg_names = ["n", "message", "old_cmd"]
    def __init__(self, n, message, old_cmd=None, **kwargs):
        super().__init__(**kwargs)
        self.n = n
        self.message = message
        self.old_cmd = old_cmd

    def messages(self):
        return [self.message]

    @requires_register
    def execute(self, env, budget):
        register = env.registers[self.n]
        try:
            message = Message("Error: ") + self.message.instantiate(env.args)
        except messages.BadInstantiation:
            raise BadCommand("invalid reference")
        old_cmd = register.cmd.command_for_raise()
        error = Message(old_cmd.string)
        cmd = self.copy(old_cmd=old_cmd)
        state = old_cmd.state.add_register(error, message, cmd=cmd)
        return None, state, cmd

    def command_for_fix(self):
        return self if self.old_cmd is None else self.old_cmd

class Fix(Command):

    arg_names = ["n"]
    def __init__(self, n, **kwargs):
        super().__init__(**kwargs)
        self.n = n

class Resume(Command):

    arg_names = ["n", "message", "nominal_budget", "question", "result_cmd", "previous"]
    def __init__(self, n, message, nominal_budget=None, question=None, result_cmd=None, previous=None, **kwargs):
        super().__init__(**kwargs)
        self.n = n
        self.message = message
        self.nominal_budget = nominal_budget
        self.question = question
        self.result_cmd = result_cmd
        self.previous = previous

    def execute(self, env, budget):
        try:
            register = env.registers[self.n]
        except IndexError:
            assert False
            raise BadCommand("invalid index")
        try:
            resume_budget = register.cmd.nominal_budget
            resume_question = register.cmd.question
            result_cmd = register.cmd.result_cmd
        except AttributeError:
            raise BadCommand("can only resume a question register")
        if not hasattr(result_cmd, "followup"):
            raise BadCommand("cannot follow up that command")
        try:
            followup = self.message.instantiate(env.args)
        except messages.BadInstantation:
            raise BadCommand("invalid reference")
        new_env = result_cmd.followup(result_cmd.state, followup, self)
        old_budget_consumed = register.cmd.budget_consumed_for_more()
        result, resume_result_cmd, budget_consumed = new_env.run(
                resume_budget - old_budget_consumed, budget,
            )
        result, env = env.contextualize(result)
        addressed_question = Message("Q: ") + self.message
        addressed_answer = Message("A: ") + result
        old_contents = register.contents
        new_contents = old_contents + (addressed_question, addressed_answer)
        cmd = self.copy(nominal_budget=resume_budget, question=resume_question,
                result_cmd=resume_result_cmd, budget_consumed=budget_consumed, previous=register.cmd)
        env = env.add_register(*new_contents, cmd=cmd, contextualize=False, n=self.n, replace=True)
        return None, env, cmd

    def command_for_raise(self):
        return self if self.result_cmd is None else self.result_cmd
    
    def budget_consumed_for_more(self):
        result = self.budget_consumed
        if self.previous is not None:
            result += self.previous.budget_consumed_for_more()
        return result

class More(Command):

    arg_names = ["n", "result_cmd", "nominal_budget", "question"]
    def __init__(self, n, result_cmd=None, nominal_budget=None, question=None, **kwargs):
        super().__init__(**kwargs)
        self.n = n
        self.result_cmd = result_cmd
        self.nominal_budget = nominal_budget
        self.question = question

    def execute(self, env, budget):
        try:
            register = env.registers[self.n]
        except IndexError:
            assert False
            raise BadCommand("invalid index")
        try:
            more_budget = register.cmd.nominal_budget
            more_question = register.cmd.question
            result_cmd = register.cmd.result_cmd
        except AttributeError:
            raise BadCommand("can only get more from a question register")
        if not isinstance(result_cmd, Interrupted):
            raise BadCommand("can only get more from interrupted questions")
        if result_cmd.exhausted:
            more_budget *= 10
        new_env = result_cmd.state
        new_head = new_env.make_head(more_question, more_budget).copy(args=new_env.registers[0].contents[0].args)
        new_first_register = (new_head,) + new_env.registers[0].contents[1:]
        new_env = new_env.add_register(*new_first_register, cmd=self, replace=True, n=0, contextualize=False).copy(parent_cmd=self)
        budget = min(budget, more_budget)
        if (hasattr(result_cmd.previous, "result_cmd") and 
                isinstance(result_cmd.previous.result_cmd, Interrupted) and
                result_cmd.previous.result_cmd.exhausted == result_cmd.exhausted):
            if isinstance(result_cmd.previous, Ask):
                new_n = len(new_env.registers) - 1
            elif isinstance(result_cmd.previous, More) or isinstance(result_cmd.previous, Resume):
                new_n = result_cmd.previous.n
            else:
                raise ValueError("didn't know that this could be interrupted")
            _, new_env, recursive_more_cmd = self.copy(n=new_n).execute(new_env, budget)
            previous_cmd = recursive_more_cmd
            budget_consumed = recursive_more_cmd.budget_consumed
        else:
            budget_consumed = 0
            previous_cmd = None
        result, more_result_cmd, step_budget_consumed = new_env.run(more_budget - budget_consumed, budget - budget_consumed, previous_cmd=previous_cmd)
        budget_consumed += step_budget_consumed
        result, env = env.contextualize(result)
        addressed_answer = Message('A: ') + result
        more_cmd = self.copy(nominal_budget=more_budget, question=more_question,
                result_cmd=more_result_cmd, budget_consumed=budget_consumed)
        new_addressed_q = env.render_question(more_question, more_budget)
        new_contents = (new_addressed_q,) + register.contents[1:-1] + (addressed_answer,)
        env = env.add_register(*new_contents,
                cmd=more_cmd, replace=True, n = self.n, contextualize=False)
        return None, env, more_cmd
    
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
message_pointer.setParseAction(lambda x : Pointer(x[0]))

register_reference = (raw("@") + number).leaveWhitespace()
register_reference.setParseAction(lambda x : RegisterReference(x[0]))

def message_action(xs):
    text, args = unweave(xs)
    if text == ("",):
        raise pp.ParseException("can't parse empty message")
    return Message(text, args)

message = pp.Forward()
submessage = raw("(") + message + raw(")")
argument = submessage | message_pointer | register_reference
literal_message = (
        pp.Optional(prose, default="") +
        pp.ZeroOrMore(argument + pp.Optional(prose, default=""))
    ).setParseAction(message_action)
message << literal_message

budget_modifier = power_of_ten + w
budget_modifier.setParseAction(lambda xs : ("nominal_budget", xs[0]))

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

resume_command = (raw("resume") | raw("ask@")) + w + number + w + message
resume_command.setParseAction(lambda xs : Resume(xs[0], xs[1]))

more_command = raw("more") + w + number
more_command.setParseAction(lambda xs : More(xs[0]))

assert_command = raw("assert") + w + message
assert_command.setParseAction(lambda xs : Assert(xs[0]))

command = ask_command | reply_command | say_command | view_command | clear_command | replace_command | raise_command | fix_command | more_command | resume_command | assert_command
