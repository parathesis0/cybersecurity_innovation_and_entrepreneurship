# 网络安全创新创业课程作业 2

本目录是作业 2 的完整提交材料，主题为：

> 调研 `bitcoin-core/secp256k1` 中与 Bitcoin 密码算法有关的安全修复和性能优化，解释问题成因、修复理由及背后的数学原理。

预期目录结构如下，`assignment-2` 与仓库保持同级：

```text
day1/
├── assignment-2/
│   ├── REPORT.md
│   ├── REPORT.docx
│   ├── evidence/
│   └── scripts/
└── secp256k1/
```

## 提交文件

- `REPORT.md`：Markdown 报告。
- `REPORT.docx`：报告的 Word 版本。
- `scripts/ecdsa_hash_forgery_demo.py`：复现课件中的“未校验消息时伪造 ECDSA 签名”实验。
- `scripts/rfc6979_reduction_demo.py`：复现 RFC 6979 中 `bits2octets`/模群阶归约的差异。
- `scripts/reproduce.ps1`：重新构建、测试、运行演示和基准测试的 PowerShell 脚本。
- `evidence/benchmark-current.txt`：本机基准测试结果。
- `evidence/verification.txt`：构建与测试环境、验证结论。

## 快速复现

在 PowerShell 中进入本目录后运行：

```powershell
python .\scripts\ecdsa_hash_forgery_demo.py
python .\scripts\rfc6979_reduction_demo.py
```

要重新构建仓库并运行完整测试：

```powershell
.\scripts\reproduce.ps1
```

完整测试在本机约需 2 分钟。脚本使用仓库根目录下被 `.gitignore` 忽略的 `build-assignment2` 构建目录。
`reproduce.ps1` 使用自身位置查找同级的 `secp256k1`，因此可以从任意当前工作目录启动。
