import ccxt
import pandas as pd
import numpy as np
import time
import schedule
import requests
from datetime import datetime, timedelta

# ==========================================
# 配置区 (请在此处核对你的密钥和参数)
# ==========================================
SYMBOL = 'BTC/USDT'
TIMEFRAME = '4h'
LIMIT = 200  # 拉取最近 200 根 K 线
SERVER_KEY = 'SCT366057TPOQ6gS2UcZ7ElMXyXzf1Vc8I'  # Server酱 SendKey

# ==========================================
# 工具函数：Server酱微信通知
# ==========================================
def send_wechat_notification(price, stop_loss, target, rr):
    """发送买入信号到微信"""
    title = "【买入信号】BTC二爻突破"
    desp = f"当前价格：{price:.2f}\n止损：{stop_loss:.2f}\n目标：{target:.2f}\n盈亏比：{rr:.2f}"
    url = f"https://sctapi.ftqq.com/{SERVER_KEY}.send?title={title}&desp={desp}"
    try:
        response = requests.get(url, timeout=10)
        print(f"微信通知发送状态: {response.json()}")
    except Exception as e:
        print(f"微信通知发送失败: {e}")

# ==========================================
# 核心函数：拉取并清洗数据
# ==========================================
def fetch_ohlcv():
    """从币安拉取 4 小时 K 线数据"""
    print(f"\n{'='*40}")
    print(f"开始拉取数据... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}  # 永续合约数据
        })
        ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LIMIT)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        print(f"数据拉取成功，共 {len(df)} 根 K 线。最新时间：{df.index[-1]}")
        return df
    except Exception as e:
        print(f"拉取数据失败，请检查网络或币安API状态: {e}")
        return None

# ==========================================
# 核心函数：六爻阶段判定 + 附录A检查
# ==========================================
def analyze_signal(df):
    """判断当前处于哪一爻，并检查是否出现买入信号"""
    if df is None or len(df) < 80:
        print("数据不足，无法分析")
        return

    # --- 计算基础指标 ---
    closes = df['close']
    highs = df['high']
    lows = df['low']
    volumes = df['volume']

    # 前20根、前10根等均量
    ma20_volume = volumes.rolling(20).mean()
    # 60周期最高点
    high_60 = highs.rolling(60).max()

    # 当前 K 线（最新一根已收盘的 K 线）
    cur_close = closes.iloc[-1]
    cur_high = highs.iloc[-1]
    cur_low = lows.iloc[-1]
    cur_vol = volumes.iloc[-1]

    # 前一根 K 线（用来辅助判断形态）
    prev_close = closes.iloc[-2]
    prev_open = df['open'].iloc[-2]
    prev_high = highs.iloc[-2]

    # 前20根最高价（用于突破判断）
    p_20 = highs.iloc[-21:-1].max()

    # 历史最高点 (用于回撤计算)
    all_time_high = highs.max()

    # --- 判断当前属于哪一爻 ---
    stage = "未识别"
    signal_buy = False
    entry_price = 0
    stop_loss = 0
    target_price = 0
    rr = 0

    # 1. 上爻判定：高位吞没阴线 或 双顶
    # 吞没形态定义：前阳后阴，阴线开盘高于前阳收盘，阴线收盘低于前阳开盘
    is_bearish_engulf = (prev_close > prev_open) and (cur_close < cur_open) and \
                        (cur_open > prev_close) and (cur_close < prev_open)
    if is_bearish_engulf:
        print("检测到高位吞没形态 -> 上爻 (亢龙有悔)")
        stage = "上爻"
        return stage, signal_buy, entry_price, stop_loss, target_price, rr

    # 2. 五爻判定：连续3根K线收盘创10根新高，无长上影
    last_3_closes = closes.iloc[-3:]
    max_last_10_highs = highs.iloc[-10:].max()
    is_3_highs = all(c > max_last_10_highs for c in last_3_closes)
    # 无长上影：影线长度 < 实体的2倍
    upper_shadow = cur_high - max(cur_close, cur_open)
    body = abs(cur_close - cur_open)
    no_long_upper = upper_shadow < (body * 2)
    if is_3_highs and no_long_upper:
        print("检测到连续创新高 -> 五爻 (飞龙在天)")
        stage = "五爻"
        return stage, signal_buy, entry_price, stop_loss, target_price, rr

    # 3. 四爻判定：触碰前高 + 长上影/吞没
    near_high = cur_high >= p_20 * 0.99
    is_long_upper = upper_shadow >= (body * 2) and body > 0
    if near_high and (is_long_upper or is_bearish_engulf):
        print("检测到触碰前高并出现反转形态 -> 四爻 (或跃在渊)")
        stage = "四爻"
        return stage, signal_buy, entry_price, stop_loss, target_price, rr

    # 4. 初爻判定：回撤>30%，震荡，量能放大
    drawdown = (all_time_high - cur_close) / all_time_high
    last_20_amp = (closes.iloc[-20:].max() - closes.iloc[-20:].min()) / closes.iloc[-20:].mean()
    vol_surge = cur_vol > (ma20_volume.iloc[-1] * 1.5)
    above_range = cur_close >= closes.iloc[-20:].max()
    if drawdown > 0.3 and last_20_amp <= 0.05 and vol_surge and above_range:
        print("检测到底部震荡放量 -> 初爻 (潜龙勿用)")
        stage = "初爻"
        return stage, signal_buy, entry_price, stop_loss, target_price, rr

    # 5. 二爻判定：附录A 全部条件
    # A1.1 前高 P
    # A1.2 收盘突破 P * 1.002
    break_cond = cur_close > p_20 * 1.002
    # A1.3 放量
    vol_cond = cur_vol >= (ma20_volume.iloc[-1] * 2)
    # A1.4 无长上影假突破（收盘在顶部）
    close_near_high = cur_close >= (cur_high * 0.97)
    # A1.5 历史阻力区检验（P 在过去 60 根 K 线最高价中最多出现 1 次）
    p_hit_count = sum(highs.iloc[-60:].values >= p_20 * 0.999)
    if break_cond and vol_cond and close_near_high and p_hit_count <= 2:
        print("检测到放量突破并满足附录A -> 二爻 (见龙在田) 买入信号！")
        stage = "二爻"
        signal_buy = True

        # 入场价 = 当前收盘价
        entry_price = cur_close
        # 止损价 = 前20根最低点下方 0.5%
        stop_loss = lows.iloc[-20:].min() * 0.995
        # 止盈价 = 盈亏比 3:1
        target_price = entry_price + (entry_price - stop_loss) * 3
        rr = 3.0
        return stage, signal_buy, entry_price, stop_loss, target_price, rr

    # 6. 三爻判定：二爻突破后 10 根 K 线内振幅<10%，成交量萎缩
    # 简化：最近 10 根 K 线振幅小且量低
    recent_10_amp = (highs.iloc[-10:].max() - lows.iloc[-10:].min()) / closes.iloc[-10:].mean()
    vol_shrink = cur_vol < ma20_volume.iloc[-1]
    if recent_10_amp < 0.1 and vol_shrink:
        print("检测到窄幅震荡缩量 -> 三爻 (终日乾乾)")
        stage = "三爻"
        return stage, signal_buy, entry_price, stop_loss, target_price, rr

    # 如果以上都不符合，默认返回初爻或未识别
    print(f"当前未触发明确信号。收盘价：{cur_close:.2f}，前高：{p_20:.2f}")
    return stage, signal_buy, entry_price, stop_loss, target_price, rr

# ==========================================
# 主循环：每4小时执行一次
# ==========================================
def job():
    df = fetch_ohlcv()
    if df is None:
        return
    stage, signal_buy, price, stop_loss, target, rr = analyze_signal(df)
    print(f"当前六爻阶段判定：{stage}")
    if signal_buy:
        print(f"触发买入信号！价格：{price:.2f}，止损：{stop_loss:.2f}，目标：{target:.2f}")
        send_wechat_notification(price, stop_loss, target, rr)
    else:
        print("无买入信号，继续等待。")
    print(f"{'='*40}\n")

# ==========================================
# 启动脚本
# ==========================================
if __name__ == "__main__":
    print("《交易之道》实时信号监控已启动...")
    # 启动后立即运行一次
    job()
    # 设定每4小时运行一次 (在整点时刻附近)
    schedule.every(4).hours.at("00:00").do(job)
    schedule.every(4).hours.at("00:01").do(job)  # 错峰重试，防止网络波动

    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次是否有任务需要执行
