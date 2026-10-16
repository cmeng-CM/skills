"""Read external settings for every actual invocation."""
import json
from pathlib import Path
import sys


def main():
    try:
        settings = json.loads(Path(__file__).with_name('settings.json').read_text(encoding='utf-8'))
        if not isinstance(settings, dict) or type(settings.get('factor')) is not int:
            raise ValueError('settings must contain an integer factor')
        output = json.dumps({'result': 2 * settings['factor']})
    except (OSError, UnicodeError, ValueError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
