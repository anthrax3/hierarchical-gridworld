from world import empty_world
from contextlib import closing
from utils import clear_screen
import messages
import envs
import sqlite3

def main(env=None):
    if env is None:
        env = envs.Env((messages.Message("[] is an empty world", messages.World(empty_world(5, 5))),))
    with closing(sqlite3.connect("memoize.db")) as conn:
        env.db = conn.cursor()
        return envs.run(env, use_cache=False)

def get_action(obs, db, use_cache=True):
    act = get_cached_action(obs, db) if use_cache else None
    if act is None:
        clear_screen()
        print(obs)
        act = input("<<< ")
        if use_cache: set_cached_action(obs, act, db)
    return act

def get_cached_action(obs, db):
    db.execute("SELECT * FROM responses where input = ?", (obs,))
    result = db.fetchone()
    return None if result is None else result[1]

def set_cached_action(obs, action, db):
    db.execute("INSERT INTO responses VALUES (?, ?)", (obs, action))
    db.connection.commit()

def init_database():
    with closing(sqlite3.connect("memoize.db")) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE responses (input varchar, output varchar)")
        conn.commit()

if __name__ == "__main__":
    main()
