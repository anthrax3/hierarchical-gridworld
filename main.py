import utils
from messages import Message, Pointer, Channel, Referent, addressed_message, BadInstantiation
import messages
import commands
import worlds
import term
import suggestions

class Env(object):
    def __init__(self, context=None, messages=(), actions=(), args=(), history=()):
        self.messages = messages
        self.actions = actions
        self.context = context
        self.args = args
        self.history = history

    def copy(self, messages=None, actions=None, context=None, args=None, history=None, **kwargs):
        if messages is None: messages = self.messages
        if actions is None: actions = self.actions
        if context is None: context = self.context
        if args is None: args = self.args
        if history is None: history = self.history
        return self.__class__(messages=messages, actions=actions, context=context, args=args, history=history, **kwargs)

    def instantiate_message(self, m):
        new_env_args = self.args
        def sub(arg):
            nonlocal new_env_args
            if isinstance(arg, Pointer):
                return arg
            else:
                new_env_args = new_env_args + (arg,)
                return Pointer(len(new_env_args) - 1, type=type(arg))
        return m.transform_args(sub), self.copy(args=new_env_args)

    def add_message(self, m):
        new_m, new_env = self.instantiate_message(m)
        return new_env.copy(messages = self.messages + (new_m,))

    def add_action(self, a):
        return self.copy(actions=self.actions + (a,), history=self.history + (self,))

    def get_lines(self, debug=False):
        message_lines = [self.display_message(i, m) for i, m in enumerate(self.messages)]
        action_lines = [self.display_action(i, a, debug) for i, a in enumerate(self.actions)]
        return utils.interleave(message_lines, action_lines)

    def fix(self):
        t = self.context.terminal
        t.clear()
        lines = self.get_lines(debug=True)
        for line in lines:
            t.print_line(line)
        done = False
        while not done:
            n = term.get_input(t, prompt="which of these choices do you want to change? ")
            if n == "none":
                return None
            else:
                try:
                    n = int(n)
                    if n >= 0 and n < len(self.actions):
                        old = "{}".format(self.actions[n])
                        message = "previously responded '{}'".format(old)
                        self.history[n].get_response(error_message=message, default=old)
                        return n
                    else:
                        t.print_line("please enter an integer between 0 and {}".format(len(self.actions) - 1))
                except ValueError:
                    t.print_line("please type 'none' or an integer")

class Implementer(Env):
    @staticmethod
    def display_message(i, m):
        return ">>> {}\n".format(m)

    @staticmethod
    def display_action(i, a, debug=False):
        prefix = "<<< "
        if debug: prefix = utils.pad_to("{}.".format(i), len(prefix))
        return "{}{}".format(prefix, a)

    def get_response(self, **kwargs):
        return get_response(self, kind="implement", prompt="<<< ", **kwargs)

    def run(self, m, use_cache=True, budget=float('inf')):
        implementer = self.add_message(m)
        message = None
        budget_consumed = 1 #the cost of merely asking a question
        while True:
            if budget_consumed >= budget:
                return Message("<<budget exhausted>>"), implementer.add_action(commands.Placeholder("<<budget exhausted>>")), budget_consumed
            s = implementer.get_response(error_message=message, use_cache=use_cache)
            command = commands.parse_command(s)
            if s == "help":
                message = commands.help_message
            elif command is None:
                message = "syntax error: {}".format(s)
            else:
                message = None
                try:
                    retval, implementer, step_budget_consumed = command.execute(implementer, budget - budget_consumed)
                    budget_consumed += step_budget_consumed
                    if retval is not None:
                        return retval, implementer, budget_consumed
                except commands.BadCommand as e:
                    message = "{}: {}".format(e, s)
                except RecursionError:
                    raise
                    implementer = implementer.add_action(command).add_message(Message("stack overflow"))

class Translator(Env):
    def display_message(self, i, m):
        #sender = "A" if i % 2 == 0 else "B"
        sender = self.sources[i]
        return "{} >>> {}".format(sender, m)

    def display_action(self, i, a, debug=False):
        #receiver = "B" if i % 2 == 0 else "A"
        receiver = self.targets[i]
        prefix = "{} <<< ".format(receiver)
        if debug: prefix = utils.pad_to("{}.".format(i), len(prefix))
        return "{}{}\n".format(prefix, a)

    def get_response(self, **kwargs):
        #receiver = "B" if len(self.actions) % 2 == 0 else "A"
        receiver = self.targets[-1]
        prompt = "{} <<< ".format(receiver)
        return get_response(self, prompt=prompt, kind="translate", **kwargs)

    def add_source_target(self, source, target):
        return self.copy(sources = self.sources + (source,), targets = self.targets + (target,))

    def __init__(self, sources=(), targets=(), **kwargs):
        self.sources = sources
        self.targets = targets
        return super().__init__(**kwargs)

    def copy(self, sources=None, targets=None, **kwargs):
        if sources is None: sources=self.sources
        if targets is None: targets=self.targets
        return super().copy(sources=sources, targets=targets, **kwargs)

    def run(self, m, use_cache=True, source="*", target="*"):
        translator = self.add_source_target(source, target).add_message(m)
        message = None
        while True:
            s = translator.get_response(error_message=message, use_cache=use_cache)
            viewer = commands.parse_view(s)
            translation = commands.parse_message(s)
            fixer = commands.parse_fix(s)
            if fixer is not None:
                message = fixer.fix(translator)
            elif viewer is not None:
                try:
                    translator = viewer.view(translator)
                    message = None
                except commands.BadCommand as e:
                    message = "{}: {}".format(e, s)
            elif translation is not None:
                try:
                    result = translation.instantiate(translator.args)
                    return result, translator.add_action(translation)
                except RecursionError:
                    raise
                    message = "stack overflow on {}".format(s)
                except BadInstantiation:
                    message = "syntax error: {}".format(s)
            else:
                message = "syntax error: {}".format(s)

def ask_Q(Q, context, sender, receiver=None, translator=None, nominal_budget=float("inf"), invisible_budget=float("inf")):
    translator = Translator(context=context) if translator is None else translator
    receiver = Implementer(context=context) if receiver is None else receiver
    builtin_result = builtin_handler(Q)
    if builtin_result is not None:
        translator = translator.add_message(Q).add_action(Q)
        translator = translator.add_message(builtin_result).add_action(builtin_result)
        implementer = receiver.add_message(Q).add_action(commands.Placeholder("response from built-in function"))
        return messages.addressed_message(builtin_result, translator=translator, implementer=implementer, budget=nominal_budget), 1
    translated_Q, translator = translator.run(Q, source="A", target="B")
    if sender is not None:
        addressed_Q = messages.addressed_message(translated_Q, implementer=sender, translator=translator, question=True, budget=nominal_budget)
    A, receiver, budget_consumed = receiver.run(addressed_Q, budget=min(nominal_budget, invisible_budget))
    translated_A, translator = translator.run(A, source="B", target="A")
    addressed_A = messages.addressed_message(translated_A, implementer=receiver, translator=translator, budget=nominal_budget)
    return addressed_A, budget_consumed

def builtin_handler(Q):
    if (Q.matches("what cell contains the agent in world []?")
            and isinstance(Q.args[0], messages.WorldMessage)):
        grid, agent, history = Q.args[0].world
        return Message("the agent is in cell []", messages.CellMessage(agent))
    if (Q.matches("what is in cell [] in world []?")
            and isinstance(Q.args[0], messages.CellMessage)
            and isinstance(Q.args[1], messages.WorldMessage)):
        cell = Q.args[0].cell
        world = Q.args[1].world
        return Message("it contains []", Message(worlds.look(world, cell)))
    for direction in worlds.directions:
        if (Q.matches("is cell [] {} of cell []?".format(direction))
                and isinstance(Q.args[0], messages.CellMessage)
                and isinstance(Q.args[1], messages.CellMessage)):
            a = Q.args[0].cell
            b = Q.args[1].cell
            if (a - b).in_direction(direction):
                return Message("yes")
            else:
                return Message("no")
        if (Q.matches("move the agent {} in world []".format(direction))
                and isinstance(Q.args[0], messages.WorldMessage)):
            world = Q.args[0].world
            new_world, moved = worlds.move_person(world, direction)
            if moved:
                return Message("the resulting world is []", messages.WorldMessage(new_world))
            else:
                return Message("it can't move that direction")
        if (Q.matches("what cell is directly {} of cell []?".format(direction))
                and isinstance(Q.args[0], messages.CellMessage)):
            cell = Q.args[0].cell
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

def get_response(env, kind="implement", use_cache=True, replace_old=False, error_message=None, prompt="<<< ", default=None):
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
            t.print_line("")
            t.print_line(error_message)
            t.print_line("")
        response = term.get_input(t, suggestions=hints, shortcuts=shortcuts, prompt=prompt, default=default)
        if use_cache: suggester.set_cached_response(obs, response)
    return response

def main():
    with Context() as context:
        world = worlds.default_world()
        init_message = messages.Message("[] is a world", messages.WorldMessage(world))
        return Implementer(context=context).run(init_message, use_cache=False)

if __name__ == "__main__":
    try:
        message, environment = main()
        import IPython
        from worlds import display_history
        IPython.embed()
    except KeyboardInterrupt:
        pass
