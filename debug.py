from messages import Message
import utils
import elicit
import envs
import term

def sanity_check(Q, A, context):
    debug_q = Message("does [] pass a basic sanity check as a response to []?", A, Q)
    debug_a, _ = envs.ask_Q(debug_q, context)
    return message_to_bool(debug_a, context)

def message_to_bool(m, context):
    if m.text == ("yes",):
        return True
    elif m.text == ("no",):
        return False
    else:
        new_m, _ = envs.ask_Q(Message("does [] represent yes? please answer with 'yes' or 'no'", m), context)
        return message_to_bool(new_m, context)

def fix_env(env):
    env = pick_command("which of these commands do you want to change? ", env)
    if env is None:
        return False
    if env is not None:
        elicit.get_action(env, replace_old=True)
        return True

def pick_command(prompt, env):
    def display_action(a, env):
        result = "{}. {}".format(display_action.k, a)
        display_action.k += 1
        return result
    display_action.k = 0
    t = env.context.terminal
    t.clear()
    lines = env.get_lines(action_callback=display_action)
    for line in lines:
        t.print_line(line)
    done = False
    while not done:
        n = term.get_input(t, prompt=prompt)
        if n == "none":
            return None
        else:
            try:
                n = int(n)
                if n >= 0 and n < display_action.k:
                    done = True
                else:
                    t.print_line("please enter an integer between 0 and {}".format(display_actions.k - 1))
            except ValueError:
                t.print_line("please type 'none' or an integer")
    new_env = envs.Env(messages=env.messages[:n+1], actions=env.actions[:n], context=env.context, args=env.args)
    return new_env
