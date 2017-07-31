from main import *
import worlds

def main():
    with Context() as context:
        world = worlds.default_world()
        init_message = messages.Message("[] is a grid", messages.WorldMessage(world))
        return run_machine(RegisterMachine(context=context, use_cache=False).add_register(init_message))

if __name__ == "__main__":
    try:
        message, src, budget_consumed = main()
        import IPython
        from worlds import display_history
        IPython.embed()
    except (KeyboardInterrupt, ChangedContinuationError):
        pass
