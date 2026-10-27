"""Shared transaction rules and exact monetary arithmetic for the CLI."""
import re

_AMOUNT = re.compile(r'(0|[1-9][0-9]{0,17})(?:\.([0-9]{1,2}))?\Z')


def to_cents(value):
    if not isinstance(value, str):
        raise ValueError('amount must be a decimal string')
    match = _AMOUNT.fullmatch(value)
    if not match:
        raise ValueError('invalid amount')
    cents = int(float(value) * 100)
    if cents <= 0:
        raise ValueError('amount must be positive')
    return cents


def format_cents(value):
    sign = '-' if value < 0 else ''
    absolute = abs(value)
    return f'{sign}{absolute // 100}.{absolute % 100:02d}'


def summarize(rows):
    if not isinstance(rows, list):
        raise ValueError('input must be a list')
    totals = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('kind') not in ('income', 'expense'):
            raise ValueError('unknown transaction kind')
        currency = row.get('currency')
        if not isinstance(currency, str) or not currency:
            raise ValueError('currency must be a nonempty string')
        cents = to_cents(row.get('amount'))
        group = totals.setdefault(currency, {'income': 0, 'expense': 0})
        group[row['kind']] += cents
    return {currency: {'income': format_cents(value['income']),
                       'expense': format_cents(value['expense']),
                       'net': format_cents(value['income'] - value['expense'])}
            for currency, value in sorted(totals.items())}
