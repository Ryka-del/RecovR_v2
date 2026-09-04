"""
Per-game adapters that connect the existing `games/*.py` implementations to the
recovr patient architecture.

An adapter is GLUE ONLY -- it subclasses the real game and translates between
the game's internals and the GameRunner host contract. No game mechanics,
graphics, scoring, difficulty, timing, or sensor logic is reimplemented here.
"""
