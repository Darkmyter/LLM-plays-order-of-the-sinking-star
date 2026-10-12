"""Command-line play, same view the model gets.

    uv run python play.py look
    uv run python play.py east [n]      # north/south/west/east, undo, restart,
                                        # activate, take_or_drop, switch_character, select_1..9
    uv run python play.py act "north 3, east 2, activate"
"""
import sys

from game.session import Session


def main():
    s = Session()
    s.last_level = None
    if len(sys.argv) < 2 or sys.argv[1] == "look":
        print(s.look())
        return
    s.look()  # establish level + labels without printing
    if sys.argv[1] == "act":
        print(s.do_sequence(" ".join(sys.argv[2:])))
        return
    action, times = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1
    print(s.do(action, times))


if __name__ == "__main__":
    main()
