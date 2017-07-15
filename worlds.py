from utils import clear_screen
import time
from random import random, randint

width = height = 7

class X(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return X(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return X(self.x - other.x, self.y - other.y)

    def in_direction(self, direction):
        dx, dy = directions[direction]
        return dx * self.x > 0 or dy * self.y > 0

    def move(self, direction):
        result = self + directions[direction]
        return result, result.is_valid()

    def is_valid(self):
        return self.x >= 0 and self.y >= 0 and self.x < height and self.y < width

    def __iter__(self):
        yield self.x
        yield self.y

    def __repr__(self):
        return "X({}, {})".format(self.x, self.y)

def update(grid, cell, f):
    return update_tuple(grid, cell.x, lambda t : update_tuple(t, cell.y, f))

def update_tuple(t, i, f):
    return t[:i] + (f(t[i]),) + t[i+1:]

def empty_grid():
    return (((),) * width,) * height

def articulate(s):
    if s[0] in "aeiou":
        return "an {}".format(s)
    else:
        return "a {}".format(s)

def render(xs):
    if xs is None:
        return "out of bounds"
    if len(xs) == 0:
        return "empty"
    else:
        return " and ".join(articulate(x) for x in xs)

def default_world():
    grid = empty_grid()
    goalx, goaly = randint(1, height-1), randint(1, width-1)
    agentx, agenty = randint(1, height-1), randint(1, width-1)
    grid = add(grid, X(agentx, agenty), "agent")
    grid = add(grid, X(goalx, goaly), "goal")
    for i in range(height):
        for j in range(width):
            if ((i != goalx or j != goaly) and (i != agentx or j != agenty)
                    and (i > 1 or j > 1)):
                if random() < 0.25:
                    grid = add(grid, X(i, j), "wall")
    return grid, X(agentx, agenty), None

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
    grid, _, _ = world
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
directions = {"north":X(-1, 0), "south":X(1, 0), "west":X(0, -1), "east":X(0, 1)}

def access(grid, cell):
    if cell.is_valid():
        return grid[cell.x][cell.y]
    else:
        return None

def passable(grid, cell):
    return in_bounds(grid, cell) and not any(obstructs[x] for x in access(grid, cell))

def in_bounds(grid, cell):
    i,j = cell
    N,M = len(grid), len(grid[0])
    return i >= 0 and i < N and j >= 0 and j < M

def move_person(world, diff):
    if isinstance(diff, str):
        diff = directions[diff]
    grid, agent_xy, previous = world
    target_xy = agent_xy + diff
    can_move = passable(grid, target_xy)
    if can_move:
        grid = add(grid, target_xy, "agent")
        grid = remove(grid, agent_xy, "agent")
        return (grid, target_xy, world), True
    else:
        return world, False

def look(world, cell):
    grid, agent_xy, previous = world
    return render(access(grid, cell))

def display_history(world, fps=5):
    history = []
    while world is not None:
        history.append(world)
        world = world[3]
    for world in reversed(history):
        print_world(world)
        time.sleep(1 / fps)
