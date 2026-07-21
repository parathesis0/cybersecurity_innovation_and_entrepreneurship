# 网络安全创新创业课程作业 1

本目录是作业 1 的完整提交材料，主题为：

> 在 Bitcoin Testnet4 发送一笔交易，逐字节解析原始交易与锁定/解锁脚本，并解析包含该交易的完整区块。

## 提交文件

- `REPORT.md`：Markdown 报告。

- `REPORT.docx`：Word 报告。
- `tx.txt`：最终广播交易的原始十六进制。
- `imgs/`：Sparrow Wallet 实验过程截图。
- `scripts/parse_bitcoin.py`：无第三方依赖的交易、签名和区块解析验证脚本。
- `scripts/build_report.py`：以作业 2 的 `REPORT.docx` 为样式模板重建报告。
- `scripts/reproduce.ps1`：一键重新生成证据和报告。
- `evidence/tx_parse.txt`：222 字节交易的完整字段表与 BIP143/ECDSA 验证结果。
- `evidence/block-144878.hex`：高度 144878 的完整 Testnet4 区块原始数据。
- `evidence/block_parse.txt`：4045 字节区块的完整字段表及 PoW、Merkle、witness commitment 验证结果。

## 核心结果

- txid：`1dd070a132e4c5dd1ab2fde424b82903a53e6afa22b921d9448590b71a5bcda7`
- 确认区块：Testnet4 高度 `144878`
- 输入：`394,027 sats`
- 输出：`114,514 sats + 277,258 sats`
- 实际手续费：`2,255 sats`
- 精确费率：约 `16.08 sat/vB`，对应最终使用的 16× 设置
- 自动验证：txid、wtxid、BIP143 ECDSA、PoW、交易 Merkle 根、SegWit witness commitment 和逐字节覆盖全部通过

## 复现

安装 `python-docx` 后，在 PowerShell 中运行：

```powershell
.\scripts\reproduce.ps1
```

只验证交易与区块、不重建 Word 报告时运行：

```powershell
python .\scripts\parse_bitcoin.py
```
