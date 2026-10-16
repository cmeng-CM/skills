import json
import sys
from money import summarize


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('usage: python3 app.py transactions.json')
        with open(sys.argv[1]) as stream:
            rows = json.load(stream)
        result = summarize(rows)
    except (OSError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
