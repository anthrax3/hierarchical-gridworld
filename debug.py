from messages import Message
import utils
import elicit
import envs

def debug(Q, A, db):
    debug_q = Message("is [] a correct response to []?", A, Q)
    debug_a, debug_env = envs.ask_Q(debug_q, db)
    if message_to_bool(debug_a, db):
        return False
    else:
        return debug_env(debug_q.args[0].env)

def message_to_bool(m, db):
    if m.text == ("yes",):
        return True
    elif m.text == ("no",):
        return False
    else:
        new_m, _ = envs.ask_Q(Message("does [] represent yes? please answer with 'yes' or 'no'", m), db)
        return message_to_bool(new_m, db)

def debug_env(env):
    bug_found = False
    for i in range(len(env.actions)):
        if isinstance(env.actions[i], envs.Ask):
            Q = env.actions[i].message.instantiate(env.args)
            A = env.messages[i+1]
            bug_found = bug_found or debug(Q, A, env.db)
    if bug_found:
        return True
    else:
        obs = pick_command("which of these commands is inappropriate?", env)
        if obs is None:
            return False
        if obs is not None:
            elicit.delete_cached_action(obs, env.db)
            elicit.get_action(obs, env.db)
            return True

def pick_command(prompt, env):
    def display_action(a):
        result = "{}. {}".format(display_action.k, a)
        display_action.k += 1
        return result
    display_action.k = 0
    done = False
    utils.clear_screen()
    print(env.get_obs(action_callback=display_action))
    while not done:
        n = input("\n{} ".format(prompt))
        if n == "none":
            return None
        else:
            try:
                n = int(n)
                if n >= 0 and n < display_action.k:
                    done = True
                else:
                    print("please enter an integer between 0 and {}".format(display_actions.k - 1))
            except ValueError:
                print("please type 'none' or an integer")
    new_env = envs.Env(messages=env.messages[:n+1], actions=env.actions[:n], db=env.db)
    return new_env.get_obs()
