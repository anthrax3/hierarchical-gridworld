from utils import clear_screen
import time

class X(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return X(self.x + other.x, self.y + other.y)

    def __iter__(self):
        yield self.x
        yield self.y

    def __repr__(self):
        return "X({}, {})".format(self.x, self.y)

def update(grid, cell, f):
    return update_tuple(grid, cell.x, lambda t : update_tuple(t, cell.y, f))

def update_tuple(t, i, f):
    return t[:i] + (f(t[i]),) + t[i+1:]

def empty_world(x, y, start=X(0, 0)):
    grid = (((),) * y,) * x
    grid = add(grid, start, "agent")
    return grid, start, start, None

def render(xs):
    if len(xs) == 0:
        return "empty"
    else:
        return " and ".join(xs)

def default_world():
    grid, agent, gaze, previous = empty_world(5, 5)
    grid = add(grid, X(2, 3), "wall")
    grid = add(grid, X(1, 3), "wall")
    grid = add(grid, X(1, 2), "wall")
    grid = add(grid, X(1, 1), "wall")
    grid = add(grid, X(1, 0), "wall")
    return grid, agent, gaze, previous

def main():
    world = default_world()
    message = ""
    while True:
        print_world(world)
        if message: print(message)
        s = input("<<< ")
        diff = direction[s]
        world, moved = move_person(world, diff)
        message = "" if moved else "!"

def render_small(xs):
    if "wall" in xs:
        return "#"
    if "agent" in xs:
        if "goal" in xs:
            return "!"
        else:
            return "@"
    if "goal" in xs:
        return "?"
    return "."

def world_repr(world):
    grid, _, _, _ = world
    return "\n".join("".join(render_small(x) for x in r) for r in grid)

def print_world(world):
    clear_screen()
    print(world_repr(world))

def remove(grid, cell, x, ignore_absent=False):
    def f(xs):
        assert (x in xs) or ignore_absent
        return tuple(y for y in xs if y != x)
    return update(grid, cell, f)

def add(grid, cell, x):
    return update(grid, cell, lambda xs : xs + (x,))

obstructs = {"agent":True, "wall":True, "goal":False}
direction = {"up":X(-1, 0), "down":X(1, 0), "left":X(0, -1), "right":X(0, 1)}

def access(grid, cell):
    return grid[cell.x][cell.y]

def passable(grid, cell):
    return in_bounds(grid, cell) and not any(obstructs[x] for x in access(grid, cell))

def in_bounds(grid, cell):
    i,j = cell
    N,M = len(grid), len(grid[0])
    return i >= 0 and i < N and j >= 0 and j < M

def move_person(world, diff):
    if isinstance(diff, str):
        diff = direction[diff]
    grid, agent_xy, gaze_xy, previous = world
    target_xy = agent_xy + diff
    can_move = passable(grid, target_xy)
    if can_move:
        grid = add(grid, target_xy, "agent")
        grid = remove(grid, agent_xy, "agent")
        return (grid, target_xy, gaze_xy, world), True
    else:
        return world, False

def move_gaze(world, diff):
    if isinstance(diff, str):
        diff = direction[diff]
    grid, agent_xy, gaze_xy, previous = world
    target_xy = gaze_xy + diff
    can_move = in_bounds(grid, target_xy)
    if can_move:
        return (grid, agent_xy, target_xy, previous), True
    else:
        return world, False

def look(world):
    grid, agent_xy, gaze_xy, previous = world
    return render(access(grid, gaze_xy))

def display_history(world, fps=5):
    history = []
    while world is not None:
        history.append(world)
        world = world[3]
    for world in reversed(history):
        print_world(world)
        time.sleep(1 / fps)
