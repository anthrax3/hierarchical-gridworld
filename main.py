import utils
from collections import namedtuple
from messages import Message, Pointer, Channel, Referent, BadInstantiation
import messages
import commands
import worlds
import term
import suggestions
from copy import copy

class RegisterMachine(object):
    max_registers = 5
    kind = "implement"
    help_message = """Valid commands:

"Q <question>", e.g. "Q what is one plus one?"
    optionally Q10, Q100, Q1000... to specify budget
"A <answer>", e.g. "A it is two"
"say <message>, e.g. "say #1 is south of #2"
"view n", e.g. "view 0", expand the pointer #n
"clear n", e.g. "clear 3", remove the contents of register 3
"replace n [and m and...] with <message>"
    == clear n && [clear m && ...] say <message>

Valid messages: text interspersed with pointers,
such as "#1", or with sub-messages enclosed in parentheses,
such as "(one more than #2)".

Built in commands:

Q what cell contains the agent in grid #n?
Q what is in cell #n in grid #m?
Q move the agent n/e/s/w in grid #n?
Q what cell is directly n/e/s/w of cell #m?
Q is cell #n n/e/s/w of cell #m?"""

    def __init__(self, registers=(), args=(), context=None):
        self.registers = registers
        self.args = args
        self.context = context

    def copy(self, **kwargs):
        for s in ["registers", "context", "args"]:
            if s not in kwargs: kwargs[s] = self.__dict__[s]
        return self.__class__(**kwargs)

    def run(self, budget=float('inf'), use_cache=True):
        state = self
        message = None
        budget_consumed = 1
        while True:
            if budget_consumed >= budget:
                return Message("<<budget exhausted>>"), state, budget_consumed
            s = get_response(state, error_message=message, use_cache=use_cache, prompt=">> ", kind=self.kind)
            command = commands.parse_command(s)
            if s == "help":
                message = self.help_message
            elif command is None:
                message = "syntax error: {}".format(s)
            else:
                message = None
                try:
                    adder = state.register_adder(s)
                    retval, state, step_budget_consumed = command.execute(state, budget - budget_consumed, adder)
                    budget_consumed += step_budget_consumed
                    if retval is not None:
                        return retval, state, budget_consumed
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

    def register_adder(self, s, contextualize=True):
        def add_register(state, contents, n=None, contextualize=contextualize, **kwargs):
            if n is None:
                n = len(state.registers)
            if contextualize:
                new_contents = []
                for c in contents:
                    new_c, state = state.contextualize(c)
                    new_contents.append(new_c)
                contents = tuple(new_contents)
            new_register = {"input":s, "context":self, "contents":contents}
            new_register.update(kwargs)
            new_registers = state.registers[:n] + (new_register,) + state.registers[n:]
            result = state.copy(registers=new_registers)
            new_register["result"] = result
            return result
        return add_register

    def add_register(self, contents, s="", *args, **kwargs):
        return self.register_adder(s)(self, contents, *args, **kwargs)

    def delete_register(self, n):
        return self.copy(registers = self.registers[:n] + self.registers[n+1:]).delete_unused_args()

    def get_lines(self):
        result = []
        for i, r in enumerate(self.registers):
            prefix = "{}. ".format(i)
            for m in r["contents"]:
                result.append("{}{}".format(prefix, m))
                prefix = " " * len(prefix)
            result.append("")
        return result

    def delete_arg(self, n, new_m=None):
        def sub(m):
            if isinstance(m, tuple):
                return tuple(sub(c) for c in m)
            if isinstance(m, dict):
                result = copy(m)
                result["contents"] = sub(m["contents"])
                return result
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
            for m in r["contents"]:
                for arg in m.get_leaf_arguments():
                    if isinstance(arg, Pointer): in_use[arg.n] = True
        result = self
        for k in reversed(list(range(len(self.args)))):
            if not in_use[k]:
                result = result.delete_arg(k)
        return result

    def clear_response(self):
        self.context


class Answerer(RegisterMachine):

    kind = "translate"
    help_message = """Enter a message to pass it through

Valid commands:

"view n", e.g. "view 0", expand the pointer #n

Valid messages: text interspersed with pointers,
such as "#1", or with sub-messages enclosed in parentheses,
such as "(one more than #2)".

Some messages will be handled automatically:

what cell contains the agent in grid #n?
what is in cell #n in grid #m?
move the agent n/e/s/w in grid #n?
what cell is directly n/e/s/w of cell #m?
is cell #n n/e/s/w of cell #m?"""

    def step(self, default=None):
        answerer = self
        message = None
        while True:
            s = get_response(answerer,
                    kind=self.kind, default=default, error_message=message,
                    prompt="   -> ")
            m = commands.parse_message(s)
            viewer = commands.parse_view(s)
            if s == "help":
                message = self.help_message
            elif m is not None:
                try:
                    return s, m, m.instantiate(answerer.args), answerer
                except BadInstantiation:
                    message = "invalid reference: {}".format(s)
            elif viewer is not None:
                try:
                    answerer = viewer.view(answerer)
                    message = None
                except commands.BadCommand as e:
                    message = "{}: {}".format(e, s)
            else:
                message = "syntax error: {}".format(s)

    def run(self, nominal_budget=float('inf'), budget=float('inf')):
        s, Q_input, Q, answerer = self.step()
        answerer = answerer.add_register((Message("-> ") + Q_input,), s, contextualize=False)
        builtin_result = builtin_handler(Q)
        if builtin_result is not None:
            A_raw = builtin_result
            budget_consumed = 1
            machine = None
        else:
            addressed_Q = Message("Q[{}]: ".format(nominal_budget)) + Q
            machine = RegisterMachine(context=answerer.context).add_register((addressed_Q,))
            A_raw, machine, budget_consumed = machine.run(min(budget, nominal_budget))
        answerer = answerer.add_register((Message("A: ") + A_raw,), s, machine=machine)
        s, A_input, A, answerer = answerer.step()
        answerer = answerer.add_register((Message("-> ") + A_input,), s, contextualize=False)
        return A, answerer, budget_consumed

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
        if use_cache: suggester.set_cached_response(obs, response)
    return response

def main():
    with Context() as context:
        world = worlds.default_world()
        init_message = messages.Message("[] is a grid", messages.WorldMessage(world))
        return RegisterMachine(context=context).add_register((init_message,)).run(use_cache=False)

if __name__ == "__main__":
    try:
        message, environment, budget_consumed = main()
        import IPython
        from worlds import display_history
        IPython.embed()
    except KeyboardInterrupt:
        pass
