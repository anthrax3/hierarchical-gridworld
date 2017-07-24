import utils
from collections import namedtuple
from messages import Message, Pointer, Channel, Referent, BadInstantiation
import messages
import commands
import worlds
import term
import suggestions
from copy import copy
from math import log

class Register(object):
    def __init__(self, contents, src=None, result_src=None, cmd=None):
        self.contents = contents
        self.src = src
        self.result_src = result_src
        self.cmd = cmd

    def copy(self, **kwargs):
        for k in ["contents", "src", "result_src", "cmd"]:
            if k not in kwargs: kwargs[k] = self.__dict__[k]
        return self.__class__(**kwargs)

class Event(object):
    def __init__(self, context, command_str):
        self.context = context
        self.command_str = command_str

class FixedError(Exception):
    pass

class RegisterMachine(object):
    max_registers = 5
    initial_budget_consumption = 1
    kind = "implement"
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

    def __init__(self, registers=(), args=(), context=None, use_cache=True):
        self.registers = registers
        self.args = args
        self.context = context
        self.use_cache = use_cache

    def copy(self, **kwargs):
        for s in ["registers", "context", "args", "use_cache"]:
            if s not in kwargs: kwargs[s] = self.__dict__[s]
        return self.__class__(**kwargs)

    def run(self, budget=float('inf')):
        state = self
        message = None
        budget_consumed = self.initial_budget_consumption
        fixed = False 
        src = None
        def ret(m):
            if fixed: #TODO recover from fixing
                raise FixedError()
            return m, src, state, budget_consumed
        while True:
            if budget_consumed >= budget:
                src = Event(state, "<<budget exhausted>>")
                return ret(Message("<<budget exhausted>>"))
            s = get_response(state, error_message=message, use_cache=state.use_cache, prompt=">> ", kind=state.kind, default=state.get_default())
            command = commands.parse_command(s)
            if s == "help":
                message = self.help_message
            elif command is None:
                message = "syntax error: {}".format(s)
            elif isinstance(command, commands.Fix):
                old_src = state.registers[command.n].src
                state = old_src.context
                message = "previously: {}".format(old_src.command_str)
                fixed = True
            else:
                message = None
                src = Event(context=state, command_str=s)
                try:
                    retval, state, step_budget_consumed = command.execute(state, budget - budget_consumed, src)
                    budget_consumed += step_budget_consumed
                    if retval is not None:
                        return ret(retval)
                except commands.BadCommand as e:
                    message = "{}: {}".format(e, s)

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

    def delete_arg(self, n, new_m=None):
        def sub(m):
            if isinstance(m, tuple):
                return tuple(sub(c) for c in m)
            if isinstance(m, Register):
                return m.copy(contents=sub(m.contents))
            elif isinstance(m, Pointer):
                if m.n < n:
                    return m
                elif m.n == n:
                    assert new_m is not None
                    return sub(new_m)
                elif m.n > n:
                    return Pointer(m.n - 1, m.type)
            elif isinstance(m, Message):
                return m.transform_args_recursive(sub)
            raise ValueError
        new_args = self.args[:n] + self.args[n+1:]
        return self.copy(registers=sub(self.registers), args=new_args)

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
        env = Translator(context=self.context)
        return env.add_register(env.make_head(Q, budget), src=src)

    def make_head(self, Q, budget=float('inf')):
        return Message('Q[{}]: '.format(budget)) + Q

    def default_budget(self, budget):
        if budget == float('inf'):
            return float('inf')
        if budget <= 10:
            return 10
        return 10**int(log(budget) / log(10))

    def render_question(self, Q, budget=float('inf')):
        return Message('Q[{}]: '.format(budget)) + Q
    
    def get_default(self):
        return ""

class Translator(RegisterMachine):

    kind = "translate"
    max_registers = 3
    initial_budget_consumption = 0

    def make_child(self, Q, budget=float('inf'), src=None):
        env = RegisterMachine(context=self.context)
        return env.add_register(env.make_head(Q, budget), src=src)

    def default_budget(self, budget):
        if budget == float('inf'):
            return float('inf')
        if budget <= 10:
            return 10
        return 10**int(log(budget) / log(10))

    def make_head(self, Q, budget=float('inf')):
        return Message('Q[concrete]: ') + Q

    def render_question(self, Q, budget=float('inf')):
        return Message('Q[abstract]: '.format(budget)) + Q

    def get_default(self):
        m = self.registers[-1].contents[-1]
        s = str(messages.strip_prefix(m))
        if utils.starts_with("A", m.text[0]):
            return "A " + s
        elif utils.starts_with("Q", m.text[0]):
            return "Q " + s
        else:
            return ""

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

def get_response(env, kind, use_cache=True, replace_old=False, error_message=None, prompt=">>> ", default=None):
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
            if default is None:
                default = suggester.default(env, obs)
        else:
            hints, shortcuts = [], []
            if default is None:
                default = ""
        if error_message is not None:
            t.print_line(error_message)
            t.print_line("")
        response = term.get_input(t, suggestions=hints, shortcuts=shortcuts, prompt=prompt, default=default)
        if use_cache:
            suggester.set_cached_response(obs, response)
    return response

def main():
    with Context() as context:
        world = worlds.default_world()
        init_message = messages.Message("[] is a grid", messages.WorldMessage(world))
        return RegisterMachine(context=context, use_cache=False).add_register(init_message).run()

if __name__ == "__main__":
    try:
        message, src, environment, budget_consumed = main()
        import IPython
        from worlds import display_history
        IPython.embed()
    except (KeyboardInterrupt, FixedError):
        pass
