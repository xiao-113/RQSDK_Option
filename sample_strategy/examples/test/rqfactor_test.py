from rqalpha_plus.apis import *

__config__ = {
    "base": {
        "accounts": {
            "stock": 1000000,
        },
        "start_date": "20190601",
        "end_date": "20190610"
    },
    "mod": {
        "rqfactor": {
            "enabled": True
        }
    }
}


def GRAHAM_SIGNAL():
    Graham_number = (22.5 * Factor('earnings_per_share') * Factor('book_value_per_share')) ** (0.5)
    # print("Graham_number:",Graham_number)

    return Graham_number


def init(context):
    context.s1 = '600000.XSHG'
    # 在初始化阶段注册指标函数
    reg_indicator('graham', GRAHAM_SIGNAL, '1d', win_size=10)


def handle_bar(context, bar_dict):
    # 获取指标结果
    gra = get_indicator(context.s1, 'graham')
    print("gra:", gra)

    # 设置入场条件
    if gra > 0:
        order_percent(context.s1, 0.1)
