# Greeting command

A small Python command without third-party dependencies.

Run `python3 app.py Alice` to print `Hello, Alice!`. Names are trimmed. Empty names must return a nonzero exit code and no greeting.

Run tests with `python3 -B -m unittest discover -s tests -v`.

Usage note: This greeting command writes its result to standard output.

New requested option: `--uppercase` prints the complete greeting in upper case; omitting it retains normal output.
