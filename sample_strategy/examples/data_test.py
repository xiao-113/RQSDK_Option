import rqalpha_plus
import rqalpha_mod_option
from datetime import date, time, timedelta
from dateutil.relativedelta import relativedelta
import rqdatac as rq
import numpy as np
rq.init()

close_df = rq.get_price('000300.XSHG', 20250501, 20250523, fields='close')
close_prices = close_df['close'].iloc[-30:]
log_returns = np.log(close_prices / close_prices.shift(1)).dropna()
hv = log_returns.std() * np.sqrt(252)
print(hv)

iv_df = rq.options.get_greeks(
    ['IO2503C3950', 'IO2503P3850'],  '2025-03-02', '2025-03-02', 
    fields='iv', model='implied_forward'
)
current_iv = iv_df['iv'].mean()
print(current_iv)