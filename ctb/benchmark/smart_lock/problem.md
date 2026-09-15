# 双门智能门锁控制器

实现隐藏。参赛者只能根据本文、`test_aw.py` 和 testcase 模板设计测试。

控制器管理 `FRONT`、`BACK` 两扇相互独立的门。正确 PIN 固定为 `2468`。

## 初始状态

每扇门初始均为：

- `locked = True`
- `door_open = False`
- `failed_attempts = 0`
- `lockout_remaining = 0`
- `unlock_remaining = 0`

## 输入

- `enter_pin(door, pin)`：输入 PIN，返回是否通过。
- `open_door(door)`：尝试开门，返回是否成功。
- `close_door(door)`：关闭门。
- `admin_reset(door)`：清除该门的失败次数与锁定计时。
- `tick(seconds)`：时间前进。
- `snapshot(door)`：读取该门可观察状态。

`door` 只支持 `FRONT/BACK`。PIN 必须是 4 位纯数字字符串。`seconds` 必须为正整数。非法参数必须抛出 `ValueError`，且不得改变任何门状态。

## PIN 与安全锁定

门处于锁定状态时：

- 正确 PIN：立即解锁，`unlock_remaining=10`，失败次数清零。
- 错误 PIN：失败次数 +1。
- 连续第 3 次错误 PIN：失败次数清零，并进入 30 秒安全锁定。

安全锁定期间所有 PIN 都返回失败，不得改变安全锁定计时或其他状态。30 秒结束后可再次正常输入 PIN。

门已解锁时：

- 再次输入正确 PIN 返回成功，但**不得刷新**剩余解锁时间。
- 输入错误 PIN 返回失败，但不得增加失败次数，也不得改变其他状态。

## 门状态与自动上锁

解锁后 10 秒自动上锁。

- 若计时到 0 时门处于关闭状态，立即上锁。
- 若计时到 0 时门仍打开，保持解锁；待门关闭时立即上锁。
- 锁定状态下 `open_door` 返回失败且状态不变。
- 已关闭的门重复执行 `close_door` 为无副作用操作。
- 门在解锁计时未到 0 前打开再关闭，不得提前上锁，也不得刷新解锁计时。

## 管理复位

`admin_reset(door)` 只清除该门的 `failed_attempts` 与 `lockout_remaining`。

它不得改变：`locked`、`door_open`、`unlock_remaining`，也不得影响另一扇门。

## 双门隔离

FRONT/BACK 的失败次数、安全锁定、解锁计时、门状态完全独立。对一扇门的 PIN、开关门、管理复位均不得影响另一扇门。

## 时间语义

`tick(n)` 等价于连续执行 n 次 `tick(1)`。一次 tick 同时推进两扇门的计时。

`snapshot(door)` 返回：`locked`、`door_open`、`failed_attempts`、`lockout_remaining`、`unlock_remaining`。
