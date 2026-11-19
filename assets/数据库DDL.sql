-- =============================================================================
-- DeepQuantor 量化选股系统 · 数据库 DDL（PostgreSQL 14+）
-- 对齐：需求文档 PRD v1.16 / 系统设计总文档 v3.5 §6
-- v1.15 变更：① 新增 task.job_def / task.job_instance（调度任务定义与执行历史）；
--             ② 新增 market.meso_monthly（中观月频低频数据）；
--             ③ market.macro_indicator 主键加入 freq（D 日频 / M 月频 / Q 季频），支撑宏观分频采集（SC-08）。
-- v1.16 变更：① 随客户端整体下线，物理删除 platform."user"（外部注册用户），表数 48 → 47；
--             ② 修复全量建表语句「列定义与约束之间缺逗号」语法缺陷（77 处），已通过 libpg_query 校验。
-- v1.17 变更：调度改由 WorkBuddy 自动化任务承担——task.job_def.xxl_job_id → automation_id，
--             task.job_instance.xxl_log_id → automation_run_id（新增），cron 口径改为 5 段标准格式。
-- v1.18 变更：补齐《系统设计总文档》§6.2/§6.3 已声明但缺建的 6 张表，表数 47 → 53：
--             ① signal.macro_aux_signal（日频辅助信号，本期零产出 · D-30）；
--             ② signal.macro_forecast（预测信号，本期实现 · D-19）；
--             ③ signal.meso_nowcast（中观辅助四项快照，方向快照不参与 total_score）；
--             ④ task.data_item（数据项主表，AD-02）；
--             ⑤ task.data_ref（数据项引用关系，键口径见策略 §4.5 ⑥）；
--             ⑥ task.run_log（运行日志，本期无页面消费）。
-- 约定：
--   1. 按 schema 分域，表名「裸名」，跨域引用写 <schema>.<table>；
--   2. 时序大表按年 PARTITION BY RANGE（trade_date / created_at）；
--   3. 代码类（symbol / code）用 VARCHAR(20)；金额 / 价格 NUMERIC(18,4)；
--      比率 / 评分 / 权重 NUMERIC(12,6)；置信度 NUMERIC(5,4)；JSON 用 JSONB；
--   4. 自增代理主键用 BIGINT GENERATED ALWAYS AS IDENTITY；
--   5. 跑批写入用批量 upsert；禁止长事务跨越跑批窗口；
--   6. 每个字段均带行内注释，末尾 COMMENT ON COLUMN 段写入数据字典（\d+ 可见）。
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. 分域 schema
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS market;       -- 行情库（各采数 Agent 写，按频率拆分独立任务）
CREATE SCHEMA IF NOT EXISTS factor;       -- 因子库（lab-factor / agent-micro 写）
CREATE SCHEMA IF NOT EXISTS signal;       -- 信号库（assemble-risk / 各层引擎写）
CREATE SCHEMA IF NOT EXISTS portfolio;    -- 组合库（portfolio 写）
CREATE SCHEMA IF NOT EXISTS metric;       -- 计量库（tracking / backtest / lab-factor 写）
CREATE SCHEMA IF NOT EXISTS task;         -- 任务与调度（全部 CLI 写；AD-11 写 job_def / rerun_request）
CREATE SCHEMA IF NOT EXISTS common;       -- 主数据（初始化 / AD-02 维护）
CREATE SCHEMA IF NOT EXISTS platform;     -- 平台（Web 站点写：用户与配置）


-- ===========================================================================
-- common 主数据
-- ===========================================================================
CREATE TABLE common.industry (
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码（申万口径，如 SW801010），全系统行业主键
    industry_name   VARCHAR(64)      NOT NULL,  -- 行业名称
    level           SMALLINT         NOT NULL,  -- 行业层级：1 一级 / 2 二级 / 3 三级（申万口径 31/134/346）
    parent_code     VARCHAR(20),  -- 父行业代码（自引用，顶级为 NULL）
    standard        VARCHAR(20)      NOT NULL DEFAULT 'SW',  -- 行业分类标准，默认 SW（申万）；系统唯一基准（C-8，禁止东财口径 JOIN）
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录更新时间
    PRIMARY KEY (industry_code),
    FOREIGN KEY (parent_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE common.industry_etf_map (
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码，主键之一
    etf_code        VARCHAR(20)      NOT NULL,  -- 跟踪该行业的 ETF 代码，主键之一
    is_primary      BOOLEAN          NOT NULL DEFAULT true,  -- 是否该行业的主映射 ETF
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录更新时间
    PRIMARY KEY (industry_code, etf_code),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE common.industry_constituent (
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码，主键之一
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码，主键之一
    in_date         DATE             NOT NULL,  -- 纳入行业的时点（point-in-time，用于历史回测）
    out_date        DATE,  -- 剔出行业的时点；NULL 表示当前仍在列
    is_current      BOOLEAN          NOT NULL DEFAULT true,  -- 是否当前成分股（冗余字段，加速查询）
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录更新时间
    PRIMARY KEY (industry_code, symbol, in_date),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE common.trade_calendar (
    trade_date      DATE             NOT NULL,  -- 交易日，主键
    is_open         BOOLEAN          NOT NULL,  -- 当日是否开市
    is_month_start  BOOLEAN          NOT NULL DEFAULT false,  -- 是否月初（用于月频信号触发）
    is_month_end    BOOLEAN          NOT NULL DEFAULT false,  -- 是否月末
    PRIMARY KEY (trade_date)
);

-- ===========================================================================
-- market 行情库（时序表按年分区）
-- ===========================================================================
CREATE TABLE market.security (
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码，主键
    name            VARCHAR(64)      NOT NULL,  -- 股票名称
    industry_code   VARCHAR(20)      NOT NULL,  -- 所属申万行业代码
    list_date       DATE,  -- 上市日期
    delist_date     DATE,  -- 退市日期；NULL 表示未退市
    is_st           BOOLEAN          NOT NULL DEFAULT false,  -- 是否 ST / *ST / 退市风险警示
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录更新时间
    PRIMARY KEY (symbol),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE market.daily_bar (
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    open            NUMERIC(18,4),  -- 开盘价
    high            NUMERIC(18,4),  -- 最高价
    low             NUMERIC(18,4),  -- 最低价
    close           NUMERIC(18,4),  -- 收盘价（后复权基准）
    volume          NUMERIC(24,2),  -- 成交量（股）
    amount          NUMERIC(28,4),  -- 成交额（元）
    adj_factor      NUMERIC(12,6),  -- 复权因子（后复权）
    source          VARCHAR(16)      NOT NULL DEFAULT 'xy',  -- 行情数据源标识（xy/westock 等）
    run_id          VARCHAR(40),  -- 跑批标识，便于溯源与重跑
    PRIMARY KEY (symbol, trade_date)
)
PARTITION BY RANGE (trade_date);
CREATE TABLE market.index_daily (
    index_code      VARCHAR(20)      NOT NULL,  -- 指数代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    open            NUMERIC(18,4),  -- 开盘价
    high            NUMERIC(18,4),  -- 最高价
    low             NUMERIC(18,4),  -- 最低价
    close           NUMERIC(18,4),  -- 收盘价
    volume          NUMERIC(24,2),  -- 成交量
    amount          NUMERIC(28,4),  -- 成交额（元）
    source          VARCHAR(16)      NOT NULL DEFAULT 'xy',  -- 行情数据源标识
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (index_code, trade_date)
)
PARTITION BY RANGE (trade_date);
CREATE TABLE market.industry_daily (
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    open            NUMERIC(18,4),  -- 行业指数开盘价
    high            NUMERIC(18,4),  -- 行业指数最高价
    low             NUMERIC(18,4),  -- 行业指数最低价
    close           NUMERIC(18,4),  -- 行业指数收盘价
    amount          NUMERIC(28,4),  -- 行业成交额（元）
    pe              NUMERIC(12,4),  -- 行业整体市盈率（TTM）
    pb              NUMERIC(12,4),  -- 行业整体市净率
    total_cap       NUMERIC(28,4),  -- 行业总市值（元）
    a_float_cap     NUMERIC(28,4),  -- 行业 A 股流通市值（元）
    source          VARCHAR(16)      NOT NULL DEFAULT 'xy',  -- 行情数据源标识
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (industry_code, trade_date),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
)
PARTITION BY RANGE (trade_date);
CREATE TABLE market.etf_daily (
    etf_code        VARCHAR(20)      NOT NULL,  -- ETF 代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    open            NUMERIC(18,4),  -- 开盘价
    high            NUMERIC(18,4),  -- 最高价
    low             NUMERIC(18,4),  -- 最低价
    close           NUMERIC(18,4),  -- 收盘价
    volume          NUMERIC(24,2),  -- 成交量
    amount          NUMERIC(28,4),  -- 成交额（元）
    source          VARCHAR(16)      NOT NULL DEFAULT 'xy',  -- 行情数据源标识
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (etf_code, trade_date)
)
PARTITION BY RANGE (trade_date);
CREATE TABLE market.chip_summary (
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    profit_rate     NUMERIC(12,6),  -- 获利比例（持仓成本低于收盘价的账户占比）
    avg_cost        NUMERIC(18,4),  -- 平均持仓成本
    conc90          NUMERIC(12,6),  -- 90% 成本集中度（筹码分散程度）
    conc70          NUMERIC(12,6),  -- 70% 成本集中度
    source          VARCHAR(16)      NOT NULL DEFAULT 'xy',  -- 行情数据源标识
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (symbol, trade_date)
)
PARTITION BY RANGE (trade_date);
CREATE TABLE market.announcement_event (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码
    publish_at      TIMESTAMPTZ      NOT NULL,  -- 公告发布时间
    tag_id          VARCHAR(32),  -- 公告标签 / 分类 ID（如 业绩预告 / 增持）
    title           VARCHAR(256),  -- 公告标题
    url             VARCHAR(512)     NOT NULL,  -- 公告原文链接
    sentiment       SMALLINT         DEFAULT 0,  -- 情感极性：-1 负面 / 0 中性 / 1 正面
    processed_at    TIMESTAMPTZ,  -- NLP 解析完成时间；NULL 表示未处理
    PRIMARY KEY (id),
    UNIQUE (symbol, url)
);
CREATE TABLE market.macro_indicator (
    indicator_code  VARCHAR(32)      NOT NULL,  -- 指标代码，主键之一（CPI / PPI / PMI / M1 / M2 / GDP / TSF 社融 / BOND1Y / BOND10Y / BOND30Y / USDCNY / DXY / SHIBOR_ON / DR007 / GOLD / WTI / CU / UST10Y 等）
    freq            VARCHAR(8)       NOT NULL DEFAULT 'M',  -- 频率，主键之一：D 日频（国债收益率/汇率/流动性/大宗/美债等日频宏观，AG-07 采，作辅助信号不改 regime）/ M 月频 / Q 季频；SC-08 分频采集标记，AD-10 分组展示不混排
    period          VARCHAR(10)      NOT NULL,  -- 数据期间，主键之一（日频为数据日期 YYYY-MM-DD；月频为 YYYY-MM；GDP 季频为 YYYY-Qn）
    indicator_name  VARCHAR(64)      NOT NULL,  -- 指标中文名（如 CPI 居民消费价格指数、Shibor 隔夜）
    val             NUMERIC(16,6),  -- 指标数值
    unit            VARCHAR(16),  -- 单位（% / 万亿 / 点 / 元）
    yoy             NUMERIC(10,4),  -- 同比增速（日频指标可为空或填环比 bp 变动）
    publish_time    TIMESTAMPTZ,  -- 官方公布时间
    source          VARCHAR(16),  -- 数据源（xy / westock / akshare）
    run_id          VARCHAR(40),  -- 跑批标识
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 本系统最新更新时间（AD-02 运维监控逐指标展示用，日频/月频分组展示）
    PRIMARY KEY (indicator_code, freq, period)
);
CREATE TABLE market.meso_monthly (
    industry_code   VARCHAR(20)      NOT NULL,  -- 申万一级行业代码，主键之一（C-8 以星耀申万为唯一基准）
    period          VARCHAR(8)       NOT NULL,  -- 数据月份，主键之一（YYYY-MM）
    metric_code     VARCHAR(32)      NOT NULL,  -- 低频指标代码，主键之一（prosperity 景气指数 / output 产量 / inventory 库存 / fin_agg 行业财务聚合）
    metric_name     VARCHAR(64)      NOT NULL,  -- 指标中文名（如 汽车制造业景气指数）
    val             NUMERIC(16,6),  -- 指标数值
    yoy             NUMERIC(10,4),  -- 同比增速
    source          VARCHAR(16),  -- 数据源（xy / westock / akshare）
    run_id          VARCHAR(40),  -- 跑批标识（agent-meso-monthly，AG-08）
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 本系统最新更新时间；缺失时行业打分降级（MD-07）
    PRIMARY KEY (industry_code, period, metric_code)
);

-- ===========================================================================
-- factor 因子库
-- ===========================================================================
CREATE TABLE factor.factor_def (
    factor_code     VARCHAR(32)      NOT NULL,  -- 因子代码，主键之一
    name            VARCHAR(64)      NOT NULL,  -- 因子名称
    dimension       VARCHAR(20)      NOT NULL,  -- 因子维度：fundamental 基本面 / news 新闻 / capital 资金 / technical 技术 / chip 筹码
    formula         TEXT,  -- 因子计算公式（可读表达式，用于审计与复现）
    params_json     JSONB,  -- 因子参数（JSON：窗口、阈值等）
    version         INTEGER          NOT NULL,  -- 因子版本，主键之一（支持多版本并存）
    status          VARCHAR(16)      NOT NULL DEFAULT 'draft',  -- 因子状态：draft 草稿 / approved 已审批 / retired 已退役
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (factor_code, version)
);
CREATE TABLE factor.factor_value (
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    factor_code     VARCHAR(32)      NOT NULL,  -- 因子代码，主键之一
    version         INTEGER          NOT NULL,  -- 因子版本，主键之一
    raw_value       NUMERIC(24,8),  -- 因子原始计算值
    std_value       NUMERIC(18,8),  -- 标准化值（如 z-score）
    neutral_value   NUMERIC(18,8),  -- 行业中性化后的值
    source          VARCHAR(16)      NOT NULL DEFAULT 'xy',  -- 数据源标识
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (symbol, trade_date, factor_code),
    FOREIGN KEY (factor_code, version) REFERENCES factor.factor_def (factor_code, version)
)
PARTITION BY RANGE (trade_date);
CREATE TABLE factor.factor_version (
    version         INTEGER          NOT NULL,  -- 版本号，主键
    applied_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 该版本应用生效时间
    weights_json    JSONB,  -- 多因子合成权重配置（JSON）
    snapshot_json   JSONB,  -- 因子集快照（构成因子与参数，用于复现）
    rollback_of     INTEGER,  -- 回滚自哪个版本；NULL 表示正向发布
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (version)
);
CREATE TABLE factor.factor_report (
    report_id       BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    factor_code     VARCHAR(32)      NOT NULL,  -- 因子代码
    version         INTEGER          NOT NULL,  -- 因子版本
    content_json    JSONB,  -- 因子研究报告内容（JSON）
    report_url      VARCHAR(512),  -- 研究报告文件链接
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (report_id),
    FOREIGN KEY (factor_code, version) REFERENCES factor.factor_def (factor_code, version)
);
CREATE TABLE factor.factor_eval (
    factor_code     VARCHAR(32)      NOT NULL,  -- 因子代码，主键之一
    version         INTEGER          NOT NULL,  -- 因子版本，主键之一
    ic_mean         NUMERIC(10,6),  -- 平均信息系数 IC（预测力）
    ir              NUMERIC(10,6),  -- 信息比率（IC 均值 / IC 标准差）
    turnover        NUMERIC(10,6),  -- 换手率
    mono_score      NUMERIC(10,6),  -- 单调性得分（分组收益是否单调）
    passed          BOOLEAN,  -- 是否通过评估门槛（进入合成候选）
    report_url      VARCHAR(512),  -- 评估报告链接
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (factor_code, version),
    FOREIGN KEY (factor_code, version) REFERENCES factor.factor_def (factor_code, version)
);

-- ===========================================================================
-- signal 信号库
-- ===========================================================================
CREATE TABLE signal.macro_signal (
    as_of           DATE             NOT NULL,  -- 适用期（月频，仅保留最新已发布一期），主键
    regime          VARCHAR(32)      NOT NULL,  -- 经济状态：复苏 / 过热 / 滞胀 / 衰退
    money_credit    VARCHAR(32),    -- 货币信用组合状态：双宽 / 宽货币紧信用 / 紧货币宽信用 / 双紧（§1.7 枚举）
    growth_s        NUMERIC(12,6),  -- 增长维度得分
    inflation_s     NUMERIC(12,6),  -- 通胀维度得分
    money_s         NUMERIC(12,6),  -- 货币维度得分
    credit_s        NUMERIC(12,6),  -- 信用维度得分
    equity_weight   NUMERIC(6,4),  -- 权益仓位上限（建议，0~1）
    style_json      JSONB,  -- 风格配置（JSON：大盘/小盘/成长/价值 等权重）
    asset_alloc_json JSONB,  -- 大类资产配置（JSON：股/债/商品 等）
    confidence      NUMERIC(5,4)     NOT NULL DEFAULT 1.0,  -- 信号置信度（0~1）
    run_id          VARCHAR(40),  -- 跑批标识
    signal_json     JSONB,         -- MacroSignal 完整契约（§1.7）：regime / phase / money_credit / asset_alloc / factors / vintage / forecast_signals；页面只读，不回写
    PRIMARY KEY (as_of)
);
CREATE TABLE signal.macro_aux_signal (
    as_of           DATE             NOT NULL,  -- 适用期，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    dr001           NUMERIC(12,6),  -- DR001 绝对水平（银行间质押式回购加权利率，%）
    dr001_ma20      NUMERIC(12,6),  -- DR001 20 日滚动均值
    dr001_pctile    NUMERIC(12,6),  -- DR001 滚动分位（0~1）
    dr001_extreme  VARCHAR(16),  -- 极端标记：high 高位 / low 低位 / normal 常态
    warn_flags      JSONB,  -- 预警标记集合（JSON 数组：量价背离 / 税期季末扰动 等）
    aux_note        TEXT,  -- 辅助说明（展示文案，不参与判定）
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (as_of, trade_date)
);
CREATE TABLE signal.macro_forecast (
    signal_id       VARCHAR(64)      NOT NULL,  -- 预测信号标识，主键
    chain           VARCHAR(64)      NOT NULL,  -- 传导链（如 ppi_to_cpi / m1_growth）
    basis_period    VARCHAR(16)      NOT NULL,  -- 依据数据所属期（仅已发布期）
    lead_window     VARCHAR(16)      NOT NULL,  -- 领先窗口：short 短窗 1-2 月 / long 长窗 3-6 月
    direction       VARCHAR(16)      NOT NULL,  -- 推断方向：up 上行 / down 下行 / flat 持平
    confidence      NUMERIC(5,4),  -- 置信度（0~1）
    hit_rate_status VARCHAR(16)      NOT NULL DEFAULT 'pending',  -- 命中率状态：pending 待回测 / valid 已回测 / invalid 已失效
    invalid_if      TEXT,  -- 失效条件（触发即降「参考级」）
    as_of           DATE             NOT NULL,  -- 信号产出日（不得晚于 basis_period 的已发布期）
    PRIMARY KEY (signal_id)
);
CREATE TABLE signal.meso_nowcast (
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    pe_pctile       NUMERIC(12,6),  -- 行业 ETF 估值滚动分位（0~1）
    fundflow_pctile NUMERIC(12,6),  -- 资金流分位（0~1）
    crowding_pctile NUMERIC(12,6),  -- 拥挤度分位（0~1）
    leverage_pctile NUMERIC(12,6),  -- 杠杆率分位（0~1）
    direction       VARCHAR(16),  -- 方向快照：confirm 印证 / divergence 背离 / risk_block 极端风险
    block_new_entry BOOLEAN          NOT NULL DEFAULT false,  -- 是否拦截新增（仅拦新增，不改清单与分数）
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (industry_code, trade_date),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE signal.industry_rank (
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    momentum_s      NUMERIC(12,6),  -- 动量维度得分
    valuation_s     NUMERIC(12,6),  -- 估值维度得分
    fundflow_s      NUMERIC(12,6),  -- 资金流维度得分
    crowding_s      NUMERIC(12,6),  -- 拥挤度维度得分
    total_score     NUMERIC(12,6),  -- 综合得分
    rank            INTEGER          NOT NULL,  -- 综合排名（1 为最优）
    etf_code        VARCHAR(20),  -- 推荐跟踪该行业的 ETF 代码
    weight          NUMERIC(6,4),  -- 建议配置权重（0~1）
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (industry_code, trade_date),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE signal.stock_score (
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    industry_code   VARCHAR(20)      NOT NULL,  -- 所属申万行业代码
    fundamental_s   NUMERIC(12,6),  -- 基本面维度得分
    news_s          NUMERIC(12,6),  -- 新闻情绪维度得分
    capital_s       NUMERIC(12,6),  -- 资金面维度得分
    technical_s     NUMERIC(12,6),  -- 技术面维度得分
    chip_s          NUMERIC(12,6),  -- 筹码维度得分
    total_score     NUMERIC(12,6),  -- 综合得分
    rank_in_industry INTEGER,  -- 行业内排名
    rank_all        INTEGER,  -- 全市场排名
    advice          VARCHAR(16),  -- 投资建议：buy 买入 / hold 持有 / sell 卖出 / watch 观察
    run_id          VARCHAR(40),  -- 跑批标识
    PRIMARY KEY (symbol, trade_date),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code),
    FOREIGN KEY (symbol)        REFERENCES market.security (symbol)
);
CREATE TABLE signal.signal (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码
    trade_date      DATE             NOT NULL,  -- 信号交易日
    source_layer    VARCHAR(16)      NOT NULL,  -- 来源层级：macro 宏观 / meso 中观 / micro 微观
    score           NUMERIC(12,6),  -- 信号得分
    entry_price_ref NUMERIC(18,4),  -- 参考买入价
    industry_code   VARCHAR(20),  -- 申万行业代码
    strategy_ver    VARCHAR(32)      NOT NULL,  -- 策略版本
    reason_json     JSONB,  -- 对内决策明细（对外裁剪时剔除，仅管理端可见）
    status          VARCHAR(16)      NOT NULL DEFAULT 'active',  -- 信号状态：active 有效 / expired 失效
    published_at    TIMESTAMPTZ,  -- 对外发布时间
    PRIMARY KEY (id),
    UNIQUE (symbol, trade_date, source_layer, strategy_ver),
    FOREIGN KEY (symbol) REFERENCES market.security (symbol)
);
CREATE TABLE signal.advice_batch (
    batch_id        BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    as_of           DATE             NOT NULL,  -- 适用期，关联 macro_signal.as_of
    equity_weight   NUMERIC(6,4),  -- 权益仓位上限（0~1）
    asset_alloc_json JSONB,  -- 大类资产配置（JSON）
    status          VARCHAR(16)      NOT NULL DEFAULT 'open',  -- 批次状态：open 开放 / closed 关闭
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (batch_id)
);
CREATE TABLE signal.advice_node (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    batch_id        BIGINT           NOT NULL,  -- 所属建议批次
    parent_id       BIGINT,  -- 父节点（自引用，根节点为 NULL）
    node_type       VARCHAR(16)      NOT NULL,  -- 节点类型：asset 大类资产 / industry 行业 / stock 个股
    name            VARCHAR(64)      NOT NULL,  -- 节点名称
    weight          NUMERIC(6,4),  -- 节点权重（0~1）
    target_json     JSONB,  -- 对外可见内容（股票代码/名称/权重；客户端展示用）
    reason_json     JSONB,  -- 对内决策明细（对外裁剪时剔除，仅管理端可见）
    PRIMARY KEY (id),
    UNIQUE (batch_id, id),
    FOREIGN KEY (batch_id) REFERENCES signal.advice_batch (batch_id),
    FOREIGN KEY (parent_id) REFERENCES signal.advice_node (id)
);

-- ===========================================================================
-- portfolio 组合库
-- ===========================================================================
CREATE TABLE portfolio.portfolio (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    name            VARCHAR(64)      NOT NULL,  -- 组合名称
    kind            VARCHAR(16)      NOT NULL DEFAULT 'virtual',  -- 组合类型：virtual 虚拟 / live 实盘
    cash            NUMERIC(20,4)    NOT NULL DEFAULT 0,  -- 现金余额
    base_currency   VARCHAR(8)       NOT NULL DEFAULT 'CNY',  -- 基准币种，默认 CNY
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (id)
);
CREATE TABLE portfolio.position (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    portfolio_id    BIGINT           NOT NULL,  -- 所属组合 ID
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码
    qty             NUMERIC(24,4)    NOT NULL,  -- 持仓数量
    cost_price      NUMERIC(18,4),  -- 持仓成本价
    weight          NUMERIC(6,4),  -- 持仓权重（组合内占比，0~1）
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 更新时间
    PRIMARY KEY (id),
    FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolio (id)
);
CREATE TABLE portfolio.order_proposal (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    portfolio_id    BIGINT           NOT NULL,  -- 所属组合 ID
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码
    side            VARCHAR(4)       NOT NULL,  -- 买卖方向：buy 买入 / sell 卖出
    qty             NUMERIC(24,4)    NOT NULL,  -- 建议数量
    price_ref       NUMERIC(18,4),  -- 参考价
    status          VARCHAR(16)      NOT NULL DEFAULT 'pending',  -- 状态：pending 待确认 / confirmed 已确认 / rejected 已驳回 / filled 已成交
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    confirmed_at    TIMESTAMPTZ,  -- 确认时间
    PRIMARY KEY (id),
    FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolio (id)
);
CREATE TABLE portfolio.trade (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    portfolio_id    BIGINT           NOT NULL,  -- 所属组合 ID
    symbol          VARCHAR(20)      NOT NULL,  -- 股票代码
    side            VARCHAR(4)       NOT NULL,  -- 买卖方向：buy / sell
    qty             NUMERIC(24,4)    NOT NULL,  -- 成交数量
    price           NUMERIC(18,4)    NOT NULL,  -- 成交价
    fee             NUMERIC(18,4)    NOT NULL DEFAULT 0,  -- 手续费
    traded_at       TIMESTAMPTZ      NOT NULL,  -- 成交时间
    proposal_id     BIGINT,  -- 关联调仓建议单（可为空）
    PRIMARY KEY (id),
    FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolio (id),
    FOREIGN KEY (proposal_id)  REFERENCES portfolio.order_proposal (id)
);
CREATE TABLE portfolio.daily_mark (
    portfolio_id    BIGINT           NOT NULL,  -- 所属组合 ID，主键之一
    trade_date      DATE             NOT NULL,  -- 交易日，主键之一
    market_value    NUMERIC(28,4)    NOT NULL,  -- 当日市值
    pnl             NUMERIC(28,4),  -- 当日盈亏
    cum_pnl         NUMERIC(28,4),  -- 累计盈亏
    benchmark_nav   NUMERIC(18,6),  -- 基准净值（用于对比超额）
    PRIMARY KEY (portfolio_id, trade_date),
    FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolio (id)
);

-- ===========================================================================
-- metric 计量库
-- ===========================================================================
CREATE TABLE metric.signal_tracking (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    signal_id       BIGINT           NOT NULL,  -- 关联信号 ID
    horizon         INTEGER          NOT NULL,  -- 持有期（交易日数）
    ret             NUMERIC(12,6),  -- 持有期收益率
    excess_ret      NUMERIC(12,6),  -- 超额收益率（相对基准）
    win             BOOLEAN,  -- 是否盈利（胜）
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 更新时间
    PRIMARY KEY (id),
    UNIQUE (signal_id, horizon),
    FOREIGN KEY (signal_id) REFERENCES signal.signal (id)
);
CREATE TABLE metric.winrate_stat (
    source_layer    VARCHAR(16)      NOT NULL,  -- 来源层级：macro / meso / micro
    industry_code   VARCHAR(20)      NOT NULL,  -- 行业代码
    horizon         INTEGER          NOT NULL,  -- 持有期
    stat_date       DATE             NOT NULL,  -- 统计日期
    samples         INTEGER          NOT NULL,  -- 样本数
    win_rate        NUMERIC(6,4)     NOT NULL,  -- 胜率（0~1）
    avg_ret         NUMERIC(12,6),  -- 平均收益
    avg_excess      NUMERIC(12,6),  -- 平均超额收益
    profit_loss_ratio NUMERIC(10,4),  -- 盈亏比
    PRIMARY KEY (source_layer, industry_code, horizon, stat_date),
    FOREIGN KEY (industry_code) REFERENCES common.industry (industry_code)
);
CREATE TABLE metric.backtest_task (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    params_json     JSONB            NOT NULL,  -- 回测参数（JSON：标的池/周期/手续费等）
    data_version    VARCHAR(40),  -- 数据版本 / 快照标识
    status          VARCHAR(16)      NOT NULL DEFAULT 'queued',  -- 状态：queued 排队 / running 运行中 / done 完成 / failed 失败
    started_at      TIMESTAMPTZ,  -- 开始时间
    ended_at        TIMESTAMPTZ,  -- 结束时间
    PRIMARY KEY (id)
);
CREATE TABLE metric.backtest_result (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    task_id         BIGINT           NOT NULL,  -- 关联回测任务 ID
    annual_ret      NUMERIC(12,6),  -- 年化收益
    volatility      NUMERIC(12,6),  -- 年化波动率
    sharpe          NUMERIC(10,4),  -- 夏普比率
    sortino         NUMERIC(10,4),  -- 索提诺比率
    max_drawdown    NUMERIC(10,4),  -- 最大回撤
    calmar          NUMERIC(10,4),  -- 卡玛比率（年化收益 / 最大回撤）
    win_rate        NUMERIC(6,4),  -- 胜率
    turnover        NUMERIC(10,4),  -- 换手率
    ic              NUMERIC(10,6),  -- 信息系数
    ir              NUMERIC(10,6),  -- 信息比率
    net_value_json  JSONB,  -- 净值序列（JSON：日期-净值 数组）
    PRIMARY KEY (id),
    FOREIGN KEY (task_id) REFERENCES metric.backtest_task (id)
);

-- ===========================================================================
-- task 任务与调度（调度由 WorkBuddy 自动化任务承担，线上为只读同步副本）
-- ===========================================================================
CREATE TABLE task.task_run (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    task_code       VARCHAR(40)      NOT NULL,  -- 任务标识（如 macro / meso / micro / assemble-risk）
    run_id          VARCHAR(40)      NOT NULL,  -- 跑批标识（本次运行唯一）
    status          VARCHAR(16)      NOT NULL,  -- 运行状态：running / done / skipped / failed
    window_date     DATE             NOT NULL,  -- 数据窗口日（本批处理的数据截止日）
    started_at      TIMESTAMPTZ,  -- 开始时间
    ended_at        TIMESTAMPTZ,  -- 结束时间
    rows            INTEGER,  -- 处理行数
    error           TEXT,  -- 错误信息（失败时有值）
    source_stats    JSONB,  -- 数据源统计（JSON：各源行数/耗时）
    PRIMARY KEY (id)
);
CREATE TABLE task.agent_run (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    agent_code      VARCHAR(16)      NOT NULL,  -- Agent 标识（macro-daily / macro-monthly / meso-daily / meso-monthly / micro，按频率独立成任务）
    run_id          VARCHAR(40)      NOT NULL,  -- 跑批标识，关联 task_run.run_id
    data_items      JSONB,  -- 本次采集的数据种类清单（JSON 数组，AD-02「采集了哪些数据」展示用）
    rows_fetched    INTEGER,  -- 采集条数
    missing_json    JSONB,  -- 缺失明细（JSON：缺失范围与类型；无缺失为空）
    latency_ms      INTEGER,  -- 耗时（毫秒）
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录时间
    PRIMARY KEY (id)
);
CREATE TABLE task.data_item (
    id              VARCHAR(64)      NOT NULL,  -- 数据项编码，主键（不可变；删除判引用只看本列）
    name            VARCHAR(128)     NOT NULL,  -- 数据项名称（全库唯一、可改）
    freq            VARCHAR(16)      NOT NULL,  -- 数据频率：daily 日频 / monthly 月频 / quarterly 季频
    factor_layer    VARCHAR(16),  -- 所属因子层：macro 宏观 / meso 中观 / micro 微观
    api             VARCHAR(128),  -- 取数接口标识
    publish_slot    VARCHAR(32),  -- 发布时点（如 每月 10-20 日 / 每月 15 日）
    job_code        VARCHAR(40),  -- 挂载任务标识（未挂载时为空）
    rows            INTEGER,  -- 累计行数
    latest_period   VARCHAR(16),  -- 库内最新期次
    gap_periods     INTEGER,  -- 库内最新期次与官方最新可获取之间的缺口期数（服务端算，前端不勾选）
    last_fetch_at   TIMESTAMPTZ,  -- 最近拉取时间
    status          VARCHAR(16)      NOT NULL DEFAULT 'active',  -- 状态：active 启用 / inactive 停用
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 修改时间
    PRIMARY KEY (id),
    UNIQUE (name)
);
CREATE TABLE task.data_ref (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    data_id         VARCHAR(64)      NOT NULL,  -- 数据项编码，关联 task.data_item.id
    used_by         VARCHAR(128)     NOT NULL,  -- 引用方标识（策略 / 报表 / 任务）
    kind            VARCHAR(16)      NOT NULL,  -- 引用类别：strategy 策略 / report 报表
    note            TEXT,  -- 备注
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (id),
    UNIQUE (data_id, used_by),
    FOREIGN KEY (data_id) REFERENCES task.data_item (id)
);
CREATE TABLE task.run_log (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    started_at      TIMESTAMPTZ      NOT NULL,  -- 开始时间
    job_code        VARCHAR(40)      NOT NULL,  -- 任务标识
    item_ids        JSONB,  -- 涉及的数据项编码数组（JSON 数组；删除数据项时按此联动清理）
    err_type        VARCHAR(32),  -- 错误类型（失败时记录）
    result_text     TEXT,  -- 结果摘要
    lv              VARCHAR(16),  -- 处置级别：wait 待处理 / done 已完成（NULL 表示未分类）
    retry_cnt       SMALLINT         DEFAULT 0,  -- 重试次数
    trigger_type    VARCHAR(16),  -- 触发方式：auto 调度 / manual 手动 / rerun 补跑
    cost_ms         INTEGER,  -- 耗时（毫秒）
    detail_msg      TEXT,  -- 明细
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录时间
    PRIMARY KEY (id)
);
CREATE TABLE task.schedule_config (
    task_code       VARCHAR(40)      NOT NULL,  -- 任务标识，主键
    cron_expr       VARCHAR(64)      NOT NULL DEFAULT '0 2 * * *',  -- 系统侧默认 cron 基线（日频 0 2 * * *；宏观月频窗口 0 2 10-20 * *）；实际执行以 WorkBuddy 自动化任务为准（task.job_def）
    enabled         BOOLEAN          NOT NULL DEFAULT true,  -- 是否启用
    updated_by      VARCHAR(40),  -- 最后修改人
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 修改时间
    PRIMARY KEY (task_code)
);
CREATE TABLE task.job_def (
    job_key         VARCHAR(40)      NOT NULL,  -- 任务键，主键（macro_daily / macro_monthly / meso_daily / meso_monthly / micro_daily / risk_assemble / tracking_daily / portfolio_daily / factor_lab / backtest_run）
    job_name        VARCHAR(64)      NOT NULL,  -- 任务中文名（AD-11 任务清单展示）
    freq            VARCHAR(16)      NOT NULL,  -- 任务频率：daily 日频 / monthly 月频 / weekly 周频 / manual 按需；同层不同频率独立成 job（C-12）
    cron_expr       VARCHAR(64),  -- cron 表达式（5 段标准格式，如 0 2 * * *；月频窗口 0 2 10-20 * *）；按需任务为空；不得落在 9:30-15:00（SC-02/06）
    cli_command     VARCHAR(256)     NOT NULL,  -- 对应 Python CLI 命令（如 python -m agent.macro_daily）
    params_json     JSONB,  -- 任务参数（JSON：指标组、重试策略、窗口等）
    automation_id   INTEGER,  -- WorkBuddy 自动化任务 ID（平台创建后回写，双写关联键）
    run_node        VARCHAR(64),  -- 执行节点（线下 offline-node；sync 类任务同为该节点）
    retry_cnt       SMALLINT         NOT NULL DEFAULT 3,  -- 失败重试次数（指数退避）
    timeout_sec     INTEGER          NOT NULL DEFAULT 1800,  -- 超时秒数（默认 30 分钟，NFR-01）
    enabled         BOOLEAN          NOT NULL DEFAULT true,  -- 是否启用（AD-11 启停操作）
    updated_by      VARCHAR(40),  -- 最后修改人（AD-11，留审计）
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 修改时间
    PRIMARY KEY (job_key)
);
CREATE TABLE task.job_instance (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    job_key         VARCHAR(40)      NOT NULL,  -- 任务键，关联 task.job_def.job_key
    run_id          VARCHAR(40)      NOT NULL,  -- 跑批标识（与 task_run.run_id / agent_run.run_id 串联 trace）
    automation_run_id VARCHAR(64),  -- 平台侧执行流水号（WorkBuddy 回写，用于对账）
    trigger_type    VARCHAR(16)      NOT NULL DEFAULT 'auto',  -- 触发方式：auto 调度自动 / manual 手动立即执行 / rerun 补跑
    scheduled_at    TIMESTAMPTZ,  -- 计划触发时间
    started_at      TIMESTAMPTZ,  -- 实际开始时间
    ended_at        TIMESTAMPTZ,  -- 结束时间
    duration_ms     INTEGER,  -- 耗时（毫秒，AD-11 展示）
    status          VARCHAR(16)      NOT NULL,  -- 执行状态：running / success / failed / timeout / retrying
    exit_code       SMALLINT,  -- CLI 退出码（0 正常）
    retry_cnt       SMALLINT         DEFAULT 0,  -- 本次执行已重试次数
    log_summary     TEXT,  -- 执行日志摘要（AD-11 列表展示；全量日志按需从线下 WorkBuddy 侧拉取）
    operator        VARCHAR(40),  -- 操作人（manual / rerun 时记录，留审计）
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 记录时间
    PRIMARY KEY (id)
);
CREATE TABLE task.rerun_request (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    agent_code      VARCHAR(16)      NOT NULL,  -- 目标 Agent（macro-daily / macro-monthly / meso-daily / meso-monthly / micro，按频率独立成任务）
    date_from       DATE             NOT NULL,  -- 补跑起点（日期或月份首日）
    date_to         DATE             NOT NULL,  -- 补跑终点
    data_type       VARCHAR(32)      NOT NULL,  -- 数据类型（指标 / 行业 / 股票，如 CPI / industry_daily / daily_bar）
    target_keys     JSONB,  -- 目标对象清单（JSON：指标代码 / 行业代码 / 股票代码列表；空表示该类型全部）
    requested_by    VARCHAR(40)      NOT NULL,  -- 发起人（AD-09 数据管理，写操作留审计）
    status          VARCHAR(16)      NOT NULL DEFAULT 'pending',  -- 状态：pending / running / done / failed
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    finished_at     TIMESTAMPTZ,  -- 完成时间
    PRIMARY KEY (id)
);
CREATE TABLE task.quality_alert (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    task_code       VARCHAR(40)      NOT NULL,  -- 关联任务标识
    data_item       VARCHAR(64),  -- 数据项名称
    check_type      VARCHAR(32),  -- 检查类型：freshness 时效性 / range 范围 / schema 结构 / consistency 一致性
    severity        VARCHAR(8)       NOT NULL DEFAULT 'warn',  -- 严重度：warn 警告 / error 错误
    detail          TEXT,  -- 告警详情
    handled_by      VARCHAR(40),  -- 处理人
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间
    PRIMARY KEY (id)
);
CREATE TABLE task.source_health (
    source          VARCHAR(16)      NOT NULL,  -- 数据源标识（xy / westock / akshare），主键
    status          VARCHAR(16)      NOT NULL,  -- 状态：ok 正常 / degraded 降级 / down 不可用
    last_trade_date DATE,  -- 最近获取到的交易日数据
    last_source     VARCHAR(16),  -- 实际获取来源
    latency_ms      INTEGER,  -- 抓取延迟（毫秒）
    checked_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 检查时间
    PRIMARY KEY (source)
);

-- ===========================================================================
-- platform 平台
-- ===========================================================================
CREATE TABLE platform.admin_user (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    username        VARCHAR(64)      NOT NULL UNIQUE,  -- 管理员登录用户名（唯一）
    password_hash   VARCHAR(128)     NOT NULL,  -- 密码哈希
    mfa_secret      VARCHAR(64),  -- MFA 密钥（启用二次验证时使用）
    status          VARCHAR(16)      NOT NULL DEFAULT 'active',  -- 状态：active / disabled
    last_login_at   TIMESTAMPTZ,  -- 最后登录时间
    PRIMARY KEY (id)
);
CREATE TABLE platform.role (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    code            VARCHAR(32)      NOT NULL UNIQUE,  -- 角色代码（唯一）
    name            VARCHAR(64)      NOT NULL,  -- 角色名称
    PRIMARY KEY (id)
);
CREATE TABLE platform.permission (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键
    code            VARCHAR(32)      NOT NULL UNIQUE,  -- 权限代码（唯一）
    name            VARCHAR(64)      NOT NULL,  -- 权限名称
    PRIMARY KEY (id)
);
CREATE TABLE platform.admin_role (
    admin_id        BIGINT           NOT NULL,  -- 管理员 ID
    role_id         BIGINT           NOT NULL,  -- 角色 ID
    PRIMARY KEY (admin_id, role_id),
    FOREIGN KEY (admin_id) REFERENCES platform.admin_user (id),
    FOREIGN KEY (role_id)  REFERENCES platform.role (id)
);
CREATE TABLE platform.role_permission (
    role_id         BIGINT           NOT NULL,  -- 角色 ID
    permission_id   BIGINT           NOT NULL,  -- 权限 ID
    PRIMARY KEY (role_id, permission_id),
    FOREIGN KEY (role_id)      REFERENCES platform.role (id),
    FOREIGN KEY (permission_id) REFERENCES platform.permission (id)
);
CREATE TABLE platform.audit_log (
    id              BIGINT           GENERATED ALWAYS AS IDENTITY,  -- 自增主键，复合主键之一
    actor_type      VARCHAR(16)      NOT NULL,  -- 操作主体类型：user 用户 / admin 管理员 / system 系统
    actor_id        VARCHAR(40),  -- 操作主体 ID
    action          VARCHAR(32)      NOT NULL,  -- 操作类型（如 create / update / delete / login）
    object_type     VARCHAR(32),  -- 操作对象类型
    object_id       VARCHAR(64),  -- 操作对象 ID
    before          JSONB,  -- 变更前内容（JSON）
    after           JSONB,  -- 变更后内容（JSON）
    ip              VARCHAR(64),  -- 来源 IP
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- 创建时间，复合主键之一（兼分区键）
    PRIMARY KEY (id, created_at)
)
PARTITION BY RANGE (created_at);

-- ===========================================================================
-- 9. 分区维护（按年创建子分区，覆盖 2020-2030；新增年份按模板加）
-- ===========================================================================
CREATE OR REPLACE FUNCTION task.create_yearly_partition(
    p_parent  TEXT,
    p_year   INT
) RETURNS VOID AS $$
DECLARE
    v_start DATE := make_date(p_year, 1, 1);
    v_end   DATE := make_date(p_year + 1, 1, 1);
    v_name  TEXT := p_parent || '_' || p_year;
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
        v_name, p_parent, v_start, v_end
    );
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE y INT;
BEGIN
    FOR y IN 2020 .. 2030 LOOP
        PERFORM task.create_yearly_partition('market.daily_bar',     y);
        PERFORM task.create_yearly_partition('market.index_daily',   y);
        PERFORM task.create_yearly_partition('market.industry_daily',y);
        PERFORM task.create_yearly_partition('market.etf_daily',     y);
        PERFORM task.create_yearly_partition('market.chip_summary',  y);
        PERFORM task.create_yearly_partition('factor.factor_value',  y);
        PERFORM task.create_yearly_partition('platform.audit_log',   y);
    END LOOP;
END $$;


-- ===========================================================================
-- 10. 索引约定（时序表主键已含 trade_date；补充高频查询索引）
-- ===========================================================================
CREATE INDEX IF NOT EXISTS idx_daily_bar_date        ON market.daily_bar (trade_date);
CREATE INDEX IF NOT EXISTS idx_industry_daily_date   ON market.industry_daily (trade_date, industry_code);
CREATE INDEX IF NOT EXISTS idx_factor_value_date     ON factor.factor_value (trade_date, factor_code);
CREATE INDEX IF NOT EXISTS idx_factor_value_symbol   ON factor.factor_value (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_score_date     ON signal.stock_score (trade_date, total_score DESC);
CREATE INDEX IF NOT EXISTS idx_stock_score_ind      ON signal.stock_score (industry_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_industry_rank_date   ON signal.industry_rank (trade_date, rank);
CREATE INDEX IF NOT EXISTS idx_signal_published     ON signal.signal (published_at);
CREATE INDEX IF NOT EXISTS idx_signal_symbol        ON signal.signal (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_advice_node_batch    ON signal.advice_node (batch_id);
CREATE INDEX IF NOT EXISTS idx_signal_tracking_sig  ON metric.signal_tracking (signal_id);
CREATE INDEX IF NOT EXISTS idx_winrate_stat_date    ON metric.winrate_stat (stat_date);
CREATE INDEX IF NOT EXISTS idx_task_run_code        ON task.task_run (task_code, window_date);
CREATE INDEX IF NOT EXISTS idx_announcement_symbol  ON market.announcement_event (symbol, publish_at);
CREATE INDEX IF NOT EXISTS idx_macro_ind_period    ON market.macro_indicator (period);
CREATE INDEX IF NOT EXISTS idx_meso_monthly_period  ON market.meso_monthly (period);
CREATE INDEX IF NOT EXISTS idx_agent_run_run        ON task.agent_run (run_id);
CREATE INDEX IF NOT EXISTS idx_rerun_status         ON task.rerun_request (status, created_at);
CREATE INDEX IF NOT EXISTS idx_job_instance_job     ON task.job_instance (job_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_instance_status  ON task.job_instance (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_macro_aux_date       ON signal.macro_aux_signal (trade_date);
CREATE INDEX IF NOT EXISTS idx_macro_forecast_basis    ON signal.macro_forecast (basis_period, as_of);
CREATE INDEX IF NOT EXISTS idx_meso_nowcast_date      ON signal.meso_nowcast (trade_date, industry_code);
CREATE INDEX IF NOT EXISTS idx_data_item_job          ON task.data_item (job_code);
CREATE INDEX IF NOT EXISTS idx_data_ref_data          ON task.data_ref (data_id);
CREATE INDEX IF NOT EXISTS idx_run_log_started        ON task.run_log (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_log_lv             ON task.run_log (lv);
CREATE INDEX IF NOT EXISTS idx_audit_created        ON platform.audit_log (created_at);


-- ===========================================================================
-- 11. 字段注释（写入数据字典，\d+ 表名 可见；与上方行内注释一致）
-- ===========================================================================
-- ---- common.industry ----
COMMENT ON COLUMN common.industry.industry_code IS '行业代码（申万口径，如 SW801010），全系统行业主键';
COMMENT ON COLUMN common.industry.industry_name IS '行业名称';
COMMENT ON COLUMN common.industry.level IS '行业层级：1 一级 / 2 二级 / 3 三级（申万口径 31/134/346）';
COMMENT ON COLUMN common.industry.parent_code IS '父行业代码（自引用，顶级为 NULL）';
COMMENT ON COLUMN common.industry.standard IS '行业分类标准，默认 SW（申万）；系统唯一基准（C-8，禁止东财口径 JOIN）';
COMMENT ON COLUMN common.industry.updated_at IS '记录更新时间';

-- ---- common.industry_etf_map ----
COMMENT ON COLUMN common.industry_etf_map.industry_code IS '行业代码，主键之一';
COMMENT ON COLUMN common.industry_etf_map.etf_code IS '跟踪该行业的 ETF 代码，主键之一';
COMMENT ON COLUMN common.industry_etf_map.is_primary IS '是否该行业的主映射 ETF';
COMMENT ON COLUMN common.industry_etf_map.updated_at IS '记录更新时间';

-- ---- common.industry_constituent ----
COMMENT ON COLUMN common.industry_constituent.industry_code IS '行业代码，主键之一';
COMMENT ON COLUMN common.industry_constituent.symbol IS '股票代码，主键之一';
COMMENT ON COLUMN common.industry_constituent.in_date IS '纳入行业的时点（point-in-time，用于历史回测）';
COMMENT ON COLUMN common.industry_constituent.out_date IS '剔出行业的时点；NULL 表示当前仍在列';
COMMENT ON COLUMN common.industry_constituent.is_current IS '是否当前成分股（冗余字段，加速查询）';
COMMENT ON COLUMN common.industry_constituent.updated_at IS '记录更新时间';

-- ---- common.trade_calendar ----
COMMENT ON COLUMN common.trade_calendar.trade_date IS '交易日，主键';
COMMENT ON COLUMN common.trade_calendar.is_open IS '当日是否开市';
COMMENT ON COLUMN common.trade_calendar.is_month_start IS '是否月初（用于月频信号触发）';
COMMENT ON COLUMN common.trade_calendar.is_month_end IS '是否月末';

-- ---- market.security ----
COMMENT ON COLUMN market.security.symbol IS '股票代码，主键';
COMMENT ON COLUMN market.security.name IS '股票名称';
COMMENT ON COLUMN market.security.industry_code IS '所属申万行业代码';
COMMENT ON COLUMN market.security.list_date IS '上市日期';
COMMENT ON COLUMN market.security.delist_date IS '退市日期；NULL 表示未退市';
COMMENT ON COLUMN market.security.is_st IS '是否 ST / *ST / 退市风险警示';
COMMENT ON COLUMN market.security.updated_at IS '记录更新时间';

-- ---- market.daily_bar ----
COMMENT ON COLUMN market.daily_bar.symbol IS '股票代码，主键之一';
COMMENT ON COLUMN market.daily_bar.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN market.daily_bar.open IS '开盘价';
COMMENT ON COLUMN market.daily_bar.high IS '最高价';
COMMENT ON COLUMN market.daily_bar.low IS '最低价';
COMMENT ON COLUMN market.daily_bar.close IS '收盘价（后复权基准）';
COMMENT ON COLUMN market.daily_bar.volume IS '成交量（股）';
COMMENT ON COLUMN market.daily_bar.amount IS '成交额（元）';
COMMENT ON COLUMN market.daily_bar.adj_factor IS '复权因子（后复权）';
COMMENT ON COLUMN market.daily_bar.source IS '行情数据源标识（xy/westock 等）';
COMMENT ON COLUMN market.daily_bar.run_id IS '跑批标识，便于溯源与重跑';

-- ---- market.index_daily ----
COMMENT ON COLUMN market.index_daily.index_code IS '指数代码，主键之一';
COMMENT ON COLUMN market.index_daily.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN market.index_daily.open IS '开盘价';
COMMENT ON COLUMN market.index_daily.high IS '最高价';
COMMENT ON COLUMN market.index_daily.low IS '最低价';
COMMENT ON COLUMN market.index_daily.close IS '收盘价';
COMMENT ON COLUMN market.index_daily.volume IS '成交量';
COMMENT ON COLUMN market.index_daily.amount IS '成交额（元）';
COMMENT ON COLUMN market.index_daily.source IS '行情数据源标识';
COMMENT ON COLUMN market.index_daily.run_id IS '跑批标识';

-- ---- market.industry_daily ----
COMMENT ON COLUMN market.industry_daily.industry_code IS '行业代码，主键之一';
COMMENT ON COLUMN market.industry_daily.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN market.industry_daily.open IS '行业指数开盘价';
COMMENT ON COLUMN market.industry_daily.high IS '行业指数最高价';
COMMENT ON COLUMN market.industry_daily.low IS '行业指数最低价';
COMMENT ON COLUMN market.industry_daily.close IS '行业指数收盘价';
COMMENT ON COLUMN market.industry_daily.amount IS '行业成交额（元）';
COMMENT ON COLUMN market.industry_daily.pe IS '行业整体市盈率（TTM）';
COMMENT ON COLUMN market.industry_daily.pb IS '行业整体市净率';
COMMENT ON COLUMN market.industry_daily.total_cap IS '行业总市值（元）';
COMMENT ON COLUMN market.industry_daily.a_float_cap IS '行业 A 股流通市值（元）';
COMMENT ON COLUMN market.industry_daily.source IS '行情数据源标识';
COMMENT ON COLUMN market.industry_daily.run_id IS '跑批标识';

-- ---- market.etf_daily ----
COMMENT ON COLUMN market.etf_daily.etf_code IS 'ETF 代码，主键之一';
COMMENT ON COLUMN market.etf_daily.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN market.etf_daily.open IS '开盘价';
COMMENT ON COLUMN market.etf_daily.high IS '最高价';
COMMENT ON COLUMN market.etf_daily.low IS '最低价';
COMMENT ON COLUMN market.etf_daily.close IS '收盘价';
COMMENT ON COLUMN market.etf_daily.volume IS '成交量';
COMMENT ON COLUMN market.etf_daily.amount IS '成交额（元）';
COMMENT ON COLUMN market.etf_daily.source IS '行情数据源标识';
COMMENT ON COLUMN market.etf_daily.run_id IS '跑批标识';

-- ---- market.chip_summary ----
COMMENT ON COLUMN market.chip_summary.symbol IS '股票代码，主键之一';
COMMENT ON COLUMN market.chip_summary.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN market.chip_summary.profit_rate IS '获利比例（持仓成本低于收盘价的账户占比）';
COMMENT ON COLUMN market.chip_summary.avg_cost IS '平均持仓成本';
COMMENT ON COLUMN market.chip_summary.conc90 IS '90% 成本集中度（筹码分散程度）';
COMMENT ON COLUMN market.chip_summary.conc70 IS '70% 成本集中度';
COMMENT ON COLUMN market.chip_summary.source IS '行情数据源标识';
COMMENT ON COLUMN market.chip_summary.run_id IS '跑批标识';

-- ---- market.announcement_event ----
COMMENT ON COLUMN market.announcement_event.id IS '自增主键';
COMMENT ON COLUMN market.announcement_event.symbol IS '股票代码';
COMMENT ON COLUMN market.announcement_event.publish_at IS '公告发布时间';
COMMENT ON COLUMN market.announcement_event.tag_id IS '公告标签 / 分类 ID（如 业绩预告 / 增持）';
COMMENT ON COLUMN market.announcement_event.title IS '公告标题';
COMMENT ON COLUMN market.announcement_event.url IS '公告原文链接';
COMMENT ON COLUMN market.announcement_event.sentiment IS '情感极性：-1 负面 / 0 中性 / 1 正面';
COMMENT ON COLUMN market.announcement_event.processed_at IS 'NLP 解析完成时间；NULL 表示未处理';

-- ---- market.macro_indicator ----
COMMENT ON COLUMN market.macro_indicator.indicator_code IS '指标代码，主键之一（CPI / PPI / PMI / M1 / M2 / GDP / TSF 社融 / BOND1Y / BOND10Y / BOND30Y / USDCNY / DXY / SHIBOR_ON / DR007 / GOLD / WTI / CU / UST10Y 等）';
COMMENT ON COLUMN market.macro_indicator.freq IS '频率，主键之一：D 日频（国债收益率/汇率/流动性/大宗/美债等日频宏观，AG-07 采，作辅助信号不改 regime）/ M 月频 / Q 季频；SC-08 分频采集标记，AD-10 分组展示不混排';
COMMENT ON COLUMN market.macro_indicator.period IS '数据期间，主键之一（日频为数据日期 YYYY-MM-DD；月频为 YYYY-MM；GDP 季频为 YYYY-Qn）';
COMMENT ON COLUMN market.macro_indicator.indicator_name IS '指标中文名（如 CPI 居民消费价格指数、Shibor 隔夜）';
COMMENT ON COLUMN market.macro_indicator.val IS '指标数值';
COMMENT ON COLUMN market.macro_indicator.unit IS '单位（% / 万亿 / 点 / 元）';
COMMENT ON COLUMN market.macro_indicator.yoy IS '同比增速（日频指标可为空或填环比 bp 变动）';
COMMENT ON COLUMN market.macro_indicator.publish_time IS '官方公布时间';
COMMENT ON COLUMN market.macro_indicator.source IS '数据源（xy / westock / akshare）';
COMMENT ON COLUMN market.macro_indicator.run_id IS '跑批标识';
COMMENT ON COLUMN market.macro_indicator.updated_at IS '本系统最新更新时间（AD-02 运维监控逐指标展示用，日频/月频分组展示）';

-- ---- market.meso_monthly ----
COMMENT ON COLUMN market.meso_monthly.industry_code IS '申万一级行业代码，主键之一（C-8 以星耀申万为唯一基准）';
COMMENT ON COLUMN market.meso_monthly.period IS '数据月份，主键之一（YYYY-MM）';
COMMENT ON COLUMN market.meso_monthly.metric_code IS '低频指标代码，主键之一（prosperity 景气指数 / output 产量 / inventory 库存 / fin_agg 行业财务聚合）';
COMMENT ON COLUMN market.meso_monthly.metric_name IS '指标中文名（如 汽车制造业景气指数）';
COMMENT ON COLUMN market.meso_monthly.val IS '指标数值';
COMMENT ON COLUMN market.meso_monthly.yoy IS '同比增速';
COMMENT ON COLUMN market.meso_monthly.source IS '数据源（xy / westock / akshare）';
COMMENT ON COLUMN market.meso_monthly.run_id IS '跑批标识（agent-meso-monthly，AG-08）';
COMMENT ON COLUMN market.meso_monthly.updated_at IS '本系统最新更新时间；缺失时行业打分降级（MD-07）';

-- ---- factor.factor_def ----
COMMENT ON COLUMN factor.factor_def.factor_code IS '因子代码，主键之一';
COMMENT ON COLUMN factor.factor_def.name IS '因子名称';
COMMENT ON COLUMN factor.factor_def.dimension IS '因子维度：fundamental 基本面 / news 新闻 / capital 资金 / technical 技术 / chip 筹码';
COMMENT ON COLUMN factor.factor_def.formula IS '因子计算公式（可读表达式，用于审计与复现）';
COMMENT ON COLUMN factor.factor_def.params_json IS '因子参数（JSON：窗口、阈值等）';
COMMENT ON COLUMN factor.factor_def.version IS '因子版本，主键之一（支持多版本并存）';
COMMENT ON COLUMN factor.factor_def.status IS '因子状态：draft 草稿 / approved 已审批 / retired 已退役';
COMMENT ON COLUMN factor.factor_def.created_at IS '创建时间';

-- ---- factor.factor_value ----
COMMENT ON COLUMN factor.factor_value.symbol IS '股票代码，主键之一';
COMMENT ON COLUMN factor.factor_value.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN factor.factor_value.factor_code IS '因子代码，主键之一';
COMMENT ON COLUMN factor.factor_value.version IS '因子版本，主键之一';
COMMENT ON COLUMN factor.factor_value.raw_value IS '因子原始计算值';
COMMENT ON COLUMN factor.factor_value.std_value IS '标准化值（如 z-score）';
COMMENT ON COLUMN factor.factor_value.neutral_value IS '行业中性化后的值';
COMMENT ON COLUMN factor.factor_value.source IS '数据源标识';
COMMENT ON COLUMN factor.factor_value.run_id IS '跑批标识';

-- ---- factor.factor_version ----
COMMENT ON COLUMN factor.factor_version.version IS '版本号，主键';
COMMENT ON COLUMN factor.factor_version.applied_at IS '该版本应用生效时间';
COMMENT ON COLUMN factor.factor_version.weights_json IS '多因子合成权重配置（JSON）';
COMMENT ON COLUMN factor.factor_version.snapshot_json IS '因子集快照（构成因子与参数，用于复现）';
COMMENT ON COLUMN factor.factor_version.rollback_of IS '回滚自哪个版本；NULL 表示正向发布';
COMMENT ON COLUMN factor.factor_version.created_at IS '创建时间';

-- ---- factor.factor_report ----
COMMENT ON COLUMN factor.factor_report.report_id IS '自增主键';
COMMENT ON COLUMN factor.factor_report.factor_code IS '因子代码';
COMMENT ON COLUMN factor.factor_report.version IS '因子版本';
COMMENT ON COLUMN factor.factor_report.content_json IS '因子研究报告内容（JSON）';
COMMENT ON COLUMN factor.factor_report.report_url IS '研究报告文件链接';
COMMENT ON COLUMN factor.factor_report.created_at IS '创建时间';

-- ---- factor.factor_eval ----
COMMENT ON COLUMN factor.factor_eval.factor_code IS '因子代码，主键之一';
COMMENT ON COLUMN factor.factor_eval.version IS '因子版本，主键之一';
COMMENT ON COLUMN factor.factor_eval.ic_mean IS '平均信息系数 IC（预测力）';
COMMENT ON COLUMN factor.factor_eval.ir IS '信息比率（IC 均值 / IC 标准差）';
COMMENT ON COLUMN factor.factor_eval.turnover IS '换手率';
COMMENT ON COLUMN factor.factor_eval.mono_score IS '单调性得分（分组收益是否单调）';
COMMENT ON COLUMN factor.factor_eval.passed IS '是否通过评估门槛（进入合成候选）';
COMMENT ON COLUMN factor.factor_eval.report_url IS '评估报告链接';
COMMENT ON COLUMN factor.factor_eval.created_at IS '创建时间';

-- ---- signal.macro_signal ----
COMMENT ON COLUMN signal.macro_signal.as_of IS '适用期（月频，仅保留最新已发布一期），主键';
COMMENT ON COLUMN signal.macro_signal.regime IS '经济状态：复苏 / 过热 / 滞胀 / 衰退';
COMMENT ON COLUMN signal.macro_signal.money_credit IS '货币信用组合状态枚举：双宽 / 宽货币紧信用 / 紧货币宽信用 / 双紧（§1.7）';
COMMENT ON COLUMN signal.macro_signal.growth_s IS '增长维度得分';
COMMENT ON COLUMN signal.macro_signal.inflation_s IS '通胀维度得分';
COMMENT ON COLUMN signal.macro_signal.money_s IS '货币维度得分';
COMMENT ON COLUMN signal.macro_signal.credit_s IS '信用维度得分';
COMMENT ON COLUMN signal.macro_signal.equity_weight IS '权益仓位上限（建议，0~1）';
COMMENT ON COLUMN signal.macro_signal.style_json IS '风格配置（JSON：大盘/小盘/成长/价值 等权重）';
COMMENT ON COLUMN signal.macro_signal.asset_alloc_json IS '大类资产配置（JSON：股/债/商品 等）';
COMMENT ON COLUMN signal.macro_signal.confidence IS '信号置信度（0~1）';
COMMENT ON COLUMN signal.macro_signal.run_id IS '跑批标识';
COMMENT ON COLUMN signal.macro_signal.signal_json IS
  'MacroSignal 完整契约（§1.7）：regime / phase / money_credit / asset_alloc / factors / vintage / forecast_signals；页面只读，不回写';

-- ---- signal.macro_aux_signal ----
COMMENT ON COLUMN signal.macro_aux_signal.as_of IS '适用期，主键之一';
COMMENT ON COLUMN signal.macro_aux_signal.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN signal.macro_aux_signal.dr001 IS 'DR001 绝对水平（银行间质押式回购加权利率，%）';
COMMENT ON COLUMN signal.macro_aux_signal.dr001_ma20 IS 'DR001 20 日滚动均值';
COMMENT ON COLUMN signal.macro_aux_signal.dr001_pctile IS 'DR001 滚动分位（0~1）';
COMMENT ON COLUMN signal.macro_aux_signal.dr001_extreme IS '极端标记：high 高位 / low 低位 / normal 常态';
COMMENT ON COLUMN signal.macro_aux_signal.warn_flags IS '预警标记集合（JSON 数组：量价背离 / 税期季末扰动 等）';
COMMENT ON COLUMN signal.macro_aux_signal.aux_note IS '辅助说明（展示文案，不参与判定）';
COMMENT ON COLUMN signal.macro_aux_signal.run_id IS '跑批标识';

-- ---- signal.macro_forecast ----
COMMENT ON COLUMN signal.macro_forecast.signal_id IS '预测信号标识，主键';
COMMENT ON COLUMN signal.macro_forecast.chain IS '传导链（如 ppi_to_cpi / m1_growth）';
COMMENT ON COLUMN signal.macro_forecast.basis_period IS '依据数据所属期（仅已发布期）';
COMMENT ON COLUMN signal.macro_forecast.lead_window IS '领先窗口：short 短窗 1-2 月 / long 长窗 3-6 月';
COMMENT ON COLUMN signal.macro_forecast.direction IS '推断方向：up 上行 / down 下行 / flat 持平';
COMMENT ON COLUMN signal.macro_forecast.confidence IS '置信度（0~1）';
COMMENT ON COLUMN signal.macro_forecast.hit_rate_status IS '命中率状态：pending 待回测 / valid 已回测 / invalid 已失效';
COMMENT ON COLUMN signal.macro_forecast.invalid_if IS '失效条件（触发即降「参考级」）';
COMMENT ON COLUMN signal.macro_forecast.as_of IS '信号产出日（不得晚于 basis_period 的已发布期）';

-- ---- signal.meso_nowcast ----
COMMENT ON COLUMN signal.meso_nowcast.industry_code IS '行业代码，主键之一';
COMMENT ON COLUMN signal.meso_nowcast.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN signal.meso_nowcast.pe_pctile IS '行业 ETF 估值滚动分位（0~1）';
COMMENT ON COLUMN signal.meso_nowcast.fundflow_pctile IS '资金流分位（0~1）';
COMMENT ON COLUMN signal.meso_nowcast.crowding_pctile IS '拥挤度分位（0~1）';
COMMENT ON COLUMN signal.meso_nowcast.leverage_pctile IS '杠杆率分位（0~1）';
COMMENT ON COLUMN signal.meso_nowcast.direction IS '方向快照：confirm 印证 / divergence 背离 / risk_block 极端风险';
COMMENT ON COLUMN signal.meso_nowcast.block_new_entry IS '是否拦截新增（仅拦新增，不改清单与分数）';
COMMENT ON COLUMN signal.meso_nowcast.run_id IS '跑批标识';

-- ---- signal.industry_rank ----
COMMENT ON COLUMN signal.industry_rank.industry_code IS '行业代码，主键之一';
COMMENT ON COLUMN signal.industry_rank.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN signal.industry_rank.momentum_s IS '动量维度得分';
COMMENT ON COLUMN signal.industry_rank.valuation_s IS '估值维度得分';
COMMENT ON COLUMN signal.industry_rank.fundflow_s IS '资金流维度得分';
COMMENT ON COLUMN signal.industry_rank.crowding_s IS '拥挤度维度得分';
COMMENT ON COLUMN signal.industry_rank.total_score IS '综合得分';
COMMENT ON COLUMN signal.industry_rank.rank IS '综合排名（1 为最优）';
COMMENT ON COLUMN signal.industry_rank.etf_code IS '推荐跟踪该行业的 ETF 代码';
COMMENT ON COLUMN signal.industry_rank.weight IS '建议配置权重（0~1）';
COMMENT ON COLUMN signal.industry_rank.run_id IS '跑批标识';

-- ---- signal.stock_score ----
COMMENT ON COLUMN signal.stock_score.symbol IS '股票代码，主键之一';
COMMENT ON COLUMN signal.stock_score.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN signal.stock_score.industry_code IS '所属申万行业代码';
COMMENT ON COLUMN signal.stock_score.fundamental_s IS '基本面维度得分';
COMMENT ON COLUMN signal.stock_score.news_s IS '新闻情绪维度得分';
COMMENT ON COLUMN signal.stock_score.capital_s IS '资金面维度得分';
COMMENT ON COLUMN signal.stock_score.technical_s IS '技术面维度得分';
COMMENT ON COLUMN signal.stock_score.chip_s IS '筹码维度得分';
COMMENT ON COLUMN signal.stock_score.total_score IS '综合得分';
COMMENT ON COLUMN signal.stock_score.rank_in_industry IS '行业内排名';
COMMENT ON COLUMN signal.stock_score.rank_all IS '全市场排名';
COMMENT ON COLUMN signal.stock_score.advice IS '投资建议：buy 买入 / hold 持有 / sell 卖出 / watch 观察';
COMMENT ON COLUMN signal.stock_score.run_id IS '跑批标识';

-- ---- signal.signal ----
COMMENT ON COLUMN signal.signal.id IS '自增主键';
COMMENT ON COLUMN signal.signal.symbol IS '股票代码';
COMMENT ON COLUMN signal.signal.trade_date IS '信号交易日';
COMMENT ON COLUMN signal.signal.source_layer IS '来源层级：macro 宏观 / meso 中观 / micro 微观';
COMMENT ON COLUMN signal.signal.score IS '信号得分';
COMMENT ON COLUMN signal.signal.entry_price_ref IS '参考买入价';
COMMENT ON COLUMN signal.signal.industry_code IS '申万行业代码';
COMMENT ON COLUMN signal.signal.strategy_ver IS '策略版本';
COMMENT ON COLUMN signal.signal.reason_json IS '对内决策明细（对外裁剪时剔除，仅管理端可见）';
COMMENT ON COLUMN signal.signal.status IS '信号状态：active 有效 / expired 失效';
COMMENT ON COLUMN signal.signal.published_at IS '对外发布时间';

-- ---- signal.advice_batch ----
COMMENT ON COLUMN signal.advice_batch.batch_id IS '自增主键';
COMMENT ON COLUMN signal.advice_batch.as_of IS '适用期，关联 macro_signal.as_of';
COMMENT ON COLUMN signal.advice_batch.equity_weight IS '权益仓位上限（0~1）';
COMMENT ON COLUMN signal.advice_batch.asset_alloc_json IS '大类资产配置（JSON）';
COMMENT ON COLUMN signal.advice_batch.status IS '批次状态：open 开放 / closed 关闭';
COMMENT ON COLUMN signal.advice_batch.created_at IS '创建时间';

-- ---- signal.advice_node ----
COMMENT ON COLUMN signal.advice_node.id IS '自增主键';
COMMENT ON COLUMN signal.advice_node.batch_id IS '所属建议批次';
COMMENT ON COLUMN signal.advice_node.parent_id IS '父节点（自引用，根节点为 NULL）';
COMMENT ON COLUMN signal.advice_node.node_type IS '节点类型：asset 大类资产 / industry 行业 / stock 个股';
COMMENT ON COLUMN signal.advice_node.name IS '节点名称';
COMMENT ON COLUMN signal.advice_node.weight IS '节点权重（0~1）';
COMMENT ON COLUMN signal.advice_node.target_json IS '对外可见内容（股票代码/名称/权重；客户端展示用）';
COMMENT ON COLUMN signal.advice_node.reason_json IS '对内决策明细（对外裁剪时剔除，仅管理端可见）';

-- ---- portfolio.portfolio ----
COMMENT ON COLUMN portfolio.portfolio.id IS '自增主键';
COMMENT ON COLUMN portfolio.portfolio.name IS '组合名称';
COMMENT ON COLUMN portfolio.portfolio.kind IS '组合类型：virtual 虚拟 / live 实盘';
COMMENT ON COLUMN portfolio.portfolio.cash IS '现金余额';
COMMENT ON COLUMN portfolio.portfolio.base_currency IS '基准币种，默认 CNY';
COMMENT ON COLUMN portfolio.portfolio.created_at IS '创建时间';

-- ---- portfolio.position ----
COMMENT ON COLUMN portfolio.position.id IS '自增主键';
COMMENT ON COLUMN portfolio.position.portfolio_id IS '所属组合 ID';
COMMENT ON COLUMN portfolio.position.symbol IS '股票代码';
COMMENT ON COLUMN portfolio.position.qty IS '持仓数量';
COMMENT ON COLUMN portfolio.position.cost_price IS '持仓成本价';
COMMENT ON COLUMN portfolio.position.weight IS '持仓权重（组合内占比，0~1）';
COMMENT ON COLUMN portfolio.position.updated_at IS '更新时间';

-- ---- portfolio.order_proposal ----
COMMENT ON COLUMN portfolio.order_proposal.id IS '自增主键';
COMMENT ON COLUMN portfolio.order_proposal.portfolio_id IS '所属组合 ID';
COMMENT ON COLUMN portfolio.order_proposal.symbol IS '股票代码';
COMMENT ON COLUMN portfolio.order_proposal.side IS '买卖方向：buy 买入 / sell 卖出';
COMMENT ON COLUMN portfolio.order_proposal.qty IS '建议数量';
COMMENT ON COLUMN portfolio.order_proposal.price_ref IS '参考价';
COMMENT ON COLUMN portfolio.order_proposal.status IS '状态：pending 待确认 / confirmed 已确认 / rejected 已驳回 / filled 已成交';
COMMENT ON COLUMN portfolio.order_proposal.created_at IS '创建时间';
COMMENT ON COLUMN portfolio.order_proposal.confirmed_at IS '确认时间';

-- ---- portfolio.trade ----
COMMENT ON COLUMN portfolio.trade.id IS '自增主键';
COMMENT ON COLUMN portfolio.trade.portfolio_id IS '所属组合 ID';
COMMENT ON COLUMN portfolio.trade.symbol IS '股票代码';
COMMENT ON COLUMN portfolio.trade.side IS '买卖方向：buy / sell';
COMMENT ON COLUMN portfolio.trade.qty IS '成交数量';
COMMENT ON COLUMN portfolio.trade.price IS '成交价';
COMMENT ON COLUMN portfolio.trade.fee IS '手续费';
COMMENT ON COLUMN portfolio.trade.traded_at IS '成交时间';
COMMENT ON COLUMN portfolio.trade.proposal_id IS '关联调仓建议单（可为空）';

-- ---- portfolio.daily_mark ----
COMMENT ON COLUMN portfolio.daily_mark.portfolio_id IS '所属组合 ID，主键之一';
COMMENT ON COLUMN portfolio.daily_mark.trade_date IS '交易日，主键之一';
COMMENT ON COLUMN portfolio.daily_mark.market_value IS '当日市值';
COMMENT ON COLUMN portfolio.daily_mark.pnl IS '当日盈亏';
COMMENT ON COLUMN portfolio.daily_mark.cum_pnl IS '累计盈亏';
COMMENT ON COLUMN portfolio.daily_mark.benchmark_nav IS '基准净值（用于对比超额）';

-- ---- metric.signal_tracking ----
COMMENT ON COLUMN metric.signal_tracking.id IS '自增主键';
COMMENT ON COLUMN metric.signal_tracking.signal_id IS '关联信号 ID';
COMMENT ON COLUMN metric.signal_tracking.horizon IS '持有期（交易日数）';
COMMENT ON COLUMN metric.signal_tracking.ret IS '持有期收益率';
COMMENT ON COLUMN metric.signal_tracking.excess_ret IS '超额收益率（相对基准）';
COMMENT ON COLUMN metric.signal_tracking.win IS '是否盈利（胜）';
COMMENT ON COLUMN metric.signal_tracking.updated_at IS '更新时间';

-- ---- metric.winrate_stat ----
COMMENT ON COLUMN metric.winrate_stat.source_layer IS '来源层级：macro / meso / micro';
COMMENT ON COLUMN metric.winrate_stat.industry_code IS '行业代码';
COMMENT ON COLUMN metric.winrate_stat.horizon IS '持有期';
COMMENT ON COLUMN metric.winrate_stat.stat_date IS '统计日期';
COMMENT ON COLUMN metric.winrate_stat.samples IS '样本数';
COMMENT ON COLUMN metric.winrate_stat.win_rate IS '胜率（0~1）';
COMMENT ON COLUMN metric.winrate_stat.avg_ret IS '平均收益';
COMMENT ON COLUMN metric.winrate_stat.avg_excess IS '平均超额收益';
COMMENT ON COLUMN metric.winrate_stat.profit_loss_ratio IS '盈亏比';

-- ---- metric.backtest_task ----
COMMENT ON COLUMN metric.backtest_task.id IS '自增主键';
COMMENT ON COLUMN metric.backtest_task.params_json IS '回测参数（JSON：标的池/周期/手续费等）';
COMMENT ON COLUMN metric.backtest_task.data_version IS '数据版本 / 快照标识';
COMMENT ON COLUMN metric.backtest_task.status IS '状态：queued 排队 / running 运行中 / done 完成 / failed 失败';
COMMENT ON COLUMN metric.backtest_task.started_at IS '开始时间';
COMMENT ON COLUMN metric.backtest_task.ended_at IS '结束时间';

-- ---- metric.backtest_result ----
COMMENT ON COLUMN metric.backtest_result.id IS '自增主键';
COMMENT ON COLUMN metric.backtest_result.task_id IS '关联回测任务 ID';
COMMENT ON COLUMN metric.backtest_result.annual_ret IS '年化收益';
COMMENT ON COLUMN metric.backtest_result.volatility IS '年化波动率';
COMMENT ON COLUMN metric.backtest_result.sharpe IS '夏普比率';
COMMENT ON COLUMN metric.backtest_result.sortino IS '索提诺比率';
COMMENT ON COLUMN metric.backtest_result.max_drawdown IS '最大回撤';
COMMENT ON COLUMN metric.backtest_result.calmar IS '卡玛比率（年化收益 / 最大回撤）';
COMMENT ON COLUMN metric.backtest_result.win_rate IS '胜率';
COMMENT ON COLUMN metric.backtest_result.turnover IS '换手率';
COMMENT ON COLUMN metric.backtest_result.ic IS '信息系数';
COMMENT ON COLUMN metric.backtest_result.ir IS '信息比率';
COMMENT ON COLUMN metric.backtest_result.net_value_json IS '净值序列（JSON：日期-净值 数组）';

-- ---- task.task_run ----
COMMENT ON COLUMN task.task_run.id IS '自增主键';
COMMENT ON COLUMN task.task_run.task_code IS '任务标识（如 macro / meso / micro / assemble-risk）';
COMMENT ON COLUMN task.task_run.run_id IS '跑批标识（本次运行唯一）';
COMMENT ON COLUMN task.task_run.status IS '运行状态：running / done / skipped / failed';
COMMENT ON COLUMN task.task_run.window_date IS '数据窗口日（本批处理的数据截止日）';
COMMENT ON COLUMN task.task_run.started_at IS '开始时间';
COMMENT ON COLUMN task.task_run.ended_at IS '结束时间';
COMMENT ON COLUMN task.task_run.rows IS '处理行数';
COMMENT ON COLUMN task.task_run.error IS '错误信息（失败时有值）';
COMMENT ON COLUMN task.task_run.source_stats IS '数据源统计（JSON：各源行数/耗时）';

-- ---- task.agent_run ----
COMMENT ON COLUMN task.agent_run.id IS '自增主键';
COMMENT ON COLUMN task.agent_run.agent_code IS 'Agent 标识（macro-daily / macro-monthly / meso-daily / meso-monthly / micro，按频率独立成任务）';
COMMENT ON COLUMN task.agent_run.run_id IS '跑批标识，关联 task_run.run_id';
COMMENT ON COLUMN task.agent_run.data_items IS '本次采集的数据种类清单（JSON 数组，AD-02「采集了哪些数据」展示用）';
COMMENT ON COLUMN task.agent_run.rows_fetched IS '采集条数';
COMMENT ON COLUMN task.agent_run.missing_json IS '缺失明细（JSON：缺失范围与类型；无缺失为空）';
COMMENT ON COLUMN task.agent_run.latency_ms IS '耗时（毫秒）';
COMMENT ON COLUMN task.agent_run.created_at IS '记录时间';

-- ---- task.data_item ----
COMMENT ON COLUMN task.data_item.id IS '数据项编码，主键（不可变；删除判引用只看本列）';
COMMENT ON COLUMN task.data_item.name IS '数据项名称（全库唯一、可改）';
COMMENT ON COLUMN task.data_item.freq IS '数据频率：daily 日频 / monthly 月频 / quarterly 季频';
COMMENT ON COLUMN task.data_item.factor_layer IS '所属因子层：macro 宏观 / meso 中观 / micro 微观';
COMMENT ON COLUMN task.data_item.api IS '取数接口标识';
COMMENT ON COLUMN task.data_item.publish_slot IS '发布时点（如 每月 10-20 日 / 每月 15 日）';
COMMENT ON COLUMN task.data_item.job_code IS '挂载任务标识（未挂载时为空）';
COMMENT ON COLUMN task.data_item.rows IS '累计行数';
COMMENT ON COLUMN task.data_item.latest_period IS '库内最新期次';
COMMENT ON COLUMN task.data_item.gap_periods IS '库内最新期次与官方最新可获取之间的缺口期数（服务端算，前端不勾选）';
COMMENT ON COLUMN task.data_item.last_fetch_at IS '最近拉取时间';
COMMENT ON COLUMN task.data_item.status IS '状态：active 启用 / inactive 停用';
COMMENT ON COLUMN task.data_item.created_at IS '创建时间';
COMMENT ON COLUMN task.data_item.updated_at IS '修改时间';

-- ---- task.data_ref ----
COMMENT ON COLUMN task.data_ref.id IS '自增主键';
COMMENT ON COLUMN task.data_ref.data_id IS '数据项编码，关联 task.data_item.id';
COMMENT ON COLUMN task.data_ref.used_by IS '引用方标识（策略 / 报表 / 任务）';
COMMENT ON COLUMN task.data_ref.kind IS '引用类别：strategy 策略 / report 报表';
COMMENT ON COLUMN task.data_ref.note IS '备注';
COMMENT ON COLUMN task.data_ref.created_at IS '创建时间';

-- ---- task.run_log ----
COMMENT ON COLUMN task.run_log.id IS '自增主键';
COMMENT ON COLUMN task.run_log.started_at IS '开始时间';
COMMENT ON COLUMN task.run_log.job_code IS '任务标识';
COMMENT ON COLUMN task.run_log.item_ids IS '涉及的数据项编码数组（JSON 数组；删除数据项时按此联动清理）';
COMMENT ON COLUMN task.run_log.err_type IS '错误类型（失败时记录）';
COMMENT ON COLUMN task.run_log.result_text IS '结果摘要';
COMMENT ON COLUMN task.run_log.lv IS '处置级别：wait 待处理 / done 已完成（NULL 表示未分类）';
COMMENT ON COLUMN task.run_log.retry_cnt IS '重试次数';
COMMENT ON COLUMN task.run_log.trigger_type IS '触发方式：auto 调度 / manual 手动 / rerun 补跑';
COMMENT ON COLUMN task.run_log.cost_ms IS '耗时（毫秒）';
COMMENT ON COLUMN task.run_log.detail_msg IS '明细';
COMMENT ON COLUMN task.run_log.created_at IS '记录时间';

-- ---- task.schedule_config ----
COMMENT ON COLUMN task.schedule_config.task_code IS '任务标识，主键';
COMMENT ON COLUMN task.schedule_config.cron_expr IS '系统侧默认 cron 基线（日频 0 2 * * *；宏观月频窗口 0 2 10-20 * *）；实际执行以 WorkBuddy 自动化任务为准（task.job_def）';
COMMENT ON COLUMN task.schedule_config.enabled IS '是否启用';
COMMENT ON COLUMN task.schedule_config.updated_by IS '最后修改人';
COMMENT ON COLUMN task.schedule_config.updated_at IS '修改时间';

-- ---- task.job_def ----
COMMENT ON COLUMN task.job_def.job_key IS '任务键，主键（macro_daily / macro_monthly / meso_daily / meso_monthly / micro_daily / risk_assemble / tracking_daily / portfolio_daily / factor_lab / backtest_run）';
COMMENT ON COLUMN task.job_def.job_name IS '任务中文名（AD-11 任务清单展示）';
COMMENT ON COLUMN task.job_def.freq IS '任务频率：daily 日频 / monthly 月频 / weekly 周频 / manual 按需；同层不同频率独立成 job（C-12）';
COMMENT ON COLUMN task.job_def.cron_expr IS 'cron 表达式（5 段标准格式，如 0 2 * * *；月频窗口 0 2 10-20 * *）；按需任务为空；不得落在 9:30-15:00（SC-02/06）';
COMMENT ON COLUMN task.job_def.cli_command IS '对应 Python CLI 命令（如 python -m agent.macro_daily）';
COMMENT ON COLUMN task.job_def.params_json IS '任务参数（JSON：指标组、重试策略、窗口等）';
COMMENT ON COLUMN task.job_def.automation_id IS 'WorkBuddy 自动化任务 ID（平台创建后回写，双写关联键）';
COMMENT ON COLUMN task.job_def.run_node IS '执行节点（线下 offline-node；sync 类任务同为该节点）';
COMMENT ON COLUMN task.job_def.retry_cnt IS '失败重试次数（指数退避）';
COMMENT ON COLUMN task.job_def.timeout_sec IS '超时秒数（默认 30 分钟，NFR-01）';
COMMENT ON COLUMN task.job_def.enabled IS '是否启用（AD-11 启停操作）';
COMMENT ON COLUMN task.job_def.updated_by IS '最后修改人（AD-11，留审计）';
COMMENT ON COLUMN task.job_def.updated_at IS '修改时间';

-- ---- task.job_instance ----
COMMENT ON COLUMN task.job_instance.id IS '自增主键';
COMMENT ON COLUMN task.job_instance.job_key IS '任务键，关联 task.job_def.job_key';
COMMENT ON COLUMN task.job_instance.run_id IS '跑批标识（与 task_run.run_id / agent_run.run_id 串联 trace）';
COMMENT ON COLUMN task.job_instance.automation_run_id IS '平台侧执行流水号（WorkBuddy 回写，用于对账）';
COMMENT ON COLUMN task.job_instance.trigger_type IS '触发方式：auto 调度自动 / manual 手动立即执行 / rerun 补跑';
COMMENT ON COLUMN task.job_instance.scheduled_at IS '计划触发时间';
COMMENT ON COLUMN task.job_instance.started_at IS '实际开始时间';
COMMENT ON COLUMN task.job_instance.ended_at IS '结束时间';
COMMENT ON COLUMN task.job_instance.duration_ms IS '耗时（毫秒，AD-11 展示）';
COMMENT ON COLUMN task.job_instance.status IS '执行状态：running / success / failed / timeout / retrying';
COMMENT ON COLUMN task.job_instance.exit_code IS 'CLI 退出码（0 正常）';
COMMENT ON COLUMN task.job_instance.retry_cnt IS '本次执行已重试次数';
COMMENT ON COLUMN task.job_instance.log_summary IS '执行日志摘要（AD-11 列表展示；全量日志按需从线下 WorkBuddy 侧拉取）';
COMMENT ON COLUMN task.job_instance.operator IS '操作人（manual / rerun 时记录，留审计）';
COMMENT ON COLUMN task.job_instance.created_at IS '记录时间';

-- ---- task.rerun_request ----
COMMENT ON COLUMN task.rerun_request.id IS '自增主键';
COMMENT ON COLUMN task.rerun_request.agent_code IS '目标 Agent（macro-daily / macro-monthly / meso-daily / meso-monthly / micro，按频率独立成任务）';
COMMENT ON COLUMN task.rerun_request.date_from IS '补跑起点（日期或月份首日）';
COMMENT ON COLUMN task.rerun_request.date_to IS '补跑终点';
COMMENT ON COLUMN task.rerun_request.data_type IS '数据类型（指标 / 行业 / 股票，如 CPI / industry_daily / daily_bar）';
COMMENT ON COLUMN task.rerun_request.target_keys IS '目标对象清单（JSON：指标代码 / 行业代码 / 股票代码列表；空表示该类型全部）';
COMMENT ON COLUMN task.rerun_request.requested_by IS '发起人（AD-09 数据管理，写操作留审计）';
COMMENT ON COLUMN task.rerun_request.status IS '状态：pending / running / done / failed';
COMMENT ON COLUMN task.rerun_request.created_at IS '创建时间';
COMMENT ON COLUMN task.rerun_request.finished_at IS '完成时间';

-- ---- task.quality_alert ----
COMMENT ON COLUMN task.quality_alert.id IS '自增主键';
COMMENT ON COLUMN task.quality_alert.task_code IS '关联任务标识';
COMMENT ON COLUMN task.quality_alert.data_item IS '数据项名称';
COMMENT ON COLUMN task.quality_alert.check_type IS '检查类型：freshness 时效性 / range 范围 / schema 结构 / consistency 一致性';
COMMENT ON COLUMN task.quality_alert.severity IS '严重度：warn 警告 / error 错误';
COMMENT ON COLUMN task.quality_alert.detail IS '告警详情';
COMMENT ON COLUMN task.quality_alert.handled_by IS '处理人';
COMMENT ON COLUMN task.quality_alert.created_at IS '创建时间';

-- ---- task.source_health ----
COMMENT ON COLUMN task.source_health.source IS '数据源标识（xy / westock / akshare），主键';
COMMENT ON COLUMN task.source_health.status IS '状态：ok 正常 / degraded 降级 / down 不可用';
COMMENT ON COLUMN task.source_health.last_trade_date IS '最近获取到的交易日数据';
COMMENT ON COLUMN task.source_health.last_source IS '实际获取来源';
COMMENT ON COLUMN task.source_health.latency_ms IS '抓取延迟（毫秒）';
COMMENT ON COLUMN task.source_health.checked_at IS '检查时间';

-- ---- platform.admin_user ----
COMMENT ON COLUMN platform.admin_user.id IS '自增主键';
COMMENT ON COLUMN platform.admin_user.username IS '管理员登录用户名（唯一）';
COMMENT ON COLUMN platform.admin_user.password_hash IS '密码哈希';
COMMENT ON COLUMN platform.admin_user.mfa_secret IS 'MFA 密钥（启用二次验证时使用）';
COMMENT ON COLUMN platform.admin_user.status IS '状态：active / disabled';
COMMENT ON COLUMN platform.admin_user.last_login_at IS '最后登录时间';

-- ---- platform.role ----
COMMENT ON COLUMN platform.role.id IS '自增主键';
COMMENT ON COLUMN platform.role.code IS '角色代码（唯一）';
COMMENT ON COLUMN platform.role.name IS '角色名称';

-- ---- platform.permission ----
COMMENT ON COLUMN platform.permission.id IS '自增主键';
COMMENT ON COLUMN platform.permission.code IS '权限代码（唯一）';
COMMENT ON COLUMN platform.permission.name IS '权限名称';

-- ---- platform.admin_role ----
COMMENT ON COLUMN platform.admin_role.admin_id IS '管理员 ID';
COMMENT ON COLUMN platform.admin_role.role_id IS '角色 ID';

-- ---- platform.role_permission ----
COMMENT ON COLUMN platform.role_permission.role_id IS '角色 ID';
COMMENT ON COLUMN platform.role_permission.permission_id IS '权限 ID';

-- ---- platform.audit_log ----
COMMENT ON COLUMN platform.audit_log.id IS '自增主键，复合主键之一';
COMMENT ON COLUMN platform.audit_log.actor_type IS '操作主体类型：user 用户 / admin 管理员 / system 系统';
COMMENT ON COLUMN platform.audit_log.actor_id IS '操作主体 ID';
COMMENT ON COLUMN platform.audit_log.action IS '操作类型（如 create / update / delete / login）';
COMMENT ON COLUMN platform.audit_log.object_type IS '操作对象类型';
COMMENT ON COLUMN platform.audit_log.object_id IS '操作对象 ID';
COMMENT ON COLUMN platform.audit_log.before IS '变更前内容（JSON）';
COMMENT ON COLUMN platform.audit_log.after IS '变更后内容（JSON）';
COMMENT ON COLUMN platform.audit_log.ip IS '来源 IP';
COMMENT ON COLUMN platform.audit_log.created_at IS '创建时间，复合主键之一（兼分区键）';

