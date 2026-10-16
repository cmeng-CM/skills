"""Actual user entry point, to be extended by the requested delivery."""
import json
import sys


def main():
    if len(sys.argv) != 2:
        print('usage: python3 app.py transactions.json', file=sys.stderr)
        return 2
    with open(sys.argv[1]) as stream:
        transactions = json.load(stream)
    print(json.dumps({'transaction_count': len(transactions)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
