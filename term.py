import termbox
import time
import sys
import random

color = termbox.DEFAULT

class LineIn(object):

    def __init__(self, t, x, y):
        self.x = x
        self.y = y
        self.cursor = 0
        self.s = ""
        self.high_water = 0
        self.t = t

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
        if ch != None:
            self.insert_ch(ch)
        elif key in [termbox.KEY_BACKSPACE, termbox.KEY_BACKSPACE2] and self.cursor > 0:
            self.remove_ch()
        elif key == termbox.KEY_ARROW_LEFT and self.cursor > 0:
            self.cursor -= 1
        elif key == termbox.KEY_ARROW_RIGHT and self.cursor < len(self.s):
            self.cursor += 1
        elif key == termbox.KEY_ARROW_UP and self.cursor > self.t.width:
            self.cursor -= self.t.width
        elif key == termbox.KEY_ARROW_DOWN and self.cursor < len(self.s) - self.t.width:
            self.cursor += self.t.width
        elif key == termbox.KEY_ENTER:
            return self.s
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

    def print_line(self, line, new_line=False):
        if new_line: self.new_line()
        self.x, self.y = self.putchs(self.x, self.y, line)

    def new_line(self):
        self.x = 0
        self.y += 1

    def clear(self):
        self.t.clear()

    def refresh(self):
        self.t.present()

    def poll(self):
        type, ch, key, mod, w, h, x, y = self.t.poll_event()
        if type == termbox.EVENT_KEY and key == termbox.KEY_ESC:
            raise KeyboardInterrupt()
        if key == 32:
            ch = " "
        return ch, key

    def set_cursor(self, x, y):
        self.t.set_cursor(x, y)

if __name__ == "__main__":
    with Terminal() as t:
        t.clear()
        t.set_cursor(5, 5)
        t.refresh()
        t.poll()
        #l = LineIn(t, 0, 0)
        #l.refresh()
        #while True:
        #    l.poll()


#spaceord = ord(u" ")
#
#def print_line(t, msg, y, fg, bg):
#	w = t.width()
#	l = len(msg)
#	x = 0
#	for i in range(w):
#		c = spaceord
#		if i < l:
#			c = ord(msg[i])
#		t.change_cell(x+i, y, c, fg, bg)
#
#class SelectBox(object):
#	def __init__(self, tb, choices, active=-1):
#		self.tb = tb
#		self.active = active
#		self.choices = choices
#		self.color_active = (termbox.BLACK, termbox.CYAN)
#		self.color_normal = (termbox.WHITE, termbox.BLACK)
#
#	def draw(self):
#		for i, c in enumerate(self.choices):
#			color = self.color_normal
#			if i == self.active:
#				color = self.color_active
#			print_line(self.tb, c, i, *color)
#
#	def validate_active(self):
#		if self.active < 0:
#			self.active = 0
#		if self.active >= len(self.choices):
#			self.active = len(self.choices)-1
#
#	def set_active(self, i):
#		self.active = i
#		self.validate_active()
#
#	def move_up(self):
#		self.active -= 1
#		self.validate_active()
#
#	def move_down(self):
#		self.active += 1
#		self.validate_active()
#
#choices = [
#	u"This instructs Psyco",
#	u"to compile and run as",
#]
#
#def draw_bottom_line(t, i):
#	i = i % 8
#	w = t.width()
#	h = t.height()
#	c = i
#	palette = [termbox.DEFAULT, termbox.BLACK, termbox.RED, termbox.GREEN,
#	           termbox.YELLOW, termbox.BLUE, termbox.MAGENTA, termbox.CYAN,
#	           termbox.WHITE]
#	for x in range(w):
#		t.change_cell(x, h-1, ord(u' '), termbox.BLACK, palette[c])
#		t.change_cell(x, h-2, ord(u' '), termbox.BLACK, palette[c])
#		c += 1
#		if c > 7:
#			c = 0
#
#with termbox.Termbox() as t:
#	sb = SelectBox(t, choices, 0)
#	t.clear()
#	sb.draw()
#	t.present()
#	i = 0
#	run_app = True
#	while run_app:
#		event_here = t.poll_event()
#		while event_here:
#			(type, ch, key, mod, w, h, x, y) = event_here
#			if type == termbox.EVENT_KEY and key == termbox.KEY_ESC:
#				run_app = False
#			if type == termbox.EVENT_KEY:
#				if key == termbox.KEY_ARROW_DOWN:
#					sb.move_down()
#				elif key == termbox.KEY_ARROW_UP:
#					sb.move_up()
#				elif key == termbox.KEY_HOME:
#					sb.set_active(-1)
#				elif key == termbox.KEY_END:
#					sb.set_active(999)
#			event_here = t.peek_event()
#
#		t.clear()
#		sb.draw()
#		draw_bottom_line(t, i)
#		t.present()
#		i += 1
