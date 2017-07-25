import utils
from collections import namedtuple
from messages import Message, Pointer, Channel, Referent, BadInstantiation
import messages
import commands
import term
import suggestions
from copy import copy
from math import log

class Register(object):
    def __init__(self, contents, src=None, result_src=None, parent_src=None, cmd=None):
        self.contents = contents
        self.src = src
        self.cmd = cmd
        self.result_src = result_src
        self.parent_src = parent_src

    def copy(self, **kwargs):
        for k in ["contents", "src", "result_src", "parent_src", "cmd"]:
            if k not in kwargs: kwargs[k] = self.__dict__[k]
        return self.__class__(**kwargs)

class Event(object):
    def __init__(self, context, command_str, command=None, interrupted=False, exhausted=False):
        self.context = context
        self.command_str = command_str
        self.command = command
        self.interrupted = interrupted
        self.exhausted = exhausted

class FixedError(Exception):
    pass

class RegisterMachine(object):
    max_registers = 5
    initial_budget_consumption = 1
    kind = "implement"
    prompt = ">> "
    help_message = """Valid commands:

"ask <question>", e.g. "ask what is one plus one?"
    optionally ask10, ask100, ask1000... to specify budget
"reply <answer>", e.g. "reply it is two"
"say <message>, e.g. "say #1 is south of #2"
"view n", e.g. "view 0", expand the pointer #n
"clear n", e.g. "clear 3", remove the contents of register 3
"replace n [and m and...] with <message>"
    == clear n && [clear m && ...] say <message>

Valid messages: text interspersed with pointers,
such as "#1", or with sub-messages enclosed in parentheses,
such as "(one more than #2)".

Built in commands:

ask what cell contains the agent in grid #n?
ask what is in cell #n in grid #m?
ask move the agent n/e/s/w in grid #n?
ask what cell is directly n/e/s/w of cell #m?
ask is cell #n n/e/s/w of cell #m?"""

    def __init__(self, registers=(), args=(), context=None, use_cache=True, budget=float('inf')):
        self.registers = registers
        self.args = args
        self.context = context
        self.use_cache = use_cache
        self.budget = budget

    def copy(self, **kwargs):
        for s in ["registers", "context", "args", "use_cache", "budget"]:
            if s not in kwargs: kwargs[s] = self.__dict__[s]
        return self.__class__(**kwargs)

    def run(self, nominal_budget=float('inf'), budget=float('inf')):
        state = self
        error = None
        error_replay = None
        budget_consumed = self.initial_budget_consumption
        budget = min(budget, nominal_budget)
        fixed = False 
        src = None
        def ret(m):
            if fixed and self.registers[0].parent_src != state.registers[0].parent_src:
                raise FixedError()
            return m, src, state, budget_consumed
        while True:
            if budget_consumed >= budget or budget_consumed > 1e5:
                error = "<<budget exhausted>>" if budget_consumed >= nominal_budget else "<<interrupted>>"
                src = Event(state, error, interrupted=True, exhausted=budget_consumed >= nominal_budget)
                return ret(Message(error))
            def make_pre_suggestions():
                pre_suggestions = state.pre_suggestions()
                if error_replay is not None: pre_suggestions.append(str(error_replay))
                return pre_suggestions
            s = get_response(state, error_message=error, use_cache=state.use_cache, prompt=state.prompt,
                    kind=state.kind, make_pre_suggestions=make_pre_suggestions)
            command = commands.parse_command(s)
            if s == "help":
                error = state.help_message
                error_replay = None
            elif command is None:
                error = "syntax error: {}".format(s)
                error_replay = s
            elif isinstance(command, commands.Fix):
                old_src = state.registers[command.n].src
                state = old_src.context
                error_replay = str(old_src.command_str)
                error = "previously: {}".format(error_replay)
                fixed = True
            else:
                error = None
                error_replay = None
                src = Event(context=state, command_str=s, command=command)
                try:
                    retval, state, step_budget_consumed = command.execute(state, budget - budget_consumed, src)
                    budget_consumed += step_budget_consumed
                    if retval is not None:
                        return ret(retval)
                except commands.BadCommand as e:
                    error = "{}: {}".format(e, s)
                    error_replay = s

    def dump_and_print(message):
        self.context.terminal.clear()
        for line in self.get_lines():
            self.context.terminal.print_line(line)
        self.context.terminal.print_line(message)
        term.get_input(self.context.terminal)
        return

    def contextualize(self, m):
        new_env_args = self.args
        def sub(arg):
            nonlocal new_env_args
            if isinstance(arg, Pointer):
                return arg
            else:
                new_env_args = new_env_args + (arg,)
                return Pointer(len(new_env_args) - 1, type=type(arg))
        return m.transform_args(sub), self.copy(args=new_env_args)

    def add_register(self, *contents, n=None, contextualize=True, replace=False, **kwargs):
        state = self
        if n is None:
            n = len(state.registers)
        if contextualize:
            new_contents = []
            for c in contents:
                new_c, state = state.contextualize(c)
                new_contents.append(new_c)
            contents = tuple(new_contents)
        new_register = Register(contents, **kwargs)
        m = n+1 if replace else n
        new_registers = state.registers[:n] + (new_register,) + state.registers[m:]
        state = state.copy(registers=new_registers)
        if replace: state = state.delete_unused_args()
        return state

    def delete_register(self, n):
        return self.copy(registers = self.registers[:n] + self.registers[n+1:]).delete_unused_args()
    
    def get_lines(self):
        result = []
        for i, r in enumerate(self.registers):
            prefix = "{}. ".format(i)
            for m in r.contents:
                result.append("{}{}".format(prefix, m))
                prefix = " " * len(prefix)
            result.append("")
        return result

    def delete_arg(self, n, new_m=None, src=None):
        def sub(m):
            if isinstance(m, tuple):
                results = [sub(c) for c in m]
                return tuple(a for a, b in results), any(b for a, b in results)
            elif isinstance(m, Register):
                new_contents, changed = sub(m.contents)
                kwargs = {"src":src} if src is not None and changed else {}
                return m.copy(contents=new_contents, **kwargs), changed
            elif isinstance(m, Pointer):
                if m.n < n:
                    return m, False
                elif m.n == n:
                    assert new_m is not None
                    return sub(new_m)[0], True
                elif m.n > n:
                    return Pointer(m.n - 1, m.type), False
            elif isinstance(m, Message):
                def inner_sub(arg):
                    result, changed = sub(arg)
                    inner_sub.any_changed = changed or inner_sub.any_changed
                    return result
                inner_sub.any_changed = False
                return m.transform_args_recursive(inner_sub), inner_sub.any_changed
            raise ValueError
        new_args = self.args[:n] + self.args[n+1:]
        return self.copy(registers=sub(self.registers)[0], args=new_args)

    def delete_unused_args(self):
        in_use =  {k:False for k in range(len(self.args))}
        for r in self.registers:
            for m in r.contents:
                for arg in m.get_leaf_arguments():
                    if isinstance(arg, Pointer): in_use[arg.n] = True
        result = self
        for k in reversed(list(range(len(self.args)))):
            if not in_use[k]:
                result = result.delete_arg(k)
        return result

    def make_child(self, Q, budget=float('inf'), src=None):
        env = Translator(context=self.context, budget=budget)
        return env.add_register(env.make_head(Q, budget), src=src, parent_src=src)

    def make_head(self, Q, budget=float('inf')):
        return Message('Q[{}]: '.format(budget)) + Q

    def default_child_budget(self):
        if self.budget == float('inf') or self.budget == 10: return self.budget
        return self.budget // 10

    def render_question(self, Q, budget=float('inf')):
        return Message('Q[{}]: '.format(budget)) + Q

    def pre_suggestions(self):
        result = []
        for register in self.registers:
            for m in register.contents:
                s = str(messages.strip_prefix(m))
                if utils.starts_with("A", m.text[0]):
                    result.append("A: " + s)
                elif utils.starts_with("Q", m.text[0]):
                    result.append("Q: " + s)
        return result
    
class Translator(RegisterMachine):

    kind = "translate"
    max_registers = 2
    initial_budget_consumption = 0
    prompt = "-> "

    def make_child(self, Q, budget=float('inf'), src=None):
        env = RegisterMachine(context=self.context, budget=budget)
        return env.add_register(env.make_head(Q, budget), src=src, parent_src=src)

    def default_child_budget(self):
        return self.budget

    def make_head(self, Q, budget=float('inf')):
        return Message('Q[concrete]: ') + Q

    def render_question(self, Q, budget=float('inf')):
        return Message('Q[abstract]: '.format(budget)) + Q

class Context(object):

    def __init__(self):
        self.terminal = term.Terminal()

    def __enter__(self):
        self.suggesters = {"implement":suggestions.ImplementSuggester(), "translate":suggestions.TranslateSuggester()}
        self.terminal.__enter__()
        return self

    def __exit__(self, *args):
        for v in self.suggesters.values():
            v.close()
        self.terminal.__exit__(*args)

def get_response(env, kind, use_cache=True, replace_old=False, error_message=None,
        prompt=">>> ", default=None, make_pre_suggestions=lambda : []):
    if error_message is not None:
        replace_old = True
    lines = env.get_lines()
    obs = "\n".join(lines)
    context = env.context
    suggester = context.suggesters[kind]
    response = suggester.get_cached_response(obs) if (use_cache and not replace_old) else None
    if response is None:
        t = context.terminal
        t.clear()
        for line in lines:
            t.print_line(line)
        if use_cache:
            hints, shortcuts = suggester.make_suggestions_and_shortcuts(env, obs)
        else:
            hints, shortcuts = [], []
        if default is None:
            default = ""
        if error_message is not None:
            t.print_line(error_message)
            t.print_line("")
        response = term.get_input(t, suggestions=hints, shortcuts=shortcuts, prompt=prompt,
                default=default, pre_suggestions=make_pre_suggestions())
        if use_cache:
            suggester.set_cached_response(obs, response)
    return response
