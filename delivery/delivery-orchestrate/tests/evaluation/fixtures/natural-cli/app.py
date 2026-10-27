"""Command-line greeting."""
import argparse


def greeting(name):
    return f"Hello, {name.strip()}!"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()
    print(greeting(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
