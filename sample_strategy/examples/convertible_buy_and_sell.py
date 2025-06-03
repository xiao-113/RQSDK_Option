# -*- coding: utf-8 -*-
from rqalpha_plus.apis import *
import numpy as np

__config__ = {
    "base": {
        "start_date": "2018-12-01",  # 回测开始日期
        "end_date": "2019-02-15",  # 回测结束日期
        "frequency": "1d",
        "accounts": {
            "stock": 1000000
        },  # 设置初始资金，此处类别需要填写为 stock
        "log_level": "INFO",
        "benchmark": "",  # 策略基准合约
        "data_bundle_path": None,
    },
    "mod": {
        "sys_simulation": {
            "enabled": True,
            "volume_limit": True,  # 是否开启成交量限制
            'volume_percent': 0.3,  # 按照 bar 数据成交量的一定比例进行限制，超限部分无法在当前 bar 一次性撮合成交
        },
        "sys_analyser": {
            "enabled": True,
            "plot": False,  # 是否画出回测结果收益图
        }
    },
}


def print_info(context):
    # 获取投资组合信息
    portfolio = context.portfolio
    print('策略现金为 {}, 债券总市值为 {}, 组合总权益为 {}, 当前持仓为 {}'.format(
        portfolio.cash, portfolio.market_value, portfolio.total_value,
        get_position('113010.XSHG', POSITION_DIRECTION.LONG).quantity))


# 策略初始化运行一次
def init(context):
    print("初始化")
    # context 存储全局变量
    context.count = 0
    context.bond_id = '113010.XSHG'
    context.bar_count = 5


# 每个交易日运行。此处债券交易日假定与场内交易所市场一致
def handle_bar(context, bar_dict):
    context.count += 1
    print_info(context)
    # 确保积累了足够的历史数据
    if context.count > context.bar_count:
        price_array = history_bars(context.bond_id, 5, '1d', 'close')
        # 获取当前 bar 数据
        bar = bar_dict[context.bond_id]
        # 计算5日移动平均价格
        avg_price = np.mean(price_array)
        # 获取当前债券持仓数量
        pos_qty = get_position(context.bond_id, POSITION_DIRECTION.LONG).quantity
        # 计算开仓信号
        if avg_price > bar.open:
            print('债券 {} 的5日均价 {} 大于今日开盘价 {}, 买入占当前总权益 10% 的转债'.format(context.bond_id, avg_price, bar.open))
            order_percent(context.bond_id, 0.1)

        elif pos_qty > 0:
            print('卖出100张转债 {}'.format(context.bond_id))
            submit_order(context.bond_id, amount=100, side=SIDE.SELL)

        # 如果上述发单逻辑成交，则需要更新持仓数量
        pos_qty = get_position(context.bond_id, POSITION_DIRECTION.LONG).quantity

        # 01-14 在回售期之内，可以通过 rqdatac.convertible.get_put_info 查询得到
        if str(context.now.date()) == '2019-01-14':
            print('回售 {} 张债券 {}'.format(pos_qty, context.bond_id))
            # 行驶回售权利
            exercise(context.bond_id, amount=pos_qty)

        if str(context.now.date()) == '2019-02-13':
            print('2019-02-13 为强制赎回的的权益登记日')
