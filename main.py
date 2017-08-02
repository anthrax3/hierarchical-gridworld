import utils
from collections import namedtuple
from messages import Message, Pointer
import messages
import commands
import term
import suggestions
from copy import copy
from math import log

help_message = """Valid commands:

"ask <question>", e.g. "ask what is one plus one?"
    optionally ask10, ask100, ask1000... to specify budget
"reply <answer>", e.g. "reply it is two"
    end the current computation and return an answer
"view n", e.g. "view 0"
    expand the pointer #n
"more n", e.g. "more 2"
    give an interrupted computation more time
"clear n", e.g. "clear 3"
    remove the contents of register 3
"say <message>, e.g. "say #1 is south of #2"
    add a message to a new register
"replace n [m ....] <message>"
    == clear n [&& clear m ...] && say <message>
"resume n <followup>", e.g. "reply 2 don't include zero"
    resume a computation with a follow-up message

Valid messages: text interspersed with pointers,
such as "#1", or with sub-messages enclosed in parentheses,
such as "(one more than #2)".

Built in commands:

ask what cell contains the agent in grid #n?
ask what is in cell #n in grid #m?
ask move the agent n/e/s/w in grid #n?
ask what cell is directly n/e/s/w of cell #m?
ask is cell #n n/e/s/w of cell #m?"""


class Register(utils.Copyable):
    """
    A register stores a series of messages,
    along with the command that most recently modified the register.
    """

    arg_names = ["contents", "cmd"]

    def __init__(self, contents, cmd=None):
        self.contents = contents
        self.cmd = cmd

    def transform_contents(self, f):
        return self.copy(contents=tuple(f(x) for x in self.contents))


class RegisterMachine(utils.Copyable):
    """
    A registser machine maintains a few registers,
    and accepts commands that modify the state of those registers.
    It also maintains a list of message `arguments',
    which registers and commands can reference using pointers.
    """

    max_registers = 7  # if all 7 registers are full, can't make new ones
    cost_to_ask_Q = 0  # asking questions is free, you pay when they are translated
    kind = "implement"  # used to choose which suggestions to show
    prompt = ">> "

    @property
    def child_class(self):
        return Translator

    arg_names = ["registers", "context", "args", "use_cache", "nominal_budget",
                 "budget", "budget_consumed", "parent_cmd", "initial_nominal_budget"]

    def __init__(self,
                 registers=(),
                 args=(),
                 context=None,
                 use_cache=True,
                 nominal_budget=float('inf'),
                 initial_nominal_budget=None,
                 budget=float('inf'),
                 budget_consumed=0,
                 parent_cmd=None):
        self.registers = registers
        self.args = args
        self.context = context
        self.use_cache = use_cache
        self.nominal_budget = nominal_budget
        if initial_nominal_budget is None:
            self.initial_nominal_budget = nominal_budget
        else:
            self.initial_nominal_budget = initial_nominal_budget
        self.budget = min(nominal_budget, budget)
        self.budget_consumed = budget_consumed
        self.parent_cmd = parent_cmd

    def __str__(self):
        return '\n'.join(self.get_lines())

    def dump_and_print(self, message=""):
        if self.context.terminal.closed:
            for line in self.get_lines():
                print(line)
            print(message)
        else:
            self.context.terminal.clear()
            for line in self.get_lines():
                self.context.terminal.print_line(line)
            self.context.terminal.print_line(message)
            term.get_input(self.context.terminal)

    def consume_budget(self, k):
        return self.copy(budget_consumed = self.budget_consumed + k)

    def contextualize(self, m):
        """
        Add each of m's arguments to the machine argument list,
        and then replace each of m's arguments with a pointer.
        """
        new_env_args = self.args

        def sub(field):
            nonlocal new_env_args
            if isinstance(field, Message):
                new_env_args = new_env_args + (field, )
                return Pointer(len(new_env_args) - 1)
            else:
                return field

        return m.transform_fields(sub), self.copy(args=new_env_args)

    def transform_register_fields(self, f):
        """
        Apply f to every argument of every message in every register.
        """

        def g(m):
            return m.transform_fields_recursive(f)

        return self.copy(
            registers=tuple(r.transform_contents(g) for r in self.registers))

    def add_register(self, *contents, n=None, contextualize=True, replace=False, **kwargs):
        """
        Add a new register, containing contents.
        n: the position to add it.
        replace: whether to replace the old register in position n, or insert it into the list
        contextualize: whether to call self.contextualize() on each argument
        **kwargs: get passed on to the register
        """
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
        m = n + 1 if replace else n
        new_registers = state.registers[:n] + (
            new_register, ) + state.registers[m:]
        state = state.copy(registers=new_registers)

        def sub(x):
            if isinstance(x, Pointer):
                return x
            if isinstance(x, RegisterReference):
                new_n = x.n
                if (not replace) and new_n >= n:
                    new_n += 1
                return RegisterReference(new_n)

        state = state.transform_register_fields(sub)
        if replace: state = state.pack_args()
        return state

    def delete_register(self, n):
        """
        Delete the register n, then remove all unused arguments
        """
        return self.copy(
            registers=self.registers[:n] + self.registers[n + 1:]).pack_args()

    def get_lines(self):
        """
        Get a sequence of lines that represent the current state of the register machine.
        """
        result = []
        for i, r in enumerate(self.registers):
            prefix = "{}. ".format(i)
            for m in r.contents:
                result.append("{}{}".format(prefix, m))
                prefix = " " * len(prefix)
            result.append("")
        return result

    def replace_arg(self, n, new_m, cmd=None):
        """
        Replace each pointer to argument n with new_m, then remove argument n
        """

        def affected(m):
            return isinstance(m, Pointer) and m.n == n

        def sub(m):
            return new_m if affected(m) else m

        def transform_register(r):
            any_affected = False
            for m in r.contents:
                any_affected = any_affected or any(affected(l)
                                                   for l in m.get_leaves())
            return r.copy(cmd=cmd) if any_affected and cmd is not None else r

        result = self.copy(
            registers=tuple(transform_register(r) for r in self.registers))
        return result.transform_register_fields(sub).pack_args()

    def pack_args(self):
        """
        Remove unused arguments,
        and renumber arguments based on first appearance.
        """
        arg_order = {}
        new_args = []
        for register in self.registers:
            for message in register.contents:
                for x in message.get_leaves():
                    if isinstance(x, Pointer) and x.n not in arg_order:
                        arg_order[x.n] = len(arg_order)
                        new_args.append(self.args[x.n])
        new_args = tuple(new_args)

        def sub(x):
            if isinstance(x, Pointer):
                return Pointer(n=arg_order[x.n])
            else:
                return x

        return self.copy(args=new_args).transform_register_fields(sub)

    def make_child(self, Q, nominal_budget=float('inf'), cmd=None,
            initial_nominal_budget=None, **kwargs):
        """
        Create a register machine that should be used to answer sub-queries.
        Normal machines create translators, translators create normal machines.
        """
        if initial_nominal_budget is None:
            initial_nominal_budget = nominal_budget
        nominal_budget = min(initial_nominal_budget, nominal_budget)
        env = self.child_class(context=self.context,
                         nominal_budget=nominal_budget,
                         initial_nominal_budget=initial_nominal_budget,
                         parent_cmd=cmd,
                         **kwargs)
        return env.add_register(env.make_head(Q, initial_nominal_budget), cmd=cmd)

    def make_head(self, Q, nominal_budget=float('inf')):
        """
        Create a message that represents the question this machine is trying to answer.
        """
        return Message('Q[{}]: '.format(nominal_budget)) + Q

    def default_child_budget(self):
        """
        The default budget for subqueries that don't specify a budget.
        """
        base_budget = self.initial_nominal_budget
        if base_budget == float('inf') or base_budget == 10:
            return base_budget
        assert utils.is_power_of_ten(base_budget)
        return base_budget // 10

    def render_question(self, Q, nominal_budget=float('inf')):
        """
        Create a message that represents a subquestion.
        """
        return Message('Q[{}]: '.format(nominal_budget)) + Q

    def pre_suggestions(self):
        """
        Return a list of commands that the user can select by pressing <up>
        """
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
    """
    A register machine with fewer registers,
    which is intended to translate a concrete query into an abstract query.
    Everything is optimized to simply relay questions and answers with minimal
    processing.
    There need to be 5 registers only to accomodate errors passing through.
    """

    kind = "translate"
    max_registers = 5
    cost_to_ask_Q = 1
    prompt = "-> "

    @property
    def child_class(self):
        return RegisterMachine

    def default_child_budget(self):
        return self.initial_nominal_budget

    def make_head(self, Q, nominal_budget=float('inf')):
        return Message('Q[concrete]: ') + Q

    def render_question(self, Q, nominal_budget=float('inf'), reg=None):
        return Message('Q[abstract]{}: '.format("" if reg is None else
                                                reg)) + Q


class Context(object):
    """
    A Context is used for looking up and eliciting responses.
    Generally one is created at the entry point and then passed
    on recursively to all child environments.
    """

    def __init__(self):
        self.terminal = term.Terminal()

    def __enter__(self):
        self.suggesters = {
            "implement": suggestions.ImplementSuggester(),
            "translate": suggestions.TranslateSuggester()
        }
        self.terminal.__enter__()
        return self

    def __exit__(self, *args):
        for v in self.suggesters.values():
            v.close()
        self.terminal.__exit__(*args)


class ChangedContinuationError(Exception):
    """
    Raised when we jump out of or into a computation and then try to return

    This is expected to happen sometimes when using Raise or Fix commands
    """
    pass


class UnwindRecursion(Exception):
    """
    We replace RecursionErrors with UnwindRecursion
    In an error handler you can call unwind.
    The first n times you do this, it reraises UnwindRecursion.

    The point is to move some distance away from a recursion error
    before dropping the user back into an interactive mode,
    so that they have some room to breathe.
    """

    def __init__(self, n):
        self.n = n

    def unwound(self):
        if self.n == 0:
            return True
        raise UnwindRecursion(self.n - 1)


def get_response(env,
                 kind,
                 use_cache=True,
                 replace_old=False,
                 error_message=None,
                 prompt=">> ",
                 default=None,
                 make_pre_suggestions=lambda: []):
    if error_message is not None:
        replace_old = True
    lines = env.get_lines()
    obs = "\n".join(lines)
    context = env.context
    suggester = context.suggesters[kind]
    response = suggester.get_cached_response(obs) if (
        use_cache and not replace_old) else None
    if response is None:
        t = context.terminal
        t.clear()
        for line in lines:
            t.print_line(line)
        if use_cache:
            hints, shortcuts = suggester.make_suggestions_and_shortcuts(env,
                                                                        obs)
        else:
            hints, shortcuts = [], []
        if default is None:
            default = ""
        if error_message is not None:
            t.print_line(error_message)
            t.print_line("")
        response = term.get_input(t,
                                  suggestions=hints,
                                  shortcuts=shortcuts,
                                  prompt=prompt,
                                  default=default,
                                  pre_suggestions=make_pre_suggestions())
        if use_cache:
            suggester.set_cached_response(obs, response)
    return response


def run_machine(state):
    command = None
    retval = None
    error = None
    error_cmd = None
    fixing_cmd = None
    while True:
        if state.budget_consumed >= state.budget and retval is None:
            budget_consumed = state.budget_consumed
            exhausted = budget_consumed >= state.nominal_budget
            command = commands.Interrupted(exhausted,
                                           command,
                                           budget_consumed=budget_consumed,
                                           state=state)
            retval = command.make_message()
        if retval is not None:
            if state.parent_cmd is None:
                return retval, command, state.budget_consumed
            retval, state, command = state.parent_cmd.finish(retval, command,
                                                         state.budget_consumed)
        else:
            def make_pre_suggestions():
                pre_suggestions = state.pre_suggestions()
                if error_cmd is not None: pre_suggestions.append(error_cmd.string)
                return pre_suggestions

            if error is None:
                error_message = None
            else:
                if error_cmd is None:
                    error_message = error
                else:
                    error_message = "{}: {}".format(error, error_cmd.string)
            s = get_response(state,
                             error_message=error_message,
                             use_cache=state.use_cache,
                             prompt=state.prompt,
                             kind=state.kind,
                             make_pre_suggestions=make_pre_suggestions)
            command = commands.parse_command(s)
            command = command.copy(string=s, state=state)
            if fixing_cmd is not None and s == error_cmd.string:
                error = "nothing was fixed"
                error_cmd = fixing_cmd
                state = fixing_cmd.state
                fixing_cmd = None
            elif s == "help":
                error = help_message
                error_cmd = None
            elif isinstance(command, commands.Malformed):
                error = "syntax error (type 'help' for help)"
                error_cmd = command
            elif isinstance(command, commands.Fix):
                error_cmd = state.registers[command.n].cmd.command_for_fix()
                error = "previously"
                fixing_cmd = command
                state = error_cmd.state
            else:
                try:
                    fixing_cmd = None
                    retval, state, command = command.execute()
                    error = None
                    error_cmd = None
                except commands.BadCommand as e:
                    error = str(e)
                    error_cmd = command
                except UnwindRecursion as e:
                    if e.unwound():  #reraise unless we've unwound all n steps of recursion
                        error = "Recursion error"
                        error_cmd = command
                except RecursionError:
                    raise UnwindRecursion(30)
