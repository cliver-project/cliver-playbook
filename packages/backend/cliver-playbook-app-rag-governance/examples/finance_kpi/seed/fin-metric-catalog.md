# 财务指标目录

版本 v1，适用于 2026 年财务分析。金额单位为人民币元，展示时按项目配置换算为万元。

## 指标定义

| 中文指标 | 字段 | 定义 |
|---|---|---|
| 营业收入 | revenue | 已审主营业务收入与其他业务收入之和 |
| 预算收入 | budget_revenue | 年度预算分解到本期的收入目标 |
| 营业成本 | cost_of_revenue | 与营业收入对应的已审营业成本 |
| 毛利 | gross_profit | 营业收入减营业成本 |
| 毛利率 | gross_margin | 毛利除以营业收入 |
| 净利润 | net_profit | 已审利润表的净利润 |
| 应收账款 | receivables | 期末应收账款余额，含未到期与逾期 |
| 应付账款 | payables | 期末应付账款余额 |
| 流动资产 | current_assets | 资产负债表流动资产合计 |
| 流动负债 | current_liabilities | 资产负债表流动负债合计 |
| 流动资金 | working_capital | 流动资产减流动负债 |
| 资产总额 | total_assets | 资产负债表资产总计 |
| 负债总额 | total_liabilities | 资产负债表负债合计 |
| 资产负债率 | debt_ratio | 负债总额除以资产总额 |

预算达成率 budget_attainment 等于营业收入除以预算收入。所有比率在服务端计算并保留四位小数，模型不得自行推算。

## 资产负债率

资产负债率 debt_ratio 是负债总额 total_liabilities 占资产总额 total_assets 的比例，用于衡量整体杠杆水平。经营分析一屏必须同时给出资产负债率与流动资金，不能只看利润。指标口径发生变化时，必须更新本目录并重新跑黄金数据集。
