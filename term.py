import termbox
import time
import sys
import random

color = termbox.DEFAULT

shortcut_bindings = [
    ('a', termbox.KEY_CTRL_A),
    ('s', termbox.KEY_CTRL_S),
    ('d', termbox.KEY_CTRL_D),
    ('f', termbox.KEY_CTRL_F),
    ('t', termbox.KEY_CTRL_T),
]

def get_input(t, suggestions=[], shortcuts=[], prompt=None):
    shortcut_dict = {}
    for (c, k), template in zip(shortcut_bindings, shortcuts):
        t.print_line("{}: {}".format(c, template))
        shortcut_dict[k] = template
    if shortcuts:
        t.print_line("")
    for i, suggestion in reversed(list(enumerate(suggestions))):
        t.print_line("{}. {}".format(i+1, suggestion))
    if suggestions:
        t.print_line("")
    if prompt is not None: t.print_line(prompt)
    return Input(t, t.x, t.y, suggestions=suggestions, shortcuts=shortcut_dict).elicit()

class Input(object):

    def __init__(self, t, x, y, suggestions=[], shortcuts={}):
        self.x = x
        self.y = y
        self.cursor = 0
        self.s = ""
        self.high_water = 0
        self.t = t
        self.drafts = [""] + suggestions
        self.current_draft = 0
        self.shortcuts = shortcuts

    def move_to_draft(self, new_draft):
        cursor_to_end = len(self.s) - self.cursor
        self.drafts[self.current_draft] = self.s
        self.s = self.drafts[new_draft]
        self.current_draft = new_draft
        self.cursor = max(0, len(self.s) - cursor_to_end)
        self.high_water = max(self.high_water, len(self.s))

    def refresh(self):
        self.t.putchs(self.x, self.y, pad_to(self.high_water, self.s))
        x, y = self.t.advance(self.x, self.y, self.cursor)
        self.t.set_cursor(x, y)
        self.t.refresh()

    def insert_ch(self, ch, n=None):
        if n is None: n = self.cursor
        self.s = self.s[:n] + ch + self.s[n:]
        if n <= self.cursor:
            self.cursor += 1
        self.high_water = max(self.high_water, len(self.s))

    def remove_ch(self, n=None):
        if n is None: n = self.cursor
        self.s = self.s[:n-1] + self.s[n:]
        if n <= self.cursor:
            self.cursor -= 1

    def poll(self):
        ch, key = self.t.poll()
        if key in [termbox.KEY_BACKSPACE, termbox.KEY_BACKSPACE2] and self.cursor > 0:
            self.remove_ch()
        elif key == termbox.KEY_ARROW_LEFT and self.cursor > 0:
            self.cursor -= 1
        elif key == termbox.KEY_ARROW_RIGHT and self.cursor < len(self.s):
            self.cursor += 1
        elif key == termbox.KEY_ARROW_UP:
            if self.cursor > self.t.width:
                self.cursor -= self.t.width
            elif self.current_draft < len(self.drafts) - 1:
                self.move_to_draft(self.current_draft+1)
        elif key == termbox.KEY_ARROW_DOWN:
            if self.cursor < len(self.s) - self.t.width:
                self.cursor += self.t.width
            elif self.current_draft > 0:
                self.move_to_draft(self.current_draft-1)
        elif key == termbox.KEY_ENTER:
            return self.s
        elif key in self.shortcuts:
            for c in self.shortcuts[key]:
                self.insert_ch(c)
        elif ch != None:
            self.insert_ch(ch)
        self.refresh()
        return None

    def elicit(self):
        self.refresh()
        while True:
            result = self.poll()
            if result is not None: return result

def pad_to(k, s):
    return s + " " * (k - len(s))

class Terminal(object):

    def __init__(self):
        pass

    def __enter__(self):
        self.t = termbox.Termbox()
        self.t.__enter__()
        self.x = 0
        self.y = 0
        self.width = min(self.t.width(), 80)
        self.clear()
        return self

    def __exit__(self, *args):
        self.t.__exit__(*args)

    def putch(self, x, y, ch):
        self.t.change_cell(x, y, ord(ch), termbox.DEFAULT, termbox.DEFAULT)

    def print_ch(self, ch):
        self.putch(self.x, self.y, ch)
        self.move()

    def move(self, n=1):
        self.x, self.y = self.advance(self.x, self.y)

    def advance(self, x, y, n=1):
        x += n
        while x >= self.width:
            x -= self.width
            y += 1
        return x, y

    def putchs(self, x, y, chs):
        for ch in chs:
            self.putch(x, y, ch)
            x, y = self.advance(x, y)
        return x, y

    def print_line(self, line, new_line=True):
        if new_line: self.new_line()
        self.x, self.y = self.putchs(self.x, self.y, line)

    def new_line(self):
        self.x = 0
        self.y += 1

    def clear(self):
        self.t.clear()
        self.x = 0
        self.y = 0

    def refresh(self):
        self.t.present()

    def poll(self):
        type, ch, key, mod, w, h, x, y = self.t.poll_event()
        if type == termbox.EVENT_KEY and key == termbox.KEY_CTRL_C:
            raise KeyboardInterrupt()
        if key == 32:
            ch = " "
        return ch, key

    def set_cursor(self, x, y):
        self.t.set_cursor(x, y)