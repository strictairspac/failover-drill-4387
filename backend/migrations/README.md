# 数据结构
本小型项目首次启动使用 SQLAlchemy metadata 建立 users/nodes/scenarios/drills/audits 五表。自然键 users.email、nodes.name、scenarios.name 唯一。drills.scenario_id 为外键，快照在入队时固定。上线结构演进须补充版本化迁移，本项目不支持对既有不同结构数据库自动升级。

## 报价簿表（quote_*）
- `quote_columns`：报价物理列换代。逻辑列名恒为 `price`；每次换列新增一代，旧代置 `retired`。`generation` 唯一，任一时刻只有一个 `active`。换列不改逻辑列名。
- `quote_rows`：报价行，`seq` 为稳定键集游标推进键，`symbol` 唯一。
- `quote_prices`：按 `(row_id, column_id, version)` 存放。改价追加新版本而不覆盖；游标据 `version` 读到打开时的价。唯一约束 `uq_price_row_column_version`。
- `quote_cursors`：快照游标。绑定 `column_id/generation/snapshot_version/max_seq/last_seq`；关闭或读完置 `closed`，不再阻挡回收。
- `quote_swaps`：换列日志。`request_id` 唯一，落盘后中断重试同一 `request_id` 返回既有结果（`replayed`），不会重复换列。
- `nodes.has_legacy`：备库是否保留换列前旧价，供游标感知切主判断能否接住未读完的旧游标。

自动升级：本项目首次建表即可；对已存在的旧库，需手工 `ALTER TABLE nodes ADD COLUMN has_legacy`（默认 1）并建上述 quote_* 表，否则启动的 DDL 会因缺列失败而中止（比静默跑坏结构更安全）。
