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
    def __init__(self, contents, cmd=None):
        self.contents = contents
        self.cmd = cmd

    def copy(self, **kwargs):
        for k in ["contents", "cmd"]:
            if k not in kwargs: kwargs[k] = self.__dict__[k]
        return self.__class__(**kwargs)

class FixedError(Exception):
    pass

class RegisterMachine(object):
    max_registers = 6
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
        fixing_state = fixing_s = None
        command = None
        def ret(m):
            if fixed and self.parent_cmd != state.parent_cmd:
                raise FixedError()
            return m, command, budget_consumed
        while True:
            if budget_consumed >= budget or budget_consumed > 1e5:
                exhausted = budget_consumed >= nominal_budget
                command = commands.Interrupted(exhausted, command).set_context(state=state)
                return ret(command.make_message())
            def make_pre_suggestions():
                pre_suggestions = state.pre_suggestions()
                if error_replay is not None: pre_suggestions.append(str(error_replay))
                return pre_suggestions
            s = get_response(state, error_message=error, use_cache=state.use_cache, prompt=state.prompt,
                    kind=state.kind, make_pre_suggestions=make_pre_suggestions)
            command = commands.parse_command(s).set_context(string=s, state=state)
            if fixing_state is not None and s == error_replay:
                error = "nothing was fixed"
                error_cmd = command
                state = fixing_state
                fixing_state = fixing_s = None
            elif s == "help":
                error = state.help_message
                error_cmd = None
            elif isinstance(command, commands.Malformed):
                error = "syntax error: {}".format(s)
                error_cmd = command
            elif isinstance(command, commands.Fix):
                error_cmd = state.registers[command.n].cmd.command_for_fix()
                error = "previously"
                state = error_cmd.state
                fixing_state = state
                fixing_s = s
                fixed = True
            else:
                try:
                    fixing_state = fixing_s = None
                    retval, state, step_budget_consumed = command.execute(state, budget - budget_consumed)
                    budget_consumed += step_budget_consumed
                    if retval is not None:
                        return ret(retval)
                    error = None
                    error_cmd = None
                except commands.BadCommand as e:
                    error = str(e)
                    error_cmd = command

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

    def delete_arg(self, n, new_m=None, cmd=None):
        def sub(m):
            if isinstance(m, tuple):
                results = [sub(c) for c in m]
                return tuple(a for a, b in results), any(b for a, b in results)
            elif isinstance(m, Register):
                new_contents, changed = sub(m.contents)
                kwargs = {"cmd":cmd} if cmd is not None and changed else {}
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

    def make_child(self, Q, budget=float('inf'), cmd=None):
        env = Translator(context=self.context, budget=budget, parent_cmd=cmd)
        return env.add_register(env.make_head(Q, budget), cmd=cmd)

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
    max_registers = 3
    initial_budget_consumption = 0
    prompt = "-> "

    def make_child(self, Q, budget=float('inf'), cmd=None):
        env = RegisterMachine(context=self.context, budget=budget, parent_cmd=cmd)
        return env.add_register(env.make_head(Q, budget), cmd=cmd)

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
