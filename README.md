# 财务报表自动提取工具

将审计报告 PDF 放入监控文件夹，自动解析报表、提取财务指标、按年度归档。

## 功能

- 自动解析 PDF（MinerU pipeline 模式）
- 调用 DeepSeek API 提取 12 个财务指标
- 跳过审计意见正文，只保留主表 + 附注数据
- 按年度自动分文件夹输出 CSV
- 处理完成后 PDF 自动重命名归档到 success/

## 环境要求

- Python 3.10 ~ 3.12
- 8GB+ 内存（处理大 PDF 建议 16GB）
- DeepSeek API Key

## 安装

```bash
pip install "mineru[all]" watchdog openai
```

首次运行会自动下载 MinerU 模型（约 2-3GB），请确保网络通畅。

## 使用

### 1. 设置 API Key

```bash
# Windows CMD
set DEEPSEEK_API_KEY=sk-你的key

# Windows PowerShell
$env:DEEPSEEK_API_KEY="sk-你的key"
```

建议永久添加到系统环境变量。

### 2. 运行

```bash
# 一次性处理 input_pdfs/ 中所有 PDF（处理完退出）
python batch_extract.py --run-once

# 持续监控 input_pdfs/（放入新 PDF 自动处理）
python batch_extract.py --watch
```

### 3. 放入 PDF

将审计报告 PDF 复制到 `input_pdfs/` 文件夹，脚本会自动处理。

## 输出说明

```
ocr工具/
├── financial_data_2024.csv   ← 2024 年度指标数据
├── financial_data_2025.csv   ← 2025 年度指标数据
├── financial_data_其他.csv   ← 年度识别失败的兜底
├── input_pdfs/               ← 放待处理 PDF
├── success/                  ← 处理完成的归档 PDF
└── output/                   ← MinerU 中间缓存
```

### CSV 表头

```
客户名称, 营业收入, 主营业务收入, 营业成本, 主营业务成本,
利润总额, 净利润, 研发费用, 销售费用, 管理费用,
资产总额, 负债总额, 所有者权益, 处理时间
```

### 归档命名

```
{公司名称}_{年度}_{报表类型}.pdf
# 例如: 晶创科技有限公司_2024_审计报告.pdf
```

报表类型自动判定：同时包含资产负债表、利润表和附注章节的归为"审计报告"，否则归为"财务报表"。

## 提取的指标

| 指标 | 说明 |
|------|------|
| 营业收入 | 合并利润表第一行 |
| 主营业务收入 | 附注中营业收入明细 |
| 营业成本 | 合并利润表 |
| 主营业务成本 | 附注中营业成本明细 |
| 利润总额 | 合并利润表 |
| 净利润 | 合并利润表 |
| 研发费用 | 附注明细 |
| 销售费用 | 附注明细 |
| 管理费用 | 附注明细 |
| 资产总额 | 合并资产负债表 |
| 负债总额 | 合并资产负债表 |
| 所有者权益 | 合并资产负债表 |

缺失的指标填"未披露"。

## 迁移到新电脑

```bash
git clone https://github.com/fine-wen/financial-report-extractor.git
cd financial-report-extractor
pip install "mineru[all]" watchdog openai
set DEEPSEEK_API_KEY=sk-你的key
python batch_extract.py --run-once
```
