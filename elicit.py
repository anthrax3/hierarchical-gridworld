from world import default_world, display_history
from contextlib import closing
from utils import clear_screen
import term
import messages
import envs
import sqlite3

def main(env=None):
    if env is None:
        env = envs.Env((messages.Message("[] is a world", messages.World(default_world())),))
    with Context() as context:
        env.context = context
        envs.run(env, use_cache=False)

class Context(object):

    def __init__(self):
        self.terminal = term.Terminal()

    def __enter__(self):
        self.db = sqlite3.connect("memoize.db")
        self.cursor = self.db.cursor()
        self.terminal.__enter__()
        return self

    def __exit__(self, *args):
        self.db.close()
        self.terminal.__exit__(*args)

def get_action(obs, context, use_cache=True):
    act = get_cached_action(obs, context) if use_cache else None
    if act is None:
        #clear_screen()
        #print(obs)
        #act = input("<<< ")
        t = context.terminal
        t.clear()
        for line in obs.split("\n"):
            t.print_line(line, new_line=True)
        t.print_line("<<< ", new_line=True)
        act = term.LineIn(t, t.x, t.y).elicit()
        if use_cache: set_cached_action(obs, act, db)
    return act

def delete_cached_action(obs, context):
    context.cursor.execute("DELETE FROM responses WHERE input = ?", (obs,))
    context.db.commit()

def get_cached_action(obs, context):
    context.cursor.execute("SELECT * FROM responses where input = ?", (obs,))
    result = context.cursor.fetchone()
    return None if result is None else result[1]

def set_cached_action(obs, action, context):
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
