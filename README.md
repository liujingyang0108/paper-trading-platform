# 模拟交易平台

一个无外部运行依赖、API 优先、可审计的模拟交易服务。平台只负责行情、订单、撮合、账户和硬风控，不包含策略，也不会连接真实资金。

## 功能

- SQLite 持久化行情、订单和不可变事件流水
- 市价单、限价单、撤单、部分成交和幂等订单
- 买一/卖一成交、滑点、佣金与卖出税费
- 单笔金额、单标的权重、总敞口和陈旧行情检查
- A 股 T+1 可卖数量、100 股买入单位、连续竞价时段和科创板禁买
- 账户、持仓、盈亏、订单、行情历史 HTTP API
- 可重复的合成实时行情，用于本地联调
- 腾讯公开行情适配器，可用真实价格驱动虚拟资金模拟交易

## 启动

```bash
cp config.example.json config.json
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
paper-platform --config config.json --synthetic
```

使用真实公开行情驱动模拟盘（不连接真实账户）：

```bash
paper-platform --config config.json --feed tencent --symbols 510300.SH,510500.SH,159915.SZ --interval 3
```

该适配器的数据标记为 `source=public_web`，可用于模拟交易观察，但因其不是已确认授权的数据服务，学习管线禁止它自动晋级策略。正式研究应替换为券商或授权数据商适配器。

服务默认位于 `http://127.0.0.1:8800`。

```bash
curl http://127.0.0.1:8800/health
curl http://127.0.0.1:8800/v1/account
curl http://127.0.0.1:8800/v1/quotes
```

提交订单：

```bash
curl -X POST http://127.0.0.1:8800/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"510300.SH","side":"buy","quantity":100,"client_order_id":"demo-001","strategy_id":"momentum-v1"}'
```

## API 边界

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/v1/market/ticks` | 行情适配器写入报价 |
| GET | `/v1/quotes` | 最新报价 |
| GET | `/v1/history/{symbol}` | 报价历史 |
| POST | `/v1/orders` | 创建订单，`client_order_id` 幂等 |
| GET | `/v1/orders` | 全部订单 |
| POST | `/v1/orders/{id}/cancel` | 撤单 |
| GET | `/v1/account` | 账户和盯市持仓 |
| GET | `/v1/events` | 增量审计事件 |

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

默认初始资金为 10 万元，禁止 `688`/`689` 科创板代码。生产化前，应将合成行情替换成获授权的行情适配器，并接入正式中国交易日历、公司行为和更真实的涨跌停排队撮合规则。
