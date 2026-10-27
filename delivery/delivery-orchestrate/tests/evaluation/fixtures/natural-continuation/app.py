"""Command-line greeting."""
import argparse


def greeting(name, uppercase=False):
    text = f"Hello, {name.strip()}!"
    return text.upper() if uppercase else text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()
    print(greeting(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
