from messages import Message
import utils
import elicit
import envs

def sanity_check(Q, A, db):
    debug_q = Message("does [] pass a basic sanity check as a response to []?", A, Q)
    debug_a, _ = envs.ask_Q(debug_q, db)
    return message_to_bool(debug_a, db)

def message_to_bool(m, db):
    if m.text == ("yes",):
        return True
    elif m.text == ("no",):
        return False
    else:
        new_m, _ = envs.ask_Q(Message("does [] represent yes? please answer with 'yes' or 'no'", m), db)
        return message_to_bool(new_m, db)

def fix_env(env):
    obs = pick_command("which of these commands do you want to change?", env)
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
