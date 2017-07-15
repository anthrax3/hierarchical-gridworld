from worlds import default_world, display_history
import worlds
from contextlib import closing
import term
import messages
import envs
import sqlite3
import suggestions
import IPython

def main(env=None):
    if env is None:
        env = envs.Env((messages.Message("[] is a world", messages.WorldMessage(default_world())),))
    with Context() as context:
        env.context = context
        return envs.run(env, use_cache=False)

class Context(object):

    def __init__(self):
        self.terminal = term.Terminal()

    def __enter__(self):
        self.db = sqlite3.connect("memoize.db")
        self.cursor = self.db.cursor()
        self.terminal.__enter__()
        self.cache = load_cache(self)
        return self

    def __exit__(self, *args):
        self.db.close()
        self.terminal.__exit__(*args)

def get_action(env, use_cache=True, replace_old=False):
    lines = env.get_lines()
    obs = "\n".join(lines)
    context = env.context
    act = get_cached_action(obs, context) if (use_cache and not replace_old) else None
    if act is None:
        t = context.terminal
        t.clear()
        for line in lines:
            t.print_line(line)
        if use_cache:
            hints, shortcuts = suggestions.make_suggestions_and_shortcuts(env, obs, context.cache)
        else:
            hints, shortcuts = [], []
        act = term.get_input(t, suggestions=hints, shortcuts=shortcuts, prompt="<<< ")
        if use_cache: set_cached_action(obs, act, context)
    return act

def delete_cached_action(obs, context):
    context.cursor.execute("DELETE FROM responses WHERE input = ?", (obs,))
    context.db.commit()

def get_cached_action(obs, context):
    if obs in context.cache:
        return context.cache[obs]
    else:
        return None

def load_cache(context):
    context.cursor.execute("SELECT * FROM responses")
    return {obs:act for obs, act in context.cursor}

def set_cached_action(obs, action, context):
    context.cache[obs] = action
    context.cursor.execute("INSERT INTO responses VALUES (?, ?)", (obs, action))
    context.db.commit()

def init_database():
    with closing(sqlite3.connect("memoize.db")) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE responses (input varchar, output varchar)")
        conn.commit()

def get_database_size():
    with closing(sqlite3.connect("memoize.db")) as conn:
        c = conn.cursor()
        result = 0
        for _ in c.execute("SELECT * FROM responses"):
            result += 1
        return result

if __name__ == "__main__":
    message, environment = main()
    IPython.embed()
