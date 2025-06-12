#!/usr/bin/env python
# -*- coding: utf-8 -*-
from rqalpha_plus.apis import *

__config__ = {
    'base': {
        'accounts': {
            'stock': 10000000,
        },
        'start_date': "20170101",
        'end_date': "20200101",
        'frequency': '1d',
    },
    "mod": {
        "optimizer2": {
            "enabled": True,
        },
        'sys_analyser': {
            'enabled': True,
            'benchmark': '000300.XSHG',
        },
    }
}


def rebalance(context, bar_dict):
    cons = [
        WildcardIndustryConstraint(lower_limit=-0.01, upper_limit=0.1, relative=True,
                                   classification=IndustryClassification.ZX, hard=False),
        WildcardStyleConstraint(lower_limit=-0.3, upper_limit=0.3, relative=True, hard=False)
    ]
    pool = [s for s in index_components('000906.XSHG') if not is_suspended(s)]
    s = portfolio_optimize(pool, cons=cons, benchmark='000300.XSHG')
    s = s[s > 0.0001]

    for order_book_id, position in context.stock_account.positions.items():
        if order_book_id not in s:
            order_target_value(order_book_id, 0)

    s = s.sort_values()
    portfolio_value = context.portfolio.total_value

    for order_book_id, weight in s.items():
        order_target_value(order_book_id, portfolio_value * weight)


def init(context):
    scheduler.run_monthly(rebalance, 1)
