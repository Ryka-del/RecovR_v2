"""
TutorialHints -- sequential, state-driven on-screen coaching shown ONLY
during Tutorial mode gameplay (self.tutorial), picking up right where the
pre-game How-To-Play card + Controls panel (see games/hud.py) leave off.

Each step is a short message tied to something that actually just happened
in THIS game's own state (first squeeze detected, first successful rep,
...), not a fixed timer, so the coaching always matches what the patient is
actually doing. The one exception is a purely informational step with
nothing further to wait on (e.g. "the ball shoots on every successful
release") -- that one advances after a few seconds on screen instead. The
LAST step in a sequence is always sticky (no `done`, never advances) -- the
ongoing "how to win" reminder (Target vs Timed wording) for the rest of the
run.

Usage (only when self.tutorial; `done`/`anchor`/`text` may be plain values
or callables taking the game instance -- callables let a step reference
live state, e.g. self.goal, that isn't known until on_enter runs):

    from games.tutorial_hints import TutorialHints, TutorialStep

    # on_enter(), after self._session_init(...):
    self._tutorial_hints = TutorialHints([
        TutorialStep("Squeeze your hand to raise the grip bar!",
                     anchor=lambda g: (BAR_X + BAR_W // 2, BAR_Y),
                     done=lambda g, t: g._squeezing),
        TutorialStep("Keep squeezing until the bar reaches the green zone, "
                      "then release!",
                     anchor=lambda g: (BAR_X + BAR_W // 2, BAR_Y + BAR_H // 2),
                     done=lambda g, t: g.score >= 1),
        TutorialStep("Nice! The ball shoots automatically every time you "
                      "release inside the green zone.",
                     done=lambda g, t: t >= 3.0),
        TutorialStep(lambda g: (f"Keep shooting to reach {g.goal} shots!"
                                 if g.session_mode == "target" else
                                 "Keep shooting as many as you can before "
                                 "time runs out!")),
    ]) if self.tutorial else None

    # update(), reached only once real gameplay is running:
    if self._tutorial_hints:
        self._tutorial_hints.update(self, dt)

    # draw(), as late as possible so nothing gameplay draws over it
    # (but before any pause/results overlay, which should cover it):
    if self._tutorial_hints:
        self._tutorial_hints.draw(surface, self)
"""

import pygame
from constants import GAME_W, GAME_H
from games.game_header import HEADER_BOTTOM

_HINT_ACCENT = (255, 196, 64)
_hint_font = None


def _font():
    global _hint_font
    if _hint_font is None:
        _hint_font = pygame.font.SysFont("arial", int(52 * GAME_H / 1080), bold=True)
    return _hint_font


def _resolve(value, game):
    return value(game) if callable(value) else value


def _wrap(text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or font.size(trial)[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class TutorialStep:
    def __init__(self, text, anchor=None, done=None, min_show=3.0):
        """text: str, or callable(game) -> str for state-dependent wording
            (e.g. Target vs Timed Mode, or a specific goal count).
        anchor: callable(game) -> (x, y) screen point this hint points at,
            or None to center it near the top with no pointer.
        done: callable(game, elapsed_on_this_step) -> bool. None marks the
            sticky final step that never advances on its own.
        min_show: this step won't advance before at least this many
            seconds have been on screen even if `done` is already True --
            guards against a step completing before the patient can even
            read it (e.g. a flag that happened to already be true, or the
            triggering action firing almost immediately). Default of 3.0
            applies everywhere no call site overrides it (none currently
            do), so every tutorial instruction in every game gets the same
            minimum read time."""
        self.text     = text
        self.anchor   = anchor
        self.done     = done
        self.min_show = min_show


class TutorialHints:
    def __init__(self, steps):
        self.steps   = steps
        self.index   = 0
        self.elapsed = 0.0

    def update(self, game, dt):
        if not self.steps:
            return
        self.elapsed += dt
        if self.index >= len(self.steps) - 1:
            return   # sticky final step -- nothing left to advance to
        step = self.steps[self.index]
        if (step.done is not None and self.elapsed >= step.min_show
                and step.done(game, self.elapsed)):
            self.index  += 1
            self.elapsed = 0.0

    def draw(self, surface, game):
        if not self.steps:
            return
        step = self.steps[self.index]
        text   = _resolve(step.text, game)
        anchor = _resolve(step.anchor, game) if step.anchor else None
        draw_tutorial_hint(surface, text, anchor)


def draw_tutorial_hint(surface, text, anchor=None):
    font  = _font()
    pad   = int(26 * GAME_H / 1080)
    max_w = int(GAME_W * 0.40)
    lines = _wrap(text, font, max_w)
    line_surfs = [font.render(l, True, (255, 255, 255)) for l in lines]

    w = max(s.get_width() for s in line_surfs) + pad * 2
    h = sum(s.get_height() for s in line_surfs) + pad * 2 + max(0, len(lines) - 1) * 10

    if anchor is None:
        # Below the header bar (and its TUTORIAL badge), never over it.
        bx, by = GAME_W // 2 - w // 2, HEADER_BOTTOM + int(16 * GAME_H / 1080)
    else:
        ax, ay = anchor
        # Keep the bubble on whichever side of the anchor stays fully
        # on-screen, biasing away from the anchor's own side of the screen.
        gap = int(60 * GAME_W / 1920)
        bx = ax - w - gap if ax > GAME_W * 0.55 else ax + gap
        bx = max(16, min(GAME_W - w - 16, bx))
        top_clamp = HEADER_BOTTOM + int(16 * GAME_H / 1080)
        by = max(top_clamp, min(GAME_H - h - 16, ay - h // 2))

    bubble = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(bubble, (18, 24, 40, 238), (0, 0, w, h), border_radius=16)
    pygame.draw.rect(bubble, _HINT_ACCENT, (0, 0, w, h), 3, border_radius=16)
    y = pad
    for s in line_surfs:
        bubble.blit(s, (pad, y))
        y += s.get_height() + 10
    surface.blit(bubble, (bx, by))

    if anchor is not None:
        ax, ay = anchor
        start = (bx, by + h // 2) if bx > ax else (bx + w, by + h // 2)
        pygame.draw.line(surface, _HINT_ACCENT, start, (ax, ay), 4)
        pygame.draw.circle(surface, _HINT_ACCENT, (ax, ay), 9)
        pygame.draw.circle(surface, (18, 24, 40), (ax, ay), 4)
