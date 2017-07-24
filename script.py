from main import *

if __name__ == "__main__":
    try:
        message, src, environment, budget_consumed = main()
        import IPython
        from worlds import display_history
        IPython.embed()
    except (KeyboardInterrupt, FixedError):
        pass
